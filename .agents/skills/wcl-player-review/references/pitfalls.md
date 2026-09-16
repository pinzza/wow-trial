# 实测陷阱清单（WCL V1 API + 分析口径）

> 全部条目均在真实会话中踩过并验证。每条附"现象 → 正确做法"。

---

## A. events 端点（**最大的坑区**）

### A1. 带 `sourceid` 时 `type` / `abilityid` 过滤会被完全忽略

**现象**：同一战斗窗口分别请求 `type=cast`、`type=damage`、`abilityid=某技能`，三次返回**完全相同**的全部事件（实测 33,208 条，且其中混有 boss 的技能与其他 actor）。

**正确做法**：**只请求一次**（不带 `type`），拿回后在本地按 `sourceID` / `guid` / `type` 过滤。附带好处是拿到完整事件流，性能反而更好。

### A2. `sourceid` 过滤本身不彻底

**现象**：首页 10,005 条里 9,063 条是目标玩家，其余混入其他玩家/宠物。
**正确做法**：本地精确过滤 `e["sourceID"] == sid`，并**保留 `sourceID`/`targetID` 字段**（第一版脚本把 sourceID 丢了，只能重写）。

### A3. `crit` 字段不存在 → 暴击率恒为 0

**现象**：直接读 `e.get("crit")` 得到全 0，暴击率算成 0.0%，**直接毁掉整个基准归一化**。
**正确做法**：用 `hitType`：`1` = 普通命中，`2` = 暴击。

### A4. 分页

用 `nextPageTimestamp` 循环，单页上限 1 万条：

```python
cur, guard = start, 0
while cur is not None and cur < end:
    guard += 1
    if guard > 80: break
    d = get(f"/report/events/{code}", {"start": cur, "end": end, "sourceid": sid})
    ev = d.get("events", [])
    out.extend(ev)
    nxt = d.get("nextPageTimestamp")
    if not ev or nxt is None or nxt <= cur: break
    cur = nxt
    time.sleep(0.2)
```

### A5. `filter` 语法

- `filter='type="cast"'` ✅ 有效
- `filter='type="cast" and source.id=X'` ❌ 返回 0 条

### A6. `report/events` 的 `source` 字段不可靠

敌方技能 cast 事件的 `source` 会落成玩家名，字段映射不可靠，用于敌方时间轴时必须交叉验证。

---

## B. 数据库（7 表 SQLite）

### B1. `event` 表的 `type='cast'` 行不是按键次数

`v1_pipeline.py` 把 events 端点返回的**所有**事件硬编码成 `type="cast"`，其中混有 damage / heal / applybuff 的 tick。

**实测**：某技能显示 3,521 次 "cast"，实际是 DoT 跳动；某场 `type='cast'` 有 21.5 万行，真实按键只有约 880 次。

**规则**：
- **施法次数只信 `tables/casts` 端点**（或重新拉 events 并本地过滤）
- event 表仅用于**取时间点**，且必须去重

### B2. event 表列名

是 `source` / `target` / `ability_name`，**不是** `source_name`（会报 `no such column`）。

### B3. 时间戳语义不一致

同一张 `event` 表内：
- death 事件 timestamp = **战斗内相对毫秒**（如 75845 → 1:15）
- CD cast 事件 timestamp = **报告内相对毫秒**（如 7482928）

**跨两者比较前必须减 `fight.start_time`**。

### B4. 报告级聚合污染

`player` / `ability` / `npc` 的 `fight_id` 恒为 1（整份报告聚合，不按战斗分组）。**单次异常施法可能来自别的 pull**。要战斗内精确数据必须走 API + `start`/`end`。

### B5. DB 里没有的字段

- `activeTime` → 用 `damage_total ÷ dps` 自己算
- `combatantInfo`（装备 / 属性 rating / 天赋树 / 开场 auras）→ 只能从 `tables/summary` 或 `type=combatantinfo` 事件拿
- 逐次事件的 `hitType` → 没有

### B6. `hero_talent` 列为空

无法从 DB 判定英雄天赋 → 用标志性技能签名或 combatantInfo 天赋树。

### B7. `player.parse_pct` 的语义被复用为 `total_casts`

不要当解析百分比用。

### B8. URL 的 `source=` ≠ DB 的 `player.id`

实测 `source=411` → `player.id=2`。一律用**玩家名**或 class/spec 定位。
events 端点的 `sourceID` 对应 `/report/fights` 里 `friendlies[].id`。

---

## C. table 端点

### C1. 已知失败端点

| 端点 | 现象 |
|---|---|
| `tables/resources/` | 空响应 / `Expecting value: line 1 column 1`（每次必失败） |
| `tables/auras/` | HTTP 400 |
| `tables/buffs/` | 可用，但**只有队伍级** aura（所有玩家共享同一列表） |

### C2. `tables/healing` 静默返回空

必须**同时**带 `start` + `end` + `sourceid` + `by=ability`，缺任一参数返回 0 条 entry，不报错。

### C3. 过量治疗的污染行

算过量率前过滤 `total <= 0`（存在 `战火淬炼 Damage = -4,675,039` 这类负行）。
净值 vs by=ability 正值合计会对不上（实测 DB `heal_total` 142,368,688 vs by=ability 147,043,850），**报告里要说明用了哪个口径**。

### C4. `tables/damage-done` 全局调用才有 `activeTime`

带 `sourceid` 的调用不返回该字段。

---

## D. 环境与工具

### D1. `/tmp` 不持久

**每次 bash 调用是独立 shell，`/tmp` 里的文件在下一次调用就没了。** 中间产物写 `data/cache/<tag>/` 或仓库内 `tmp/`。

### D2. Python 环境

用**系统 `python3`**（3.12，requests + pydantic 齐全）。项目 `venv/bin/python`（3.11）**缺 pydantic**，跑不了 `core/` 管线。
曾有"以为缺 requests"而 `pip install --target tmp/wcl_deps` 的操作，实际装成 win_amd64 wheel 且系统本就有 requests —— **不要重蹈**。

### D3. API 稳定性

`SSLEOFError: UNEXPECTED_EOF_WHILE_READING` 常见，疑似与并发后台任务争抢有关。

```python
for attempt in range(4):
    try:
        ...
    except HTTPError as e:
        if e.code in (429, 500, 502, 503) and attempt < 3:
            time.sleep(2 ** attempt); continue
        raise
    except Exception:
        time.sleep(1 + attempt)
```

抓取尽量**串行**，请求间隔 `sleep(0.15~0.2)`。

### D4. 中文 / 生僻字路径必须加引号

`丨`、`丶`、中文字符在 shell 里不加引号会出错。

### D5. PDF 校验方式

`pdfinfo` 看页数 + `pdftotext - | head` 看文本层。**不要用 `read_image` 目视截图**——部分模型不支持图片输入，白白浪费一轮。

### D6. 缓存文件互相覆盖

`core/m2_standalone_summary.py` 的输出文件名是固定的（`data/cache/m2_meta.txt` 等），**跑第二份报告会覆盖第一份**。实测曾把 +19 的 meta 当成低层 DH 的 meta 来读。跨报告对比时要么立即消费，要么自行改名保存。

---

## E. 分析口径陷阱

| # | 陷阱 | 正确做法 |
|---|---|---|
| E1 | 跨层直接比 DPS/HPS | 先归一化；不同层必须显式声明不可直接比 |
| E2 | 用 `k_all` 归除非暴击每发 | 两个因子分开用（见 methodology.md §4） |
| E3 | 按技能名匹配 | 一律按 spell_id/guid |
| E4 | 伤害表 `casts=0` 当 0 次施法 | 那是被动/触发技 |
| E5 | 孤立评判某个占比 | 先看总掉血/总时长/层数 |
| E6 | 把"低层保守"当"手法差" | 降级为纪律性建议，写明客观原因 |
| E7 | 把队伍级断档当个人发呆 | 与队友断档时间点交叉验证 |
| E8 | 把锅全甩给玩家或全甩给环境 | 给百分比拆解 |
| E9 | 引用 percentile 作水平判据 | 实测 rank 与 percentile 语义会自相矛盾，只作参考并加免责说明 |
| E10 | 臆造"正确循环" | 不确定就只做相对比较 |
| E11 | 用讽刺/情绪化措辞 | 中性表述，对就是对错就是错 |
| E12 | 缺合剂/食物/符文没写进 P0 | 这是**最容易改**的个人项，必须显眼 |
