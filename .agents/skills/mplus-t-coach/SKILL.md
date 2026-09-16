---
name: mplus-t-coach
description: "T 系列单人教练模式 — 织雾学员·第一版。面向织雾武僧（鹤僧）的 1v1 固定对标教练系统，对标选手孙青云/绿绿月光。与 X 系列同构的完整四阶段管线（教材提取→WCL基准→报告骨架→填充诊断），治疗专精变体。使用 mplus_pipeline.py t 一次性产出全部数据。"
version: 1.4.0
requires_env: [WCL_API_KEY]
metadata:
  tags: [wow, warcraft-logs, mythic-plus, analysis, coaching, mistweaver-monk]
  migrated_from: hermes
---

# T 系列 — 织雾学员进阶之路·第一版

基于 Warcraft Logs v1 API 的织雾武僧（鹤僧）教练模式。与 X 系列架构同构，仅职业专精、对标选手、基准不同。

> CLI：`mplus_pipeline.py t <args>` — 见 CLI 速查
> 由 `mplus-analysis` 路由中枢触发加载（触发短语：`鹤僧指导` `桃鹤僧` `孙青云教学` `T1` `织雾指导`）

---

## 核心原则

**孙青云的教学内容（B站视频）是核心教材，WCL 实战数据是辅助验证。** 与 X 系列的教材来源优先级完全一致。

## 身份信息

| 角色 | 姓名 | 服务器 | WCL |
|------|------|--------|-----|
| **对标选手（绿绿月光）** | 绿绿月光 | 伊森利恩 (CN) | [报告 DLQHbFkqyX14dvgr](https://cn.warcraftlogs.com/reports/DLQHbFkqyX14dvgr) |
| **孙青云 B站** | 孙青云 | — | BV1vvwozkEZ5 / BV1na9nB8EZF / BV1FzQHBoEmE |

## 绿绿月光基准信息

| 项目 | 值 |
|------|-----|
| 已知报告 | DLQHbFkqyX14dvgr (艾杰斯亚+21 fight=92, 执政团+22 fight=102) |
| class 过滤 | 同服有同名 Priest 号，搜索时必须 class=10 过滤 |

## 知识卡片目录结构

```
data/taozhi/knowledge_base/孙青云/
├── 00_README.md                     # 索引 + 教材来源表
├── 01_孙青云-总纲.md                # 核心理念 + 配装属性
├── 02_孙青云-天赋.md                # 天赋构筑 + 8本变体
├── 03_孙青云-循环.md                # 治疗循环/爆发/资源管理
├── 04_孙青云-生存.md                # 生存策略 + 减伤使用
├── 05_孙青云-副本.md                # 8本副本机制对策
└── 转录勘误对照.md                  # Whisper 错误对照表
```

## 执行协议

1. **Phase 0 — 知识库门禁**：检查 `data/taozhi/knowledge_base/孙青云/` 完整（7 文件）
2. **Step 0 — WCL 门禁**：检查基准 JSON、DB 缓存、fight_id 提取
3. **Step 1 — 基准建立**：通过 Rankings API 搜索绿绿月光（class=10），跑 v1_pipeline + extract-benchmark
4. **Step 1 — 管线**：`taozhi_pipeline.py <code> --fight-id N`
5. **Step 2 — 骨架**：`taozhi_report_builder.py <code>`
6. **Step 3 — 填充**：6 占位符（同 X 系列），孙青云口吻。**必须先执行填充报告门禁协议（见 references/report-filling-gate.md），加载知识卡片后再填占位符。**

## 报告文件命名规范

T 系列与 X 系列遵循统一的命名约定：
### 字段说明
- **副本名+N**：国服副本简称 + 层数，如 `风行者之塔+10`
- **里程碑/期数**：`第一期` / `第二期` / `第三期`……按分析先后顺序递增，不重复
- **第N周**：按魔兽服务器 CD 周计算。**周四早 8:00 为重置节点**（国服），重置前为本周、重置后为下周
- **第0周**：仅用于赛季前的基线测试，正式输出从第 1 周开始

### 示例
| 系列 | 文件名 |
|------|--------|
| T | `示例学员_风行者之塔+10_第三期_第2周.md` |
| T | `示例学员_执政团之座+12_第二期_第1周.md` |
| X | `小雪_风行者之塔+10_第三期_第3周.md` |

报告文件统一存入 `data/reports/` 目录，Markdown 源文件与 PDF 同名不同后缀。

---

## 报告生成规范

同 X 系列结构（12 节，含 P0 摘要三层格式），区别：
- 📈 总览：含 HPS + 伤害行（鹤僧伤转治疗）
- 🔧 技能评估：治疗技能全表 + 伤害技能缩略
- 📊 治疗轴对比 + ⏱ 治疗向深度解析
- 📈 进步对比：使用 HPS 而非 DPS，里程碑参考绿绿月光

### P0 摘要三层格式（与 X 系列完全一致）

```
### 🔴 P0-{N}：{一句话定义核心问题}

{一句话解释——学员做了什么 vs 孙青云教了什么}

三个关键差距：
1. {差距 A — 一行说清}
2. {差距 B — 一行说清}
3. {差距 C — 一行说清}

> → 详细分析见下方 📊 治疗轴对比 → {节名}
```

**T 系列的 P0 选题方向**：
- P0：死亡/减伤/关键技能没交（壮胆酒/作茧缚命/散魔功未覆盖高压波次）
- P0：治疗资源分配错位（复苏之雾铺太多 x 鹤僧手法矛盾、神龙之赐不在大掉血波次）
- P0：法力管理失控（法力茶使用次数/蓝量规划）
- P1：伤害输出不足（鹤僧伤转治疗模型下，DPS 低意味着治疗量也会低）
- P1：打断/控制遗漏 ⚠️ **注意：12.0 版本鹤僧无打断技能**（只有奶萨有），0 次打断**不应批评**。如果要检查控制，看扫堂腿/瘫痪等硬控技能使用

### 📊 施法时间轴分析章节（管线自动生成）

T 流程报告**必须包含**「逐波次施法序列对比」章节，这是与 X 流程对应的核心结构。

**数据来源**：`t_comparison.json`（由 events API 管线生成）

**自动生成机制**（2026-05-14 修复）：
`_write_placeholder_skeleton` 在 Phase 5 检测 `t_comparison_{code}.json` 是否存在，若存在则调用 `_build_wave_comparison_tables()` 自动产出：
- **波次总览表**：全部波次的名称/类型/时长/施法数/密度差
- **关键波次序列对比**（Top 4 高压波次）：按 BOSS+5 / 密度×10 / 施法数×0.01 加权评分选取，展示前 12 个施法序列对比、Top 5 高频技能、自动诊断（如检测复苏之雾≥2 次 → "读条/铺雾浪费 GCD"）
- **施法节奏总结表**：总施法数 / 平均密度 / 波次数三行对比

> ⚠️ 如果 comparison JSON 不存在，章节输出提示"未找到 comparison JSON"而非留占位符。**不再留空让模型手写。**

**分析维度**（模型填充诊断文字时参考）：

| 维度 | 内容 | 对比基准 |
|------|------|---------|
| 三板斧节奏 | 旭日→幻灭→神鹤的序列是否完整，有无断裂期 | 绿绿月光同波次序列 |
| 神龙之赐对齐 | 神龙之赐是否在团队大掉血前施放，还是随意穿插 | 教练的施放时间窗口 |
| 减伤预判 | 壮胆酒/散魔功/作茧缚命是否在尖刺伤害前使用 | 死亡时间点前 5-10s |
| 读条占比 | 抚慰之雾/复苏之雾的施放位置——是否出现在高压期 | 教练波形该位置无读条 |
| 起手/转阶段 | 开怪起手技能序列是否正确（鹤僧应直接三板斧） | 教练起手序列 |

**建议展示格式**（逐波次）：

```
### 第N波：{波次名}（{类型}，{时长}）

| 时间 | 学习者施法序列 | 教练典型节奏 | 诊断 |
|------|--------------|------------|------|
| 起手 | 复苏之雾 ❌ | 神鹤引项踢 ✅ | 浪费 GCD |
| ~2s | 神鹤引项踢 | 旭日东升踢 | 节奏偏缓 |
| ... | ... | ... | ... |

**本波结论**：{一句话总结}
```

**`_build_wave_comparison_tables()` 在 Phase 5 自动生成该章节**（详见上方"自动生成机制"）。

### 孙青云口吻参考

沉稳讲解型，用"你"。参考：治疗资源→"别把复苏挂得太散"、"该波次得开壮胆"；死后→"没预读""断疗了"；表扬→"还行""节奏对了"。

**6 个占位符**：`{{DIAGNOSIS}}` `{{DO_WELL_FINAL}}` `{{IMPROVE_FINAL}}` `{{DEATH_ROOT_CAUSE}}` `{{TRAINING_TASKS}}` `{{COACH_NOTE}}`

## 治疗分析要点

- 首要关注 HPS，鹤僧需同时看输出与治疗的关联
- 过量治疗率判断铺雾时机
- 作茧缚命/壮胆酒/散魔功的预判使用
- 神龙之赐对齐大掉血波次

## 填充报告步骤（post-pipeline manual report writing）

**taozhi_report_builder.py 不存在时**，管线输出骨架 + m2_group_a/b/c + comparison JSON。模型须手动填充完整报告，步骤如下：

### 🔒 Step 0：填充报告门禁（强制，不可跳过）

填充占位符前必须执行 `report-filling-gate.md` 协议：

1. 加载知识卡片（用 `read` 工具按绝对/相对路径读取，本 skill 目录记作 `<SKILL_DIR>` = `.agents/skills/mplus-t-coach/`）：
   - `data/taozhi/knowledge_base/孙青云/03_孙青云-循环.md`
   - `data/taozhi/knowledge_base/孙青云/04_孙青云-生存.md`
   - `data/taozhi/knowledge_base/孙青云/05_孙青云-副本.md`
   - 若目录缺失，先报告"知识库门禁未通过"，不要凭记忆写技能建议
2. 循环卡片重点确认：技能机制（什么技能可预铺、什么技能不可）、三板斧优先级、神龙之赐使用规则
3. 出口验收：报告中每一条技能建议均可在卡片中找到依据

详见 `references/report-filling-gate.md`。

### Step A：获取学习者总治疗量 / HPS

管线骨架中的 `{{HPS}}` 是占位符，**管线不会自动填充学习者 HPS**。需手动查询 healing table API：

```bash
# 获取学习者总治疗量 → 手动计算 HPS
curl -s "https://www.warcraftlogs.com/v1/report/tables/healing/{code}?start={fight_start_ms}&end={fight_end_ms}&api_key={KEY}" | python3 -c "
import json,sys
data = json.load(sys.stdin)
for e in data.get('entries',[]):
    print(f'{e[\"name\"]}: total={e.get(\"total\",0)} overheal={e.get(\"overheal\",0)}')
"
# HPS = heal_total / (fight_duration_ms / 1000)
```

- fight_start/end 从 `/v1/report/fights/{code}` 的 fight 条目中获取
- 也可以通过 `m2_meta.txt` 的总时长推算

### Step B：从 comparison JSON 提取波次对比数据

`t_comparison_{code}.json` 包含逐波次施法密度对比：
- `summary.learner_avg_density` / `summary.benchmark_avg_density` — 施法密度
- `summary.learner_wave_count` / `summary.benchmark_wave_count` — 波次数
- `death_healing[]` — 死亡前治疗窗口（⚠️ V1 API 可能返回 0）
- `waves_learner[]` — 每波的 `top_skills` + `casts_simple`（施法时间线）

### Step C：从 m2_group_a.txt 提取学习者技能次数

Group A 中含有学习者各技能的施法次数。引用时注意：
- 鹤僧的 PBAOE 技能（神鹤引项踢、碧火踏）在 V1 中标记为 `[自动触发/pet技能, hits=0]`，实际次数存于 `skill_composition` 的 hits 字段
- 治疗技能（神龙之赐、复苏之雾等）有具体施法次数

### Step D：对比基准时注意副本差异

绿绿月光的基准可能来自不同副本/层数（如执政团之座 +22 vs 学习者 风行者之塔 +10）：
- 层数越高治疗压力越大 → 基准技能次数偏高
- 某些副本机制特殊（如执政团大量 AOE）→ 特定技能（如氤氲之雾）使用更多
- **复苏之雾次数是跨副本也成立的诊断指标**：鹤僧在任何副本都不该大量铺雾
- **幻灭踢/旭日/神鹤的比例** 比绝对次数更有诊断价值

## 报告管线的已知缺口

### taozhi_report_builder.py 不存在（管线 fallback）

**现状**：管线 fallback 到 `_write_placeholder_skeleton()`。该函数写入包含 12 节结构的占位骨架。

**2026-05-13 修复：基准技能次数自动填充** — `_write_placeholder_skeleton` 现接受 `bm_profile_path` 参数，自动读取 `lvlyue_benchmark_profile.json` 的 `skill_composition`，在总览表中填入绿绿月光侧的技能次数。

**2026-05-14 修复：施法时间轴对比自动生成** — `_write_placeholder_skeleton` 新增 `comparison_path` 参数。在 Phase 5 自动检测 `t_comparison_{code}.json`，调用 `_build_wave_comparison_tables()` 自动生成：
- 波次总览表（全部波次）
- 关键波次序列对比（Top 4 高压波次，含自动诊断）
- 施法节奏总结表
详见上方「📊 施法时间轴分析章节」的自动生成机制。

**剩余缺口**：
- 总览表的学习者侧次数（如 `{{LEARNER_作茧缚命}}`）仍需模型填充
- 技能评估表（🔧 章节）尚未自动填充基准侧数据
- 完整 `taozhi_report_builder.py` 仍未实现

### 基准配置存放位置与字段路径

`data/taozhi/lvlyue_benchmark_profile.json` → `skill_composition → {技能名} → hits`

该文件由 `extract-comparison` 步骤（v1_pipeline → fetch_top_benchmarks → extract_comparison）生成。
**已修复**（2026-05-13）：`_write_placeholder_skeleton` 在 Phase 5 消费基准配置，自动填充总览表的绿绿月光技能次数。`bm_profile_path` 参数由 `_run_coaching_pipeline` 计算传入。

## 已知陷阱

- T-01: 治疗量 vs 伤害量混淆（鹤僧需同时呈现）
- T-02: 过量治疗干扰（区分有效 vs 有效+过量）
- T-05: 基准 JSON 需 heal_total 和 damage_total 字段
- T-07: V1 ability 表治疗技能 amount=0，查询用 WHERE amount=0 AND hits>0
- T-10: event 表 death timestamp 单位是毫秒，显示时 /1000
- **T-20: 🟢 基准技能次数缺口已修复 (2026-05-13)** — `_write_placeholder_skeleton` 现读取 `lvlyue_benchmark_profile.json` 并自动填充总览表的绿绿月光技能次数。总览表不再出现 `—`。技能评估表（🔧 章节）的基准侧数据尚未自动填充——该表目前只显示学习者次数+分析列，不包含教练对比列，因此不受此问题影响。
- **T-21: 管线不输出学习者 HPS** — `_write_placeholder_skeleton` 生成 `{{HPS}}` 占位符但管线不填充。报告填充阶段必须手动查 healing table API 获取 `heal_total` 并计算 HPS。详见「填充报告步骤—Step A」。
- **T-22: 基准可能来自不同副本/层数** — 绿绿月光基准来自执政团之座 +22 或艾杰斯亚 +21，与学习者副本不同。报告中的绝对次数对比需加以注释说明。但手法模式（复苏之雾数量、幻灭踢比例）跨副本仍成立。
- **T-23: events API death_healing 可能返回 0** — V1 events 端口的 sourceid 查询在死亡窗口内可能探测不到治疗事件（特别是如果学习者自身已死亡）。死亡根因分析仍可通过死亡集群 + m2_group_b 的致死技能推断。
- **T-24: 鹤僧伤害技能在 Group A 中为 auto-tick** — 神鹤引项踢、碧火踏在 Group A 的施法列表中标记为 `[自动触发/pet技能, hits=0]`，但实际施法次数仍需取自单独的 hits 字段。引用 Group A 数据时注意不要漏算。
- **T-25: 12.0 鹤僧无打断技能** —— 模型中只有奶萨有打断。报告中不得批评 "鹤僧 0 次打断"。如果要做控制检查，看扫堂腿/瘫痪/平心之环等硬控技能。
- **T-27: 鹤僧术语准确性 — "预铺"只能用于氤氲之雾，不能用于神龙之赐** —— 神龙之赐是"攒层数等损伤出来→释放"，属于**反应型刷血**而非预铺技能。可预铺的是氤氲之雾（HoT 提前挂上）。写诊断时注意区分：
  - ✅ "提前挂氤氲之雾预铺 + 攒好神龙之赐层数"
  - ❌ ~~"预铺神龙之赐"~~（神龙之赐不能预铺，10 层精通：天猴攒满了即可在掉血瞬间打出）
  - 绿绿月光氤氲之雾 107 次中有大量是预铺使用，而神龙之赐 131 次都是掉血后释放
  - 同样：作茧缚命是"预判给"（提前给）、壮胆酒是"提前开"（大减伤），都不是"预铺"
- **T-D1: T mode 不得降级为 X mode** — 治疗分析的指标、基准、骨架与 DPS 完全不同。
  `run_t_mode` 必须走自身管线 (v1_pipeline → 治疗基准 → 治疗骨架)，不得调用 `run_x_mode`。
  `taozhi_pipeline.py` 不存在时，直写治疗向最小骨架（`_write_healing_skeleton`）作为 fallback。

**Pitfall T-27: 🚨 填充报告前必须先加载知识卡片（2026-05-14）** —
写任何技能建议前先验证卡片。如写"预铺"类建议，须确认技能是否支持预铺（神龙之赐不支持，氤氲之雾支持）。
具体门禁协议见 `references/report-filling-gate.md`。
本 Pitfall 与 X2-15 共享。

## 鹤僧手法诊断参考（基于绿绿月光基准）

鹤僧治疗输出由三板斧（旭日→幻灭→猛虎/神鹤）驱动神龙之赐，而非铺复苏之雾。

### 关键基准数值参考

| 技能 | 绿绿月光 (+22 执政团) | 诊断阈值 |
|------|---------------------|---------|
| 神鹤引项踢 | 478次 | 主力 AOE 手段，≥300 次/全本 |
| 旭日东升踢 | 307次 | 核心触发技能，≥200 次/全本 |
| 神龙之赐 | 131次 | 主刷血技能，≥100 次/全本 |
| 复苏之雾 | **~1次** | **鹤僧基本不掉**——如果学员用了 50+ 次，说明还在用龙僧思维铺雾 |
| 作茧缚命 | 16次 | 应急盾，≥10 次/全本 |
| 壮胆酒 | 8次 | 3min CD 大减伤，全本约 8 次机会 |

**复苏之雾次数是区分龙僧/鹤僧手法的核心指标**。绿绿月光整个执政团+22 只用了 1 次复苏之雾（可能只是开怪前的预铺），学员如果用了几十次，说明手法路线错误——把时间花在了铺雾上而非打三板斧触发神龙。

## CLI 速查

```bash
# 完整管线（单次调用）
WCL_API_KEY=<YOUR_WCL_V1_KEY> \
PYTHONPATH=. python3 core/mplus_pipeline.py t \
  --report-code <CODE> \
  --fight-id <N> \
  --benchmark-char 绿绿月光 \
  --benchmark-report <教练CODE> \
  --benchmark-fight <N>

# 测试验收
PYTHONPATH=. python3 -m unittest tests.test_mplus_pipeline.TestModeT -v
```

## 参考文件

路径分三类：`<SKILL_DIR>/...` 在本 skill 目录内；其余相对仓库根。

| 文件 | 用途 | 状态 |
|------|------|------|
| `<SKILL_DIR>/references/report-filling-gate.md` | **填充报告门禁协议**（Step 0 必读） | ✅ |
| `<SKILL_DIR>/references/skill-walkthrough.md` | 本 skill 的精简讲解版 | ✅ |
| `<SKILL_DIR>/references/sunqingyun-research.md` | 孙青云调研资料 | ✅ |
| `templates/taozhi-coaching-template.md` | T 系列报告模板 | ✅ |
| `data/taozhi/knowledge_base/孙青云/` | 孙青云知识卡片 | ⚠️ 运行期数据，需自备 |
| `data/taozhi/lvlyue_benchmark_profile.json` | 绿绿月光基准 | ⚠️ 运行期数据，需自备 |
| `references/wcl-healing-api-notes.md` | WCL V1 healing 数据模式 | ❌ 迁移时未随行，见 `wcl-player-review/references/healing-review.md` |
| `references/manual-report-filling-example.md` | 手动填充报告示例 | ❌ 迁移时未随行 |
