# 大秘境分析模块 (M1) 功能介绍

## 模块目标

对《魔兽世界：至暗之夜》(12.0) 大秘境战斗日志做**结构化数据提取 → 多维度对比 → 自然语言分析报告输出**。

用户提供 WCL 报告码 → 自动入库、寻找顶层对比队伍、产生 8 维对比 JSON → 3 路并行 AI 子代理生成最终中文分析报告。

---

## 工作流（完整链路）

```
┌──────────────────┐
│ 用户输入报告码    │
└────────┬─────────┘
         ▼
┌──────────────────┐   WCL V1 API (12 次请求)
│ v1_pipeline.py   │──▶ fights 端点 + 9 个 table 端点
│ --fight-id 过滤  │──▶ 聚合 → 7 表 SQLite
└────────┬─────────┘
         ▼
┌──────────────────┐   raider.io API / WCL 反查
│ 寻找顶层对比报告  │──▶ 同名专精 ≥3/5 匹配 → 提取 code
└────────┬─────────┘
         ▼
┌──────────────────┐   同上 → 顶层 SQLite
│ v1_pipeline.py   │
└────────┬─────────┘
         ▼
┌──────────────────┐
│ comparison_engine│──▶ 双 DB → 8 节结构化 JSON (~112KB)
│ .py              │
└────────┬─────────┘
         ▼
┌──────────────────┐
│ build_analysis_  │──▶ JSON → 3 组紧凑摘要 (~5KB 总计)
│ summaries.py     │     A:伤害+施法+冷却  B:死亡+路线+打断  C:Buff+资源
└────────┬─────────┘
         ▼
┌──────────────────┐
│ delegate_task    │──▶ 3 个子 Agent 并行, 每组 ~1.7KB context
│ (3 路并行)       │──▶ 各自产出分析文本
└────────┬─────────┘
         ▼
┌──────────────────┐
│ 主 Agent 聚合    │──▶ 结构化中文报告
│                  │     5 对/5 错 + MVP/战犯 + 个人提升 + 下 CD 清单
└──────────────────┘
```

---

## 核心组件清单

### 1. Python 脚本

| 脚本 | 位置 | 功能 |
|------|------|------|
| `v1_pipeline.py` | `/home/code/wow-trial/v1_pipeline.py` | WCL V1 API → SQLite 入库 (7 表), 支持 --fight-id 过滤 |
| `comparison_engine.py` | `/home/code/wow-trial/comparison_engine.py` | 双 DB 对比 → 8 节 JSON, 同名专精配对算法 |
| `build_analysis_summaries.py` | `/home/code/wow-trial/build_analysis_summaries.py` | JSON → 3 组紧凑文本摘要, spell_id 桥接中英文 |

### 2. 依赖模块

| 模块 | 位置 | 功能 |
|------|------|------|
| `wcl_parser/storage/writer.py` | `/home/code/wow-trial/wcl_parser/storage/writer.py` | SQLite 写入器（创建 DB、建表） |
| `wcl_parser/storage/schema.py` | `/home/code/wow-trial/wcl_parser/storage/schema.py` | 7 表 DDL 定义 |

### 3. Hermes Skills

| Skill | 位置 | 功能 |
|-------|------|------|
| `mplus-analysis` | `~/.hermes/profiles/wow/skills/gaming/mplus-analysis/` | 分析方法论：API 调用规范、7 维对比框架、报告模板 |
| `mplus-benchmark` | `~/.hermes/profiles/wow/skills/mplus-benchmark/` | 流水线调度器：5 步全链路编排、摘要压缩策略、并行分析聚合 |
| `wow-lookup` | `~/.hermes/profiles/wow/skills/wow-lookup/` | 角色查询：raider.io API 调用规范（M+ 分数、最佳记录、当前词缀） |

### 4. 外部 API

| API | Base URL | 认证方式 | 用途 |
|-----|----------|---------|------|
| WCL V1 API | `https://www.warcraftlogs.com/v1` | `?api_key=` query param | 报告元数据、table 汇总、排名查询 |
| raider.io API | `https://raider.io/api/v1` | 无需认证 | 角色查询、M+ 排行、词缀查询 |
| WCL V2 GraphQL (备用) | `https://cn.warcraftlogs.com/api/v2/client` | OAuth (client_id + client_secret) | 事件流查询（含时间戳的 cast/damage/resource 事件） |

### 5. 凭据

| 凭据 | 存储位置 | 说明 |
|------|---------|------|
| WCL_V1_API_KEY | `v1_pipeline.py` 默认值 | `<YOUR_WCL_V1_KEY>` |
| WCL_V2_CLIENT_ID / SECRET | 环境变量 (未设定) | OAuth 凭证，V2 模块等待配置 |

### 6. 数据存储

| 位置 | 内容 |
|------|------|
| `/home/code/wow-trial/data/wcl_db/{code}.db` | 每报告一个 SQLite 文件 |
| `/home/code/wow-trial/data/cache/group_{a,b,c}_summary.txt` | 3 组分析摘要 |
| `/home/code/wow-trial/comparison_{code}_v3.json` | 8 节结构化对比 JSON |
| `/home/code/wow-trial/_archive/` | 过期/废弃数据 |

---

## SQLite Schema (7 表)

| 表 | 主键 | 说明 | 数据来源 |
|---|------|------|---------|
| report | report_code | 报告元数据 (title/zone/owner) | `/report/fights/` |
| fight | (report_code, fight_id) | 战斗摘要 (kill/start_time/end_time/difficulty) | `dungeonPulls` |
| player | auto_id | 玩家统计 (class/spec/ilvl/DPS/total_casts) | `damage-done` + `healing` + `summary` |
| ability | auto_id | 技能明细 (damage_amount + cast_count [hits]) | `damage-done.abilities` + `casts.abilities` |
| aura | auto_id | Buff 覆盖率 (队伍级别) | `buffs.auras` (>30% 覆盖率) |
| event | auto_id | 战斗事件 (仅 death + interrupt) | `summary.deathEvents` + `interrupts` |
| npc | auto_id | NPC 实体 (全副本聚合) | `/report/fights/` enemies |

---

## comparison JSON 结构 (8 节)

| 节 | 关键字段 |
|----|---------|
| meta | our_code, our_zone, top_code, top_zone, top_title, generated_at |
| summary | total_damage, total_healing, total_deaths, avg_ilvl, total_duration_sec, dps_ratios[], overall_dps_ratio |
| damage_composition | our_players[]/top_players[] (name/class/spec/damage_total/top_abilities[]), same_spec_pairs[] |
| cast_activity | our_players[]/top_players[] (name/total_casts/duration_sec/cpm), window_density_5s: available=false |
| cooldown_usage | our_players[]/top_players[] (name/all_abilities[]: spell_id/name/cast_count/damage_amount), unmapped_spells |
| deaths_and_damage | our/top: deaths[] (player/relative_sec/killing_ability/pre_death_damage), interrupts (total/by_player[]/by_ability[]) |
| route_timeline | our/top: fights[] (name/is_boss/kill/start_rel_sec/duration_sec), npcs_global, boss_order, boss_order_match |
| resource_cycling | available: false (V1 API 端点空响应) |
| buff_coverage | our_players[]/top_players[] (name/auras[]: name/spell_id/uptime_pct), same_spec_buff_diff[] |

---

## V1 API 端点详情

| 端点 | 响应状态 | 返回内容 |
|------|---------|---------|
| `/report/fights/{code}` | ✅ 200 | 报告元数据、玩家列表、NPC 列表、dungeonPulls |
| `/tables/damage-done/{code}` | ✅ 200 | entries[{name, total, itemLevel, abilities[], damageAbilities[]}] |
| `/tables/healing/{code}` | ✅ 200 | 同上结构 |
| `/tables/damage-taken/{code}` | ✅ 200 | 拉取但未入库 |
| `/tables/summary/{code}` | ✅ 200 | playerDetails, damageDone[], healingDone[], deathEvents[] |
| `/tables/casts/{code}` | ✅ 200 | entries[{name, total, abilities[{guid, name, total}]}] |
| `/tables/deaths/{code}` | ✅ 200 | 拉取但未入库（改用 summary.deathEvents） |
| `/tables/interrupts/{code}` | ✅ 200 | 嵌套 entries 结构，含 timestamp/ability/details |
| `/tables/buffs/{code}` | ✅ 200 | auras[{name, guid, totalUptime}], totalTime |
| `/tables/resources/{code}` | ❌ 空响应 | 始终返回空 |
| `/tables/auras/{code}` | ❌ 400 | 不存在的端点 |
| `/rankings/character/...` | ✅ (非 CN) | 玩家排名数据 |

---

## 计划内但未启用的能力

| 能力 | 状态 | 所需条件 |
|------|------|---------|
| WCL V2 events 接入 | V2Client 已完成，未接入管道 | OAuth 凭证 + v2_pipeline 设计 |
| 施法时间轴分析 (窗口密度/长间隔) | 依赖 V2 events | 同上 |
| 爆发对齐验证 (崩摧 vs 巨人打击窗口) | 依赖 V2 events | 同上 + 技能配对规则库 |
| 死前伤害序列 | 依赖 V2 events | 同上 |
| 个人 Buff 区分 | V2 理论上支持 | 需验证 GraphQL schema |
| 资源溢出检测 (怒气/圣能) | 依赖 V2 events | 同上 |
| raider.io 顶层匹配自动化 | 脚本 `find_matching_top.py` 已写但未调试 | raider.io 排行 API 不稳定 |

---

## 已知限制

1. **raider.io 国服不可用**：角色 API 不支持 CN 服务器
2. **raider.io 排行端点异常**：返回 HTML 而非 JSON，疑似废弃
3. **WCL 前端全封**：Cloudflare 拦截所有浏览器请求
4. **V1 API 无时间戳**：施法/伤害/资源事件均无法按时刻分析
5. **Buff 为队伍级**：无法区分个人覆盖率
6. **SPEC_MAP 版本落后**：标记为 Dragonflight，需更新至 Midnight
