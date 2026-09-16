# 大秘境分析模块 (M1) 完成度评估

## 总评：70% — 核心链路可用，但分析深度受限，外部依赖两条断链

---

## 一、已完成功能

### ✅ 数据入库 (`v1_pipeline.py`)
- **完成度**: 95%
- WCL V1 API 12 端点 → 7 表 SQLite，幂等写入
- `--fight-id` 过滤多副本聚合报告
- DoT/通道技能 hits=0 防御 (comparison_engine 侧)
- 小瑕疵：SPEC_MAP 版本落后，wcl_parser 模块归档会断裂导入

### ✅ 双数据对比 (`comparison_engine.py`)
- **完成度**: 90%
- 8 节结构化 JSON，异常不级联
- `same_spec_pairs()` 按专精分组、damage 排序一一配对
- `available: false` 透传机制，不可用维度不编造数据
- 小瑕疵：硬编码副本名 (萨隆矿坑) 在 build_analysis_summaries.py

### ✅ 摘要压缩 (`build_analysis_summaries.py`)
- **完成度**: 85%
- 112KB JSON → 5KB 三组摘要，95.5% 压缩率
- spell_id 桥接中英文技能名
- 自动触发/pet 技能标注
- 死亡集群启发式根因推测
- 小瑕疵：硬编码玩家名 (牛劲儿/当归等) 用于坦克/治疗归类

### ✅ 并行分析 (delegate_task 3 路)
- **完成度**: 80%
- 3 个子 Agent 并行，128-159s 完成
- 零中断（vs 激进压缩方案的 49s 但全员中断）
- 局限：子 Agent 无法调用外部 API，仅能消费摘要文本

### ✅ 最终报告输出
- **完成度**: 80%
- 结构化中文报告：核心指标 + 5 对/5 错 + MVP/战犯 + 个人提升 + 下 CD 清单
- 报告模板在 mplus-analysis skill 中定义
- 局限：无对比时降级为自我分析，削弱了量化差距的能力

---

## 二、降级/妥协项

### ⚠️ 顶层对比查找 → 手动/半自动
- **原计划**: raider.io 排行榜自动匹配 → WCL 反查 code → 自动入库
- **实际状态**: raider.io 排行 API 疑似废弃(返回 HTML)，国服角色 API 无响应
- **当前做法**: ① 用户直接提供顶层报告码 ② self-analysis 降级模式
- **影响**: 最核心的对比功能不可自动化

### ⚠️ 施法活跃度 → 仅 CPM
- **原计划**: 窗口密度(5s GCD 利用率)、长间隔检测、最大间隔
- **实际状态**: 全部标 `available: false`，仅有总次数÷时长的粗略 CPM
- **影响**: 无法区分"一直丢技能但优先级错"和"频繁断档"

### ⚠️ 冷却爆发分析 → 仅次数
- **原计划**: 爆发对齐时机、爆发覆盖增伤窗口的伤害占比
- **实际状态**: 仅统计聚合施法次数，无时间戳
- **影响**: 无法回答"崩摧是否打在巨人打击窗口内"这类关键问题

### ⚠️ 死亡分析 → 无死前伤害
- **原计划**: 死亡前 5s 伤害序列，可避免伤害检测
- **实际状态**: `pre_death_damage_5s: available=false`
- **影响**: 无法判断是"一波猝死"还是"慢慢流血死"

### ⚠️ 资源流转 → 完全不可用
- **原计划**: 怒气/圣能/灵魂碎片的获取-消耗-溢出
- **实际状态**: `/tables/resources` 始终空响应，JSON 中 `available: false`
- **影响**: 零覆盖

### ⚠️ WCL V2 客户端 → 完成但空置
- **原计划**: 通过 V2 GraphQL 获取事件流补时间戳缺口
- **实际状态**: `v2_client.py` + OAuth + `query_events()` 全部实现，未接入管道
- **影响**: 有路不走

---

## 三、已解决 / M2 修复

### ✅ 硬编码玩家名/副本名 → 已去硬编码 (M2)
- `build_analysis_summaries.py` 原硬编码 "你那牛劲儿呢" (坦克)、"当归煲腊鸭" (治疗)、"萨隆矿坑" (副本)
- **修复**: 改为 `build_player_spec_map()` 从 comparison JSON 各章节收集 spec → `get_role()` 按专精判定坦克/治疗/DPS；副本名通过 `ZONE_NAMES` 查表 (zone_id → 名称)
- **影响**: 任意队伍/副本均可正常运行，不再依赖特定玩家

### ✅ 目录整理 → canonical 唯一
- `core/` 为唯一代码正本，根目录无 Python 同步副本
- 所有产出物统一收纳于 `data/`（cache/comparisons/reports/wcl_db）

### ✅ SPEC_MAP 审核 → 无需更新
- Dragonflight 专精 ID 仍覆盖 Midnight 全部 39 个专精（12.0 无新专精/新职业）

### ✅ M2 独立分析管道 → 已实现
- `core/m2_standalone_summary.py` 支持单 DB → 4 组摘要 (meta + groups A/B/C)
- 速度基准: ~5-15KB 输出，主 Agent 直接消费

### ❌ raider.io 国服不可用
- 国服角色 API 返回空
- 排行 API 返回 HTML（非 JSON），疑似端点被废弃或改版
- **根因**: raider.io 不支持中国区服务器
- **无 workaround**：顶层对比队伍发现完全依赖用户提供或 WCL 手动搜索

### ❌ Cloudflare 封锁
- `cn.warcraftlogs.com` 和 `www.warcraftlogs.com` 前端全封
- 浏览器、web_extract 均无法穿透
- **根因**: WCL 前端使用 Cloudflare 防爬
- **workaround**: V1 API 端点 (`www.warcraftlogs.com/v1/*`) 不受影响，但无法使用搜索、角色页、排行页

---

## 四、数据可用性矩阵

| 维度 | 状态 | 有值字段 | 空值字段 |
|------|------|---------|---------|
| §1 伤害构成 | ✅ | name, class, spec, damage_total, top_abilities[].name/spell_id/amount/pct | — |
| §2 施法活跃度 | ⚠️ | total_casts, duration_sec, cpm | window_density_5s, long_gap_count, max_gap_sec |
| §3 冷却爆发 | ⚠️ | all_abilities[].spell_id/name/cast_count/damage_amount | 时间戳、对齐质量 |
| §4 死亡承伤 | ⚠️ | player, relative_sec, killing_ability, interrupts | pre_death_damage_5s, NPC casts |
| §5 路线时间轴 | ⚠️ | fight_id, name, is_boss, kill, start_rel_sec, duration_sec, boss_order | 每波 NPC 分布 |
| §6 资源流转 | ❌ | — | 全部 |
| §7 Buff 覆盖 | ✅ (队伍级) | name, spell_id, uptime_pct, same_spec_buff_diff | 个人级区分 |
| §8 汇总指标 | ✅ | total_damage, total_healing, total_deaths, avg_ilvl, total_duration_sec, dps_ratios | — |

---

## 五、M2 下一步路线

1. **最高优先**: 接入 V2 GraphQL — 把 `available: false` 的维度全部点亮
2. **次优先**: 解决顶层对比发现的自动化 — WCL 搜索替代 raider.io
3. **进行中**: 完善 ZONE_NAMES 映射表 — 补充 Midnight 12.0 全部副本 zone_id
4. **长期**: 爆发规则库 — 为各专精定义冷却技能×增伤窗口的配对规则
