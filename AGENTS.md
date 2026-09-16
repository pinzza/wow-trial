# AGENTS.md

本文件是本仓库**唯一**的 Agent 指令事实源（single source of truth）。任何 AI 编码代理——DeepSeek Harness (DSH)、Claude Code、Codex 或其他 AGENTS.md 兼容工具——在修改本仓库前都应先读本文件。

> 历史沿革：本项目先后使用过 Hermes 与 Claude Code，2026-09-10 起以 **DSH** 为主。迁移时已彻底移除 superpowers 相关产物（`.claude/skills/`、`.claude/agents/`、`.hermes/`），`docs/superpowers/` 中仍有价值的文档已迁到 `docs/plans/` 与 `docs/design/`。
> `CLAUDE.md` 只是指向本文件的薄兼容入口，不承载项目知识。

---

## 项目概述

魔兽世界 Warcraft Logs (WCL) 战斗日志数据分析项目。核心业务是**读 WCL 报告 → 量化对比 → 产出中文教练报告（Markdown + PDF）**。

七条数据路径：

- **V1 API 管道** (`core/v1_pipeline.py`): 通过 WCL V1 API 的 table 端点获取汇总数据，写入 7 表 SQLite。**主要生产工具。**
- **通用管线** (`core/mplus_pipeline.py`): `--profile <档案>` 个人教练模式 / `--mode team` 团队分析模式，档案驱动（YAML）。
- **自动对标** (`core/fetch_top_benchmarks.py`): 从 WCL rankings API 自动发现同副本同专精顶级选手，拉取数据并生成 1v1 对比 JSON。
- **比较引擎** (`core/comparison_engine.py`): 读取两份 SQLite，逐维度对比计算，输出 8 节结构化 JSON。
- **独立分析** (`core/m2_standalone_summary.py`): 单份 SQLite → 结构化分析摘要（技能构成/活跃度/死亡/路线/Buff）。
- **报告骨架** (`core/report_skeleton.py`): 读取 benchmarks + m2 摘要 → 预填充 Markdown 骨架，含 10 个占位符供 AI 填充。
- **V2 GraphQL API** (`wcl_parser/`): OAuth 认证，获取全量结构化数据。**功能完成但 V1 API 更高效，当前优先使用 V1。**
- **HTML 抓取** (`_archive/wcl_fetcher.py`): cloudscraper + Playwright，解析页面 DOM。**已归档，仅用于快速预览。**

---

## 运行环境（2026-09-10 实测）

| 项 | 事实 | 结论 |
|---|---|---|
| 系统 python | `/usr/bin/python3` = **3.12.3**，requests 2.31.0 + pydantic 2.13.3 + sqlite3 齐全 | ✅ **一律用 `python3`** |
| 项目 venv | `venv/bin/python` = 3.11.15，**缺 pydantic** | ❌ 不要用它跑 `core/` 管线 |
| Node | v22.22.2，`node_modules/` 已有 `marked` 18 + `puppeteer-core` 24 | ✅ PDF 可直接出 |
| Chrome | `/usr/bin/google-chrome-stable`（HeadlessChrome/148）存在 | ✅ |
| pytest | 9.0.3，`tests/` 下 11 个测试文件 | ✅ |

**所有 `core/` 命令都必须带 `PYTHONPATH=.`**，否则 `from core.xxx import` 失败。

> 历史坑：曾有一次"以为缺 requests"而 `pip install --target tmp/wcl_deps`，实际装成 win_amd64 wheel 且系统本来就有 requests。**不要再往 `tmp/` 里装依赖。**

---

## 关键架构

```
core/                           # 核心管道与工具（当前主力）
├── mplus_pipeline.py            # 入口：--profile → 个人教练 | --mode team → 团队分析
├── profile_loader.py            # YAML 档案加载 + 校验（Profile dataclass）
├── pipeline_strategies.py       # CoachingStrategy + ROLE_CONFIGS（三角色差异配置驱动）
├── report_builder.py            # 统一报告构建器（profile.role + profile.persona 驱动）
│   ├── V1Client                # API 请求封装 (限速 + 重试)
│   ├── fetch_fights()          # 报告元数据、玩家、NPC、dungeonPulls
│   ├── fetch_table()           # 9 个 table 端点，含 by=ability 逐玩家增强
│   ├── parse_class_spec()      # 从 icon/combatantInfo 解析职业专精
│   ├── SPEC_MAP                 # specID → (Class, Spec) 映射 (12.0 Midnight)
│   ├── --fight-id              # 可选：仅处理指定 fight，过滤 table 时间窗口
│   └── 幂等写入                 # DELETE + INSERT 模式，重复运行不翻倍
│
├── v1_pipeline.py              # 单报告 → 7 表 SQLite（最小可用单元，最常被复用）
├── events_pipeline.py          # 事件层抓取
├── fetch_top_benchmarks.py     # 自动对标：rankings API → 顶级选手 → v1_pipeline → 1v1 JSON
│   ├── fetch_rankings() / find_top_per_spec() / extract_comparison()
│   └── 匿名顺延                 # 跳过匿名选手，次选非匿名
│
├── comparison_engine.py        # 读两份 SQLite → 8 节 JSON（8 个 compute_* 独立计算）
├── m2_standalone_summary.py    # 单份 DB → 3 组分析摘要文本
│   ├── build_group_a()         # 伤害构成 + 施法活跃度 + 冷却爆发
│   ├── build_group_b()         # 死亡分析 + 路线时间轴 + 打断统计
│   ├── build_group_c()         # Buff覆盖 + 资源流转
│   ├── build_meta()            # 报告元数据 (层数/限时/SX/波次方差)
│   ├── detect_sx()             # WCL events API 检测嗜血/英勇次数
│   └── compute_wave_variance() # 小怪波次用时方差分析
│
├── report_skeleton.py          # M2 报告骨架预生成（10 个占位符）
├── build_analysis_summaries.py # comparison JSON → 3 组分析就绪摘要
├── spell_cn_map.py             # spell_id → 国服简体中文名解析
├── schema.py / writer.py       # 7 表 DDL + SQLite 写入器（复制自 wcl_parser/storage/）
│
├── xiaoxue_pipeline.py         # X 系列（冰法·小雪）三件套
├── xiaoxue_report_builder.py
├── xiaoxue_tracker.py
└── meishu_pipeline.py / meishu_report_builder.py   # M 系列（梅叔）

.agents/skills/                 # DSH 项目级 skills（DSH 自动发现，见「Skills 布局」）
scripts/                        # md2pdf.js / safe_content_filter.py / 转写与 Wiki 工具
wcl_parser/                     # V2 GraphQL API 模块 (备用)
tests/                          # pytest 回归（含 CLI 正交化、档案、报告构建器）
data/                           # 数据与产物（大体积，已 gitignore）
├── wcl_db/                     # 每报告一个 .db（7 表 SQLite）
├── cache/                      # 分析中间产物（m2_*.txt、benchmarks、事件快照）
├── mappings/                   # 副本名等小型映射（随仓库提交）
├── profiles/                   # 个人教练 YAML 档案（随仓库提交）
└── reports/                    # 最终报告输出目录（.md + .pdf）
```

**数据流（完整链）**:
```
V1Client(table endpoints)
  → core/v1_pipeline.py → data/wcl_db/{code}.db (7 tables)
  → core/m2_standalone_summary.py → data/cache/m2_{meta,group_a/b/c}.txt

V1Client(rankings API) + v1_pipeline (subprocess)
  → core/fetch_top_benchmarks.py → data/cache/per_spec_benchmarks.json

m2 txt + per_spec_benchmarks.json
  → core/report_skeleton.py → data/cache/m2_skeleton.md (10 占位符)
  → AI 填充占位符 → 最终 Markdown 报告
  → scripts/md2pdf.js → PDF

comparison_engine.py (两份 DB) → JSON
  → core/build_analysis_summaries.py → 3 组摘要文本 (供子 Agent 消费)
```

---

## 核心工具使用

```bash
# 0. 个人教练模式（推荐，使用档案）
PYTHONPATH=. python3 core/mplus_pipeline.py --profile dongrou --report-code <CODE> --fight-id <N>
PYTHONPATH=. python3 core/mplus_pipeline.py --profile taozi   --report-code <CODE> --fight-id <N>
PYTHONPATH=. python3 core/mplus_pipeline.py --profile meishu  --report-code <CODE> --fight-id <N>

# 1. 团队分析模式（独立入口）
PYTHONPATH=. python3 core/mplus_pipeline.py --mode team --report-code <CODE> --fight-id <N>

# 1b. 最小单元：单报告 → 7 表 SQLite（其它分析的前置）
PYTHONPATH=. python3 core/v1_pipeline.py <CODE> --fight-id <N> --db-dir data/wcl_db
#   --fight-id 仅处理指定 fight，并过滤 table 时间窗口；不传则整份报告聚合
#   --api-key 缺省时读 WCL_API_KEY 环境变量；--db-dir 默认 data/wcl_db

# 2. 自动对标 (发现顶级选手 + 拉取 + 对比)
PYTHONPATH=. python3 core/fetch_top_benchmarks.py <our.db> <our_code>
#   选项: --output data/cache/per_spec_benchmarks.json / --db-dir / --dry-run

# 3. 独立分析摘要 (单份 DB) —— ⚠️ 输出文件名固定，跨报告会互相覆盖
PYTHONPATH=. python3 core/m2_standalone_summary.py <db_path> <report_code>

# 4. 报告骨架预生成
PYTHONPATH=. python3 core/report_skeleton.py <report_code>

# 5. 比较引擎 (两份 DB → 8 节 JSON)
PYTHONPATH=. python3 core/comparison_engine.py \
  --our-db <ours.db> --our-code <our_code> \
  --top-db <top.db> --top-code <top_code> --output result.json

# 6. 分析摘要拆分 (comparison JSON → 3 组文本)
PYTHONPATH=. python3 core/build_analysis_summaries.py comparison_result.json

# 7. 回归测试 / 单模块自测
PYTHONPATH=. python3 -m pytest tests/ -q
PYTHONPATH=. python3 core/schema.py && PYTHONPATH=. python3 wcl_parser/storage/schema.py
```

长任务（一次 `v1_pipeline` 约 60 次 API 请求，1–3 分钟）请用**后台任务**方式跑，再收结果。

---

## 数据库模式

7 表，每报告一个 `.db` 文件存放于 `data/wcl_db/`。`core/v1_pipeline.py` 直接 SQL 写入（非 Pydantic 模型），幂等设计（先 DELETE 后 INSERT）。

| 表 | 主键 | 说明 | 数据来源 (V1 API) |
|---|---|---|---|
| report | report_code | 报告元数据 (title/zone/owner/keystone_timed/dungeon_name) | `/report/fights/` |
| fight | (report_code, fight_id) | 战斗摘要 (kill/start_time/end_time/keystone_level) | `dungeonPulls` |
| player | auto_id | 玩家统计 (class/spec/ilvl/DPS/total_casts) | `damage-done` + `healing` |
| ability | auto_id | 技能 (damage_amount + cast_count via hits) | `damage-done.abilities` + `casts.abilities` |
| aura | auto_id | Buff 覆盖率 (队伍级别，所有玩家相同) | `buffs.auras` |
| event | auto_id | 战斗事件 (仅 death + interrupt 两种类型) | `summary.deathEvents` + `interrupts` |
| npc | auto_id | NPC 实体 (全部 fight_id=1，非按战斗分组) | `enemies` |

**关键限制**（V1 API table 端点局限）：
- **event 表只有 death 和 interrupt 事件** — 无 cast/damage/resource 事件
- **aura 是队伍级别** — 所有玩家共享相同的 buff 列表
- **player/npc 是聚合数据** — 全部 fight_id=1，不按战斗分组
- **DB 里没有**：`activeTime`、`combatantInfo`（装备/属性 rating/天赋树/开场 buff）、逐次事件的 `hitType`
- `player.parse_pct` 列复用为存储 `total_casts`（总施法次数）
- `ability.hits` 存储施法次数（从 casts 端点合并）
- `report` 表含 `dungeon_name` 列（v1_pipeline 自动写入，旧 DB 自动补列）

需要前述缺失字段时，**必须直连 V1 API 补数**，不要试图从 7 表反推。

### by=ability 逐玩家增强

`v1_pipeline.py` 默认对每个玩家分别调用 `tables/damage-done/?sourceid={id}&by=ability` 和 `tables/casts/?sourceid={id}&by=ability`，突破全局 top 5 截断限制。若逐玩家查询失败则自动回退原始数据。
`fetch_top_benchmarks.py` 的 `_cache_is_valid()` 以"任意玩家 >12 技能"判断增强是否生效。

### 跨语言技能名解析

`core/spell_cn_map.py`：以 `spell_id` 为主键，不做客户端语言假设；150+ 硬编码映射 + `_extract_from_dbs()` 自动提取；`resolve(spell_id, fallback)` 优先级 = 硬编码 > DB 提取 > fallback。
**任何技能对比都必须按 spell_id/guid 匹配，禁止按名字匹配**（英文客户端 `Lava Burst` vs 中文 `熔岩爆裂`；同一技能还常有多个 spell_id）。

---

## V1 API 信息与已知陷阱

- **Base URL**: `https://www.warcraftlogs.com/v1`
- **API Key**: 经 `WCL_API_KEY` 环境变量提供（`core/config.py:get_api_key` 统一入口），公开仓库不内置任何可用 Key
- **常用端点**: `report/fights/{code}`、`report/tables/{summary,damage-done,healing,casts,buffs,deaths,interrupts}/{code}`、`report/events/{code}`、`rankings/encounter/{id}`、`rankings/character/{name}/{server}/{region}?zone=55`、`zones`
- **失败端点（已知）**: `tables/resources/` 空响应或 400；`tables/auras/` HTTP 400
- **限速**: 内建指数退避重试（3 次）；大量抓取时页间 `sleep(0.15~0.2)`，429/5xx 用 `sleep(2**attempt)`

### events 端点实测陷阱（2026-09-10 验证，写 skill 时反复踩过）

1. **带 `sourceid` 时 `type` / `abilityid` 过滤会被忽略** —— 请求 `type=cast`、`type=damage`、指定 6 个技能，三次返回**完全相同**的全部事件（如 33,208 条）。正确做法：**只请求一次**，拿回后在本地按 `sourceID` / `guid` / `type` 过滤。
2. **`sourceid` 过滤本身不彻底** —— 首页仍会混入其他 actor/宠物，必须本地精确过滤。
3. **V1 events 不返回 `crit` 字段** —— 暴击必须用 `hitType`（`1`=命中，`2`=暴击）。漏看这条会让暴击率恒为 0，直接毁掉整个基准归一化。
4. **分页**用 `nextPageTimestamp` 循环，配合 guard（50–80 页）兜底，单页上限 1 万条。
5. **`report/events` 的 `filter='type="cast"'` 语法有效**，但 `type="cast" and source.id=X` 返回 0 条。
6. **时间戳语义不一致**：同一张 `event` 表里，death 事件的 timestamp 是**战斗内相对毫秒**，而 CD cast 事件是**报告内相对毫秒**。跨两者比较前必须先减 `fight.start_time` 归一化。
7. **`event` 表的 `type='cast'` 行不是按键次数**：`v1_pipeline` 把 events 端点返回的所有事件都hardcode 成 `cast`，其中混有 damage/heal/applybuff 的 tick（实测某技能 3521 次"cast"其实是 DoT 跳动）。**施法次数只信 `tables/casts` 端点**；event 流仅用于取时间点。
8. **`tables/healing` 需要 `start`+`end`+`sourceid`+`by=ability`**，缺任一参数会静默返回 0 条。
9. **过量治疗** = `overheal/(total+overheal)`；必须过滤 `total <= 0` 的负行（存在如 `战火淬炼 Damage = -4,675,039` 的污染行）。
10. **`player.hero_talent` 列为空** —— 无法从 DB 判定英雄天赋，必须靠标志性技能签名或 `tables/summary` 的 `combatantInfo`。
11. **URL 的 `source=` ≠ DB 的 `player.id`** —— 一律用玩家名或 class/spec 定位；events 端点用的 `sourceID` 对应 `/report/fights` 里 `friendlies[].id`。
12. **ranks/percentile 仅供参考** —— 实测同一角色 rank 与 percentile 语义可能自相矛盾，不能作为水平判据，引用时加免责说明。

---

## 报告产出与交付约定

**命名规范**：`{专精}_{角色名}_{主题}_{副本中文名}+{层数}.md`（例：`武器战_开冲开冲_毒牙祭坛+9_输出水平诊断.md`），PDF 同名。

**报告固定形式**：
- 头部元信息表：评估对象 / 参照对象 / 层数 / 数据来源 / 生成日期
- 表格数字右对齐（`|---|---:|`）；单位统一（万 / M / min / 次/分钟）
- 改进清单固定 **P0（立刻改）/ P1（本周内）/ P2（持续提升）**，**每条必须挂数字依据**
- 结论必须区分 **客观因素（层数/装等/队伍拉怪）vs 个人可改**，给百分比拆解与"合理上限"估数
- 附录写**方法局限**（样本量、端点缺失、口径假设）
- **全程中性措辞**：对就是对、错就是错，**禁止讽刺、禁止情绪化形容词**

**PDF 转换**（Markdown → 浏览器级渲染 PDF）：
```bash
node scripts/md2pdf.js data/reports/报告.md 输出.pdf references/pdf-chrome-print.css
```
流水线 `marked(解析) → puppeteer(Chrome headless) → page.pdf`，脚本 `scripts/md2pdf.js`，CSS `references/pdf-chrome-print.css`。
验证用 `pdfinfo` 看页数 / `pdftotext - | head` 看文本层；**不要依赖截图目视**（部分模型不支持图片输入）。
备选：`pandoc + weasyprint`（表格对齐略弱）、`pandoc + xelatex`（emoji 丢失，安装量 ~800MB）。

---

## Skills 布局（DSH）

DSH 文件系统 skill provider 的扫描优先级：

| 优先级 | 目录 | 作用域 |
|---|---|---|
| 100 | `<project>/.dsh/skills` | 项目 |
| 200 | `<project>/.agents/skills` | 项目（推荐公共目录） |
| 400 | `~/.dsh/skills` | 用户全局 |
| 500 | `~/.agents/skills` | 用户全局（推荐通用目录） |

- **DSH 不扫描 `.claude/skills`。** 项目专属 skill 一律放 `.agents/skills/<name>/SKILL.md`，frontmatter 必须有 `name` 与 `description`。
- 跨项目复用的通用 skill 放 `~/.agents/skills/`，不要提交进本仓库。
- 不要为了兼容而在仓库里同时维护 `.agents/skills` 与 `.claude/skills` 两份副本。

当前项目 skills：

| Skill | 用途 |
|---|---|
| `wcl-player-review` | **通用**：给定"待分析记录 + 对标记录"，量化评估某玩家的**输出水平或治疗水平**，产出 md+pdf 报告 |
| `mplus-t-coach` | T 系列单人教练（桃子鹤僧 / 织雾武僧），孙青云教材 + 绿绿月光基准 |

---

## 多 Agent 协作

- DSH 内委派用 **subagent / subagent_fork / workflow** 工具，不要再用 Hermes 时代的 ACP 委托。
- 独立的长任务（多次 API 抓取、批量报告）并行起后台 job，用 `job_output` 收集，不要忙轮询。
- 给子代理的提示必须**自包含**：它看不到主会话上下文，需显式给出文件路径、命令、期望输出格式。
- 子代理默认只读；需要写盘时在提示里明确要求，并指定输出路径。

**Claude Code 共存**：仓库保留薄 `CLAUDE.md` 作为兼容入口。若某位开发者的 CC 版本不识别 `.agents/skills`，请其**在本机**创建 `.claude/skills` 适配器（已被 gitignore），**不要提交**。

---

## 安全内容过滤

`scripts/safe_content_filter.py` 防止 DeepSeek API "Content Exists Risk" 400 错误：
- 零宽字符 (ZWJ/ZWNJ/BOM) → 删除
- 变体选择符 (VS16) → 删除
- Emoji → ASCII 安全文本替代 (如 ✅→[OK], 🛡️→[T])
- Unicode 破折号 → ASCII (如 —→--)
- Greek 字母 → Latin/Chinese (如 σ→标准差)
- 递归过滤 `safe_dict_filter()` 处理 dict/list 中所有字符串值

所有输出到 DeepSeek API 的文本都应经过此过滤器。

---

## 注意事项

- `player.parse_pct` 列语义已变更为 `total_casts`（总施法次数），非解析百分比
- `SPEC_MAP` 当前标记为 12.0 Midnight
- `event` 表的 `timestamp` 列是相对报告开始的毫秒偏移（非绝对时间戳）；`fight` 表的 `start_time`/`end_time` 同样是相对偏移
- 中文编码: WCL 中文站玩家名和技能名为中文字符；跨语言匹配通过 `spell_cn_map` 解决
- `requests` 库为运行时依赖（排名 API、SX 检测等需要网络请求）
- subprocess 调用 `v1_pipeline.py` 时需确保 `PYTHONPATH=.`，并透传 `WCL_API_KEY`
- 命令行里的中文 / 生僻字路径（`丨`、`丶`）**必须加引号**
- 中间产物不要写 `/tmp`：**每次 bash 调用是独立 shell，`/tmp` 不持久**。落盘请用 `data/cache/` 或 `tmp/`（后者已 gitignore，仅作临时区）
