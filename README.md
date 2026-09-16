# wow-trial — WCL 战斗日志 ETL 与自动化教练报告

> 魔兽世界 Warcraft Logs (WCL) 非官方数据管线：读 WCL 报告 → 7 表 SQLite → 量化对标 → 中文教练报告（Markdown + PDF）。
> For educational use. Data via the official WCL API; please comply with the [WCL ToS](https://www.warcraftlogs.com/terms).

## 为什么做这个

手动复盘一份大秘境日志要 1–2 小时，且结论多凭感觉。本项目把流程自动化：

```
WCL V1 API (table 端点)
  → core/v1_pipeline.py      → data/wcl_db/{code}.db (SQLite)
  → core/m2_standalone_summary.py → data/cache/m2_{meta,group_a,b,c}.txt
  → core/fetch_top_benchmarks.py  → data/cache/per_spec_benchmarks.json (rankings 自动对标)
  → core/report_skeleton.py  → Markdown 骨架（含 10 个待填占位符）
  → AI 填充 + scripts/md2pdf.js → 教练报告 PDF
```

两份 DB 的横向对比另有 `core/comparison_engine.py`（8 节结构化 JSON）→ `core/build_analysis_summaries.py`。

## 架构

```
core/
├── config.py               # 统一配置：WCL_API_KEY 环境变量唯一入口（不内置 Key）
├── v1_pipeline.py          # 单报告 → SQLite（最小可用单元，~60 次 API 请求）
├── mplus_pipeline.py       # 入口：--profile 个人教练 / --mode team 团队分析
├── profile_loader.py       # YAML 档案加载 + 校验
├── pipeline_strategies.py  # CoachingStrategy + ROLE_CONFIGS（三角色配置驱动）
├── events_pipeline.py      # 事件层抓取（施法/伤害时间轴）
├── fetch_top_benchmarks.py # rankings 自动发现同专精顶级选手 → 1v1 JSON
├── comparison_engine.py    # 两份 DB → 8 节对比 JSON
├── m2_standalone_summary.py# 单份 DB → 技能构成/死亡/路线/Buff 摘要
├── report_skeleton.py      # 报告骨架预生成
├── spell_cn_map.py         # spell_id → 国服中文名（按 id 匹配，不按名字）
└── schema.py / writer.py   # SQLite DDL + 写入器
wcl_parser/                 # V2 GraphQL 备用模块（OAuth；当前主力是 V1）
scripts/md2pdf.js           # Markdown → PDF（marked + puppeteer）
tests/                      # pytest（离线可跑；联网集成测试需 WCL_API_KEY）
data/
├── mappings/               # 副本名映射（随仓）
├── templates/              # 报告模板（随仓）
├── profiles/example.yaml   # 虚构示例档案（真人档案只放本地，不进仓）
└── samples/                # 合成示例数据构建脚本（无真人信息）
```

数据模型：每份报告一个 `.db`，`report / fight / player / ability / aura / event / npc` 等表，
幂等写入（`DELETE + INSERT`，重复运行不翻倍）。技能对比一律按 `spell_id` 匹配，
不按名字（英文客户端 `Lava Burst` vs 中文 `熔岩爆裂`，同一技能还常有多个 id）。

## 快速开始

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 填入你的 WCL V1 Key（https://www.warcraftlogs.com/api/clients）
export WCL_API_KEY=<your-key>

# 最小单元：单报告 → SQLite
PYTHONPATH=. python3 core/v1_pipeline.py <REPORT_CODE> --fight-id <N> --db-dir data/wcl_db

# 个人教练（档案驱动，见 data/profiles/example.yaml）
PYTHONPATH=. python3 core/mplus_pipeline.py --profile example --report-code <CODE> --fight-id <N>

# 离线测试（无需 Key）
PYTHONPATH=. python3 -m pytest tests/ -q
```

无 Key 时联网集成测试会自动 skip，只有纯离线单测会运行。

## 实测 API 陷阱（本项目最有价值的部分）

V1 API 文档没写、实测踩出来的 12 条（详见 `AGENTS.md`），摘 3 条：

1. `report/events` 带 `sourceid` 时 `type`/`abilityid` 过滤会被**忽略**——只请求一次，本地按 `sourceID/guid/type` 过滤。
2. V1 events 不返回 `crit` 字段——暴击看 `hitType`（1=命中，2=暴击），否则暴击率恒为 0。
3. `event` 表 `type='cast'` 行混有 DoT tick——**施法次数只信 `tables/casts`**，event 流只取时间点。

## 方法局限

- V1 table 端点无逐次 cast/damage/resource 事件；`aura` 是队伍级别；`player/npc` 为聚合数据。
- `rank`/`percentile` 仅供参考（实测存在语义矛盾），报告中需加免责说明。
- 对标榜样存在选择偏差（层数/队伍拉怪/装等差异），结论区分“客观因素 vs 个人可改”。

## 命名对照（历史原因，拼音模块保留）

| 模块/档案 | 含义 |
|---|---|
| `xiaoxue_*` / profile `example(dps·冰法)` | 冰法 DPS 教练管线 |
| `meishu_*` / profile `example(tank·酒仙)` | 酒仙坦克教练管线 |
| `taozhi` / profile `example(healer·织雾)` | 织雾治疗教练管线 |
| `mplus_pipeline.py --mode team` | 全队混合分析 |

## 报告示例

本地跑通后在 `data/reports/` 看输出（不进仓）。PDF 经 `node scripts/md2pdf.js 报告.md 输出.pdf` 生成。

## License

MIT，见 `LICENSE`。
