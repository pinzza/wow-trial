---
name: wcl-player-review
description: "给定两条 Warcraft Logs 链接（待分析记录 + 对标榜样），量化评估某个玩家的输出水平或治疗水平，产出中文 Markdown + PDF 报告。当用户说「分析这份 WCL 记录」「这个人的输出/伤害/治疗水平怎么样」「和这份记录对比」「以 X 伤害为基准拉平装等」「结合施法顺序分析平稳期/爆发期」「出个复盘报告/PDF」时使用。覆盖 DPS 与治疗两条分支，含装等归一化、施法序列与爆发窗口分析、敌我时间轴交叉、P0/P1/P2 改进清单。"
version: 1.0.0
metadata:
  tags: [wow, warcraft-logs, mythic-plus, performance-review, dps, healing, report]
  derived_from: "4 个真实会话的方法论提炼（噬灭DH / 元素萨满 / 武器战 / 神圣圣骑士，2026-09）"
---

# WCL 玩家水平复盘（输出 / 治疗）

## 这个 skill 解决什么

用户丢两条 WCL 链接：

- **A = 待分析记录**（"他伤害怎么这么低？"）
- **B = 对标榜样**（"另一个人的同副本记录，他伤害就很高"）

要求：判断 A 里某个角色**真实水平如何**，把"层数差 / 装等差 / 队伍环境差"从"个人手法差"里剥离出来，最后落地成报告。

**核心洞察：原始 DPS/HPS 高低几乎不能说明水平。** 必须做归一化 + 时间轴 + 环境排除，才能给出可信结论。本 skill 的全部价值就在这三件事上。

---

## 铁律（违反任意一条，报告即失效）

1. **先对齐可比性，再谈高低。** 必须同副本、同专精、同英雄天赋；层数不同则**禁止**直接比 DPS/HPS/总量——它们都是层数的函数。
2. **先确认英雄天赋与版本，再确定技能池，最后评价手法。** 顺序不可逆。历史上模型曾给"铸光者"圣骑士写"圣洁鸣钟"（该天赋根本没有此技能），整份报告作废。`player.hero_talent` 列为空，必须靠标志性技能签名或 `tables/summary` 的 `combatantInfo` 反推。
3. **不确定职业循环就不要编。** 只做可量化的相对比较（每发倍率、次数比、频率比、窗口密度）。宁可写"相对差距 X%"，也不要臆造"正确循环应该是……"。
4. **所有占比都是相对量**，禁止孤立评判某一个百分比。先看团队总掉血/总战斗时长/层数，再看单技能占比。（事故：把"神圣壁垒占比 19.4%"单独判为"靠被动兜底"，实际是低层团队掉血少导致主动治疗空间小。）
5. **施法次数只信 `tables/casts` 端点。** DB 的 `event` 表把 events 端点返回的所有事件都标成 `type='cast'`，混有 DoT tick，直接把 tick 当按键会得出荒谬结论。
6. **跨技能对比一律按 spell_id/guid 匹配，禁止按名字。** 同一技能常有多个 spell_id（地震术伤害 77478 / 施法 61882），跨语言客户端名字更不可靠。
7. **结论必须区分"客观因素"与"个人可改"**，并给百分比拆解 + 一个"合理上限"估数。禁止把锅全甩给玩家，也禁止把玩家的错误归给环境。
8. **全程中性措辞。** 对就是对、错就是错。**禁止讽刺、反讽、情绪化形容词**。（用户原话："不要用讽刺这种形容词"。）
9. **交付前如实写方法局限**（样本量、端点缺失、口径假设、无法验证的部分）。

---

## 执行流程

### Phase 0 · 解析输入与可比性检查

从两条 URL 抠出三要素，`?fight=N` 与 `&source=M` **都要取**：

```
https://cn.warcraftlogs.com/reports/<CODE>?fight=<N>&type=damage-done&source=<M>
                                    ^code        ^fight-id              ^URL source
```

- [ ] 两条记录是否**同一副本**？层数各是多少？（层数不同 → 走 Phase 3 归一化，并在报告里显式声明不可直接比）
- [ ] 是否**同一专精 + 同一英雄天赋**？（不同 → 需要额外说明偏差，或请用户换对标）
- [ ] 若用户指定了"以 X 技能伤害为基准"，记录该技能；未指定则按 `references/methodology.md` 选型规则挑选，并在报告中说明**为什么选它**。
- [ ] 明确产出格式（默认 Markdown + PDF）。

> 若只能拿到不同层的对标，**优先在同一份报告里找第二个同专精玩家**做同层对照——同队、同层、同装备档次，能把"环境差"和"个人差"分得最干净。实测比强行跨层对比有价值得多。

### Phase 1 · 入库（每份报告一个 SQLite）

```bash
PYTHONPATH=. python3 core/v1_pipeline.py <CODE> --fight-id <N> --db-dir data/wcl_db
```

- 用**后台任务**跑（每份约 60 次 API 请求，1–3 分钟），再收结果。
- 用**系统 `python3`**（3.12，依赖齐全）；`venv/bin/python` 缺 pydantic。
- `tables/resources/` 与 `tables/auras/` 会稳定失败，属已知限制，忽略即可。

### Phase 2 · 定位坐标（**必做，防止分析错人**）

```sql
SELECT DISTINCT keystone_level, keystone_time FROM fight;   -- 层数 / 限时
SELECT * FROM player ORDER BY dps DESC;                      -- 名字 / class / spec / ilvl
SELECT MIN(start_time), MAX(end_time) FROM fight;            -- 战斗窗口（后续 events 要用）
```

⚠️ **URL 的 `source=` ≠ DB 的 `player.id`**。实测：URL `source=411` → DB `player.id=2`。
events 端点的 `sourceID` 对应 `/report/fights/{code}` 里 `friendlies[].id`，需要用玩家名去对：

```python
requests.get(f"https://www.warcraftlogs.com/v1/report/fights/{code}",
             params={"api_key": KEY, "translate": "true"})
# → friendlies[].id / .name
```

**必须做这一步**，否则后面拉到的施法序列是别人的。

### Phase 3 · 基准归一化（剥离装等）

选一个**纯单体、伤害与目标数无关、每发只随面板属性线性缩放**的技能作"装等标尺"。选型理由与两个等价公式见 **`references/methodology.md`**。

已验证的基准选择范例：

| 专精 | 基准技能 | spell_id | 理由 |
|---|---|---|---|
| 噬灭 DH | 吞噬 Devour | 1217610 | 纯单体泄怒技，与目标数无关 |
| 元素萨满 | 闪电箭 Lightning Bolt | 188196 | 纯单体填充，不受爆发窗口影响 |
| 武器战 | 自动攻击 Melee | 1 | 唯一纯武器伤害来源，永远单体 |

两个口径必须**分开用**（这是实测踩过的坑）：

- `k_nc`（非暴击每发比）→ 用于比较**"每发伤害"类指标**
- `k_all`（含暴击每发比）→ 用于归一**总伤 / DPS**

**方法自检（强制）**：拿 8–10 个同伤害类型的技能，各自算非暴击每发比值，看是否**聚集在 k 附近**。实测武器战 10 技能落在 1.44–1.65（均值 1.55，白字 1.53 正中），标尺成立；唯一离群项（重伤 2.05）单独解释。**如果离散度很大，说明基准不成立，必须换技能或放弃归一化并如实说明。**

**收敛性验证**：若能拿到两个以上高水平样本，归一后应当收敛（实测两个好手归一 DPS 3.49 / 3.60，而原始层数差 7 层、原始 DPS 差 9%）。不收敛 = 归一化无效。

### Phase 4 · 施法序列与爆发窗口

**必须直连 events API 重拉**，不能用 DB 的 event 表。用本 skill 附带的脚本：

```bash
python3 .agents/skills/wcl-player-review/scripts/wcl_events.py \
    --code <CODE> --start <fight.start_time> --end <fight.end_time> \
    --source-id <friendlies.id> --out data/cache/<tag>/<role>_events.json
```

脚本已内建全部已知陷阱（见 `references/pitfalls.md`）：
带 `sourceid` 时 `type`/`abilityid` 过滤失效 → 只请求一次后**本地过滤**；`crit` 字段不存在 → 用 `hitType`（1 命中 / 2 暴击）；`nextPageTimestamp` 分页 + 退避重试。

**爆发/平稳期切分锚点**（按专精选，写在报告里说明）：

- 元素萨满：每次「升腾」后 15s 为爆发窗口；另查升腾前 5s 是否预铺「风暴守护者」
- 噬灭 DH：以「坍缩之星」为锚 —— 坍缩星 → 大灭(proc) → Devour ×3~4 为爆发；虚空射线（攒资源）→ Devour（泄怒）为平稳
- 通用做法：把同一 `ability_id` 且在 **1.0s 内**的连续事件折叠为一次"激活"，用激活序列近似按键序列

**分析的指标**（完整清单见 `references/methodology.md`）：
主技能占比、**生成:泄怒比**（资源循环类专精的核心）、低价值技能:主技能比、爆发次数/分钟、爆发窗口内大技能密度、CD 强化去向、药水次数与时机、死亡、打断、APM/活跃时间。

### Phase 5 · 环境混淆排除（**这一步决定了结论对不对**）

用户要的是"他到底菜不菜"，所以必须逐项排除非个人因素：

| 检查项 | 方法 | 判定 |
|---|---|---|
| 活跃时间占比 | `damage_total / dps` ÷ 战斗时长 | <80% 说明大量时间没输出 |
| 长断档 | 施法间隔分布：`>6s` / `>15s` 的次数与总时长 | **和队友的断档时间点对比**；若几乎重合（实测 218/212、425/425、942/942s）→ **队伍级**，不是个人发呆 |
| 目标数差异 | 伤害事件数 ÷ 施放次数 = "每发命中几个目标" | 差异归因于拉怪规模/层数 |
| 消耗品 | `tables/summary` 的 `combatantInfo` auras + `player.potion_use` | 缺合剂/食物/符文/药水 = **个人可改**，直接进 P0 |
| 装备硬差距 | combatantInfo 的 ilvl / 武器 / 属性 rating / 套装 | 客观因素，量化后从残差里剔除 |
| 天赋差异 | combatantInfo 的 talentTree 节点对比 | 节点基本一致 → 排除 build 变量 |

**残差要做乘性分解**并回验，例如实测：

```
原始差 2.338× → 拉平后 1.427×
1.427× = 每输出GCD归一产出 1.287×  ×  输出GCD频率 1.108×
1.286 × 1.110 = 1.427 ✓
```

### Phase 6 · 治疗分支

若对象是治疗，**换用另一套评判维度**（详见 **`references/healing-review.md`**），不要套 DPS 的指标：

1. **基础治疗手法** = 治疗构成占比 + 施法次数 + 过量率 + **资源流转（生成 → 泄能转化率）**
2. **救急能力** = 救急/自保技能次数 + 过量率 + 是否对应死亡事件
3. **可预见 AOE / 大额点名应对** = 大招 CD 利用率（实际次数 ÷ 理论次数）+ 敌我时间轴交叉
4. **职业特色发挥** = 英雄天赋核心按钮是否卡 CD + 双轴（治疗/输出）是否都转

治疗数据的获取方式与伤害不同（`healing` 端点要 `start`+`end`+`sourceid`+`by=ability`；过量率算法；时间戳归一化），**动手前先读 `references/healing-review.md`**。

### Phase 7 · 报告与 PDF

报告结构见 **`references/report-template.md`**。要点：

- 命名 `{专精}_{角色名}_{主题}_{副本中文名}+{层数}.md`，存 `data/reports/`
- 头部元信息表 + 结论摘要表；改进清单固定 **P0 / P1 / P2**，每条挂数字依据
- 表格数字右对齐，单位统一（万 / M / min / 次/分钟）
- 附录写方法局限

```bash
node scripts/md2pdf.js "data/reports/xxx.md" "data/reports/xxx.pdf" references/pdf-chrome-print.css
pdfinfo "data/reports/xxx.pdf" | head -15      # 验证页数
pdftotext "data/reports/xxx.pdf" - | head -60  # 验证文本层
```

**不要依赖截图目视校验**——部分模型不支持图片输入，会浪费一轮。

---

## 交付前自检清单

- [ ] 报告里出现的**每个技能名**都确认过属于当前英雄天赋 + 版本
- [ ] 所有对比都标了层数；跨层比较处**显式声明不可直接比**
- [ ] 每个"需要改进"都挂了数字；每个数字都能在数据里复现
- [ ] 区分了客观因素 vs 个人可改，并给了百分比拆解
- [ ] 长断档等环境指标已和队友交叉验证
- [ ] 通篇无讽刺/情绪化措辞
- [ ] 附录写了方法局限
- [ ] `.md` 与 `.pdf` 都已生成并验证

---

## 资源

| 文件 | 内容 |
|---|---|
| `references/methodology.md` | 基准选型与两种归一化公式、指标全清单、爆发窗口切分 |
| `references/healing-review.md` | 治疗四维度量化方法、资源流转、过量率、时间轴交叉 |
| `references/pitfalls.md` | WCL V1 API + 分析的实测陷阱清单（含复现命令） |
| `references/report-template.md` | DPS / 治疗两套报告骨架与写法规范 |
| `references/persona-logomancer.md` | 项目既定报告人格「松子」（冷静克制、数据即标准）——与"中性措辞"铁律一致，可选用 |
| `scripts/wcl_events.py` | 正确的 events 抓取器（内建过滤/分页/暴击/退避处理） |

> **已验证**：`scripts/wcl_events.py` 在 `RXCBtHF4yD37qK1w` fight 5 / source 2（奶骑）上复现了历史会话的全部关键数字——神圣震击 208、圣光闪现 181、正义盾击 148、审判 120、荣耀圣令 108、神圣军备 25+24、清洁术 18，且暴击率非零（证明 `hitType` 口径正确）。运行约 1 分钟。

**不要偏离到这些路径**：项目里已有的 `core/m2_standalone_summary.py`（固定 M2 模板、偏团队伤害向、输出文件名固定会互相覆盖）、`core/report_skeleton.py`（10 个占位符的 M2 骨架）、`core/fetch_top_benchmarks.py`（只发现 +18~+20 顶层选手，服务不了非顶层层数对标）——**都不适用于单人单次深挖**。它们可以帮你做首轮速览，但不要用它们的结果直接下结论。
