#!/usr/bin/env python3
"""
[DEPRECATED] 请使用 core.report_builder.ReportBuilder

core/meishu_report_builder.py — 梅叔酒仙报告骨架构建器（已弃用）

复用 report_skeleton.py 的 load_meta/load_group_b，新增硬玩复仇基准加载和
梅叔专用表格/候选生成。输出含 7 个占位符的半成品 Markdown。

用法:
    PYTHONPATH=. python3 core/meishu_report_builder.py <report_code>

输入:
    data/cache/m2_meta_{code}.txt
    data/cache/m2_group_b_{code}.txt
    data/meishu/yingwan_benchmark_profile.json
    data/meishu/progress.db (可选)

输出:
    data/cache/m2_meishu_skeleton_{code}.md
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from core.report_skeleton import load_meta, load_group_b, format_num

# ── 路径 ──
PROJECT_DIR = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_DIR / "data" / "cache"
MEISHU_DIR = PROJECT_DIR / "data" / "meishu"
BENCHMARK_PATH = MEISHU_DIR / "yingwan_benchmark_profile.json"
TEMPLATE_PATH = PROJECT_DIR / "templates" / "meishu-coaching-template.md"

# 酒仙核心技能 (spell_id → 中文名)
BREWMASTER_CORE_SKILLS: dict[int, str] = {
    121253: "醉酿投",
    123725: "火焰之息",
    100784: "幻灭踢",
    100780: "猛虎掌",
    101546: "神鹤引项踢",
    123730: "龙焰酒",
    386285: "玄牛下凡",
    395403: "天神灌注",
    443006: "淬火神酿",
    115399: "活血酒",
    115203: "壮胆酒",
    449642: "禅悟状态",
    122783: "散魔功",
    124503: "玄牛之赐",
    116705: "切喉手",
}


# ══════════════════════════════════════════════════════
# 数据加载
# ══════════════════════════════════════════════════════


def load_yingwan_benchmark() -> dict:
    if not BENCHMARK_PATH.exists():
        print(f"警告: 硬玩复仇基准文件不存在: {BENCHMARK_PATH}", file=sys.stderr)
        return {}
    with open(BENCHMARK_PATH, encoding="utf-8") as f:
        return json.load(f)


def load_inputs(report_code: str) -> dict[str, Any]:
    meta_path = CACHE_DIR / f"m2_meta_{report_code}.txt"
    gb_path = CACHE_DIR / f"m2_group_b_{report_code}.txt"

    meta = load_meta(str(meta_path))
    gb = load_group_b(str(gb_path))
    bm = load_yingwan_benchmark()

    return {"meta": meta, "group_b": gb, "benchmark": bm}


# ══════════════════════════════════════════════════════
# 优先级判定
# ══════════════════════════════════════════════════════


def detect_priority(
    skill_name: str,
    ours: dict | None,
    tops: dict | None,
    deaths: int = 0,
    vs_ratio: float = 1.0,
) -> str:
    """自动判定优先级 (P0/P1/P2)。"""
    # P0: 核心减伤技能缺失 / 死亡 ≥ 3 / DPS 差距 > 50%
    if deaths >= 3:
        return "P0"
    if skill_name in ("壮胆酒", "活血酒", "禅悟状态") and vs_ratio < 0.5:
        return "P0"
    if vs_ratio < 0.5:
        return "P0"

    # P1: 中等差距
    if vs_ratio < 0.7:
        return "P1"

    return "P2"


def vs_ratio(ours: float | None, tops: float | None) -> float:
    if ours is None or tops is None or tops == 0:
        return 0.0
    return ours / tops


# ══════════════════════════════════════════════════════
# 构建骨架
# ══════════════════════════════════════════════════════


def build_skeleton(report_code: str) -> str:
    inputs = load_inputs(report_code)
    meta = inputs["meta"]
    bm = inputs["benchmark"]

    dungeon = meta.get("dungeon", "?")
    level = meta.get("level", "?")
    duration = meta.get("duration", "?")
    keystone_timed = meta.get("keystone_timed", 0)
    timed_text = "限时" if keystone_timed else "超时"

    # ── 标题 ──
    lines = [
        f"# 🍺 梅叔酒仙进步之路 — {dungeon} +{level} · 首期诊断",
        "",
        f"> 师傅：硬玩复仇 (硬玩复仇绿色-白银之手) | 徒弟：梅夫三拳",
        f"> 副本：{dungeon} +{level} | {timed_text} | 用时：{duration} | 第 1 周",
        f"> 日期：{datetime.now().strftime('%Y-%m-%d')}",
        "",
        f"**WCL**: https://cn.warcraftlogs.com/reports/{report_code}",
        "",
    ]

    # ── 总览表 ──
    lines.append("## 📈 本周表现总览")
    lines.append("")
    lines.append("| 指标 | 本周 | 硬玩复仇 | 差值 |")
    lines.append("|---|---|---|---|")

    # 从 meta 获取 DPS，从 benchmark 获取硬玩复仇数据
    learner_dps = meta.get("dps", "?")
    bm_dps = bm.get("dps", "?")
    bm_hps = bm.get("hps", "?")
    lines.append(f"| DPS | {learner_dps} | {bm_dps} | {{DPS_GAP}} |")
    lines.append(f"| 自疗 HPS | {{SELF_HPS}} | {bm_hps} | {{SELF_HPS_GAP}} |")
    lines.append(f"| DTPS | {{DTPS}} | — | — |")

    deaths = meta.get("deaths", 0)
    lines.append(f"| 死亡 | {deaths} | — | — |")
    lines.append(f"| 打断 | {{INTERRUPTS}} | {{BM_INTERRUPTS}} | — |")
    lines.append("")

    # 从基准填充技能行
    bm_skills = bm.get("skill_composition", {})
    overview_skills = ["壮胆酒", "活血酒", "玄牛下凡", "禅悟状态", "醉酿投", "火焰之息"]
    for sk_name in overview_skills:
        if sk_name in bm_skills:
            bm_hits = bm_skills[sk_name].get("hits", 0)
            lines.append(f"| {sk_name} | {{{{LEARNER_{sk_name}}}}} | **{bm_hits}次** | {{{{GAP_{sk_name}}}}} |")
        else:
            lines.append(f"| {sk_name} | {{{{LEARNER_{sk_name}}}}} | — | {{{{GAP_{sk_name}}}}} |")
    lines.append("")

    # ── 技能评估表 ──
    lines.append("## 🔧 技能使用评估")
    lines.append("")
    lines.append("### 伤害技能")
    lines.append("")
    lines.append("| 技能 | 学习者次数 | 硬玩复仇次数 | 差距 | 评级 | 分析 |")
    lines.append("|---|---|---|---|---|---|")
    dmg_skills = ["醉酿投", "火焰之息", "幻灭踢", "猛虎掌", "神鹤引项踢", "龙焰酒", "玄牛下凡", "淬火神酿"]
    for sk in dmg_skills:
        bm_hits = 0
        if sk in bm_skills:
            bm_hits = bm_skills[sk].get("hits", 0)
        lines.append(f"| {sk} | {{{{L_{sk}}}}} | {bm_hits} | {{{{G_{sk}}}}} | 🟡 | {{{{A_{sk}}}}} |")
    lines.append("")

    lines.append("### 生存/减伤技能")
    lines.append("")
    lines.append("| 技能 | 学习者次数 | 硬玩复仇次数 | 差距 | 评级 | 分析 |")
    lines.append("|---|---|---|---|---|---|")
    surv_skills = ["活血酒", "壮胆酒", "禅悟状态", "散魔功", "明志灵药", "玄牛之赐"]
    for sk in surv_skills:
        bm_hits = 0
        if sk in bm_skills:
            bm_hits = bm_skills[sk].get("hits", 0)
        lines.append(f"| {sk} | {{{{L_{sk}}}}} | {bm_hits} | {{{{G_{sk}}}}} | 🟡 | {{{{A_{sk}}}}} |")
    lines.append("")

    # ── 做得好 / 需要改进 ──
    lines.append("## ✅ 做得好")
    lines.append("{{DO_WELL_FINAL}}")
    lines.append("")
    lines.append("## ❌ 需要改进")
    lines.append("{{IMPROVE_FINAL}}")
    lines.append("")

    # ── 坦克轴对比 ──
    lines.append("## 📊 坦克轴对比")
    lines.append("")
    lines.append("> 以下章节需结合 events API 数据填充。")
    lines.append("> 数据来源：m_comparison_{code}.json（如有）")
    lines.append("")
    lines.append("{{WAVE_COMPARISON}}")
    lines.append("")

    # ── 技能深度解析 ──
    lines.append("## ⏱ 技能深度解析")
    lines.append("")
    lines.append("{{SKILL_DEEP_DIVE}}")
    lines.append("")

    # ── 死亡分析 ──
    lines.append("## 💀 死亡分析")
    lines.append("")
    lines.append("{{DEATH_ROOT_CAUSE}}")
    lines.append("")

    # ── 改进计划 ──
    lines.append("## 📅 改进计划")
    lines.append("")
    lines.append("| 优先级 | 改进项 | 具体目标 | 练习方法 |")
    lines.append("|---|---|---|---|")
    lines.append("| 🔴 P0 | {{P0_ITEM}} | {{P0_TARGET}} | {{P0_METHOD}} |")
    lines.append("| 🟡 P1 | {{P1_ITEM}} | {{P1_TARGET}} | {{P1_METHOD}} |")
    lines.append("| 🟢 P2 | {{P2_ITEM}} | {{P2_TARGET}} | {{P2_METHOD}} |")
    lines.append("")

    # ── 师傅的话 ──
    lines.append("## 💬 硬玩复仇的话")
    lines.append("{{COACH_NOTE}}")
    lines.append("")

    # ── 趋势 ──
    lines.append("## 📈 进步趋势")
    lines.append("")
    lines.append("> 初始基准报告，暂无趋势数据。")
    lines.append("")
    lines.append("```")
    lines.append(f"第1周({dungeon}+{level}):")
    lines.append("DPS:   {{DPS}}")
    lines.append("自疗:  {{SELF_HPS}}")
    lines.append("活血酒: {{PURIFY_COUNT}}")
    lines.append("壮胆酒: {{FORTBREW_COUNT}}")
    lines.append("死亡:   {{DEATHS}}")
    lines.append("```")
    lines.append("")

    # ── 里程碑 ──
    lines.append("## 📊 里程碑追踪")
    lines.append("")
    lines.append("| 里程碑 | 条件 | 状态 |")
    lines.append("|---|---|---|")
    lines.append("| 🥉 萌新出村 | 首次限时 M0，减伤技能使用基本合理 | ❌ |")
    lines.append("| 🥈 蓝分入门 | 相比硬玩复仇差距 ≤30%（三轴综合） | ❌ |")
    lines.append("| 🥇 紫分进阶 | 相比硬玩复仇差距 ≤15%，存活率 ≥95% | ❌ |")
    lines.append("| 🏆 橙分坦克 | 相比硬玩复仇差距 ≤5%，能自主规划减伤链 | ❌ |")
    lines.append("")

    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print("用法: python3 core/meishu_report_builder.py <report_code>", file=sys.stderr)
        sys.exit(1)

    code = sys.argv[1]
    report_dir = CACHE_DIR
    report_dir.mkdir(parents=True, exist_ok=True)

    skeleton = build_skeleton(code)
    out_path = report_dir / f"m2_meishu_skeleton_{code}.md"
    out_path.write_text(skeleton, encoding="utf-8")

    print(f"[meishu_report_builder] ✅ 骨架已写入: {out_path}")
    print(f"    大小: {len(skeleton)} chars")


if __name__ == "__main__":
    main()
