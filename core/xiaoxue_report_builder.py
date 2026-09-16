#!/usr/bin/env python3
"""
[DEPRECATED] 请使用 core.report_builder.ReportBuilder

core/xiaoxue_report_builder.py — 小雪指导报告骨架构建器（已弃用）

迁移目标:
    from core.report_builder import ReportBuilder
    from core.profile_loader import Profile

    profile = Profile(id="dongrou", name="冬柔", role="dps", spec="冰法",
                      persona_style="qingxin")
    builder = ReportBuilder(profile, output_dir=Path("data/cache"))
    header = builder.build_header(meta)

输入:
    data/cache/m2_meta_{code}.txt
    data/cache/m2_group_b_{code}.txt
    data/xiaoxue/qingxin_benchmark_profile.json
    data/xiaoxue/progress.db

输出:
    data/cache/m2_xiaoxue_skeleton_{code}.md
"""

import json
import sys
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any

from core.report_skeleton import load_meta, load_group_b, format_num

# ── 路径 ──────────────────────────────────────────────────────────
PROJECT_DIR = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_DIR / "data" / "cache"
XIAOXUE_DIR = PROJECT_DIR / "data" / "xiaoxue"
BENCHMARK_PATH = XIAOXUE_DIR / "qingxin_benchmark_profile.json"
TEMPLATE_PATH = PROJECT_DIR / "templates" / "xiaoxue-coaching-template.md"

# 冰法核心技能 (spell_id → 中文名)
FROST_MAGE_CORE_SKILLS: dict[int, str] = {
    30455: "冰枪术",
    116: "寒冰箭",
    153595: "彗星风暴",
    84721: "冰风暴",
    190356: "暴风雪",
    12472: "冰冷血脉",
    84714: "寒冰宝珠",
    228597: "冰霜射线",
}


# ═══════════════════════════════════════════════════════════════════
# 数据加载
# ═══════════════════════════════════════════════════════════════════


def load_qingxin_benchmark() -> dict:
    """加载清心基准 JSON。"""
    if not BENCHMARK_PATH.exists():
        print(f"警告: 清心基准文件不存在: {BENCHMARK_PATH}", file=sys.stderr)
        return {}
    with open(BENCHMARK_PATH, encoding="utf-8") as f:
        return json.load(f)


def load_previous_report() -> dict | None:
    """加载上周报告的数据（从 progress.db 取最近第二份快照）。"""
    from core.xiaoxue_tracker import get_latest

    rows = get_latest(count=2)
    if len(rows) >= 2:
        return rows[1]
    return None


def load_inputs(report_code: str) -> dict[str, Any]:
    """加载所有输入文件，返回结构化数据 dict。"""
    meta_path = CACHE_DIR / f"m2_meta_{report_code}.txt"
    gb_path = CACHE_DIR / f"m2_group_b_{report_code}.txt"

    meta = load_meta(str(meta_path))
    gb = load_group_b(str(gb_path))
    bm = load_qingxin_benchmark()
    prev = load_previous_report()

    return {"meta": meta, "group_b": gb, "benchmark": bm, "previous": prev}


# ═══════════════════════════════════════════════════════════════════
# 优先级判定
# ═══════════════════════════════════════════════════════════════════


def detect_priority(
    skill_name: str,
    ours: dict | None,
    tops: dict | None,
    deaths: int = 0,
    vs_ratio: float = 1.0,
) -> str:
    """自动判定改进项优先级 (P0/P1/P2)。

    P0: 核心技能缺失 / 死亡 ≥ 3 / DPS 差距 > 50%
    P1: 核心技能占比差 > 5% / 施法次数 < 顶层 70%
    P2: 其他辅助差距
    """
    # P0: 死亡过多
    if deaths >= 3:
        return "P0"

    # P0: DPS 差距过大
    if vs_ratio < 0.5:
        return "P0"

    # P0: 核心技能完全缺失
    if ours is None and tops is not None:
        for sid, name in FROST_MAGE_CORE_SKILLS.items():
            if name == skill_name:
                return "P0"

    if ours is None or tops is None:
        return "P2"

    # P1: 核心技能占比差 > 5%
    pct_diff = abs(ours.get("pct", 0) - tops.get("pct", 0))
    for sid, name in FROST_MAGE_CORE_SKILLS.items():
        if name == skill_name and pct_diff > 5:
            return "P1"

    # P1: 施法利用率不足
    tops_hits = tops.get("hits", 0)
    if tops_hits > 0 and ours.get("hits", 0) < tops_hits * 0.7:
        return "P1"

    return "P2"


# ═══════════════════════════════════════════════════════════════════
# 表格生成
# ═══════════════════════════════════════════════════════════════════


def build_weekly_overview(
    meta: dict,
    gb: dict,
    bm_dps: float,
    bm_deaths: int,
    bm_interrupts: int,
    bm_level: int,
    current_snapshot: dict,
    previous_snapshot: dict | None,
) -> str:
    """生成本周总览表格。"""
    xiaoxue = _find_ice_mage(meta)
    if xiaoxue is None:
        return "(未找到冰法玩家)"

    dps = xiaoxue.get("dps", 0) or 0
    deaths = sum(1 for d in gb.get("deaths", []) if d["player"] == xiaoxue["name"])
    interrupts = gb.get("interrupts", {}).get(xiaoxue["name"], 0)

    def _weekly(val, key, prev):
        if prev is None:
            return "-"
        prev_val = prev.get(key, val)
        diff = val - prev_val
        if diff > 0:
            return f"↑{diff}"
        elif diff < 0:
            return f"↓{abs(diff)}"
        return "→"

    lines = [
        "| 指标 | 小雪 | 清心基准 (+{}) | 差距 | vs 上周 |".format(bm_level),
        "|------|------|-----------------|------|---------|",
    ]

    dps_diff_val = dps - bm_dps
    dps_diff_str = format_num(abs(dps_diff_val))
    if dps_diff_val < 0:
        dps_diff_str = "-" + dps_diff_str
    dps_pct = (dps / bm_dps - 1) * 100 if bm_dps else 0
    lines.append(
        f"| DPS | {format_num(dps)} | {format_num(bm_dps)} | "
        f"{dps_diff_str} ({dps_pct:+.1f}%) | "
        f"{_weekly(dps, 'dps', previous_snapshot)} |"
    )

    death_diff = deaths - bm_deaths
    death_diff_str = f"+{death_diff}" if death_diff > 0 else str(death_diff)
    lines.append(
        f"| 死亡 | {deaths} | {bm_deaths} | {death_diff_str} | "
        f"{_weekly(deaths, 'deaths', previous_snapshot)} |"
    )

    int_diff = interrupts - bm_interrupts
    int_diff_str = f"+{int_diff}" if int_diff > 0 else str(int_diff)
    lines.append(
        f"| 打断 | {interrupts} | {bm_interrupts} | {int_diff_str} | "
        f"{_weekly(interrupts, 'interrupts', previous_snapshot)} |"
    )

    return "\n".join(lines)


def build_skill_assessment(xiaoxue_abilities: dict, qingxin_abilities: dict) -> str:
    """生成技能使用评估对比表。"""
    all_skills = set(list(xiaoxue_abilities.keys()) + list(qingxin_abilities.keys()))
    if not all_skills:
        return "(无技能数据)"

    lines = [
        "| 技能 | 小雪占比 | 小雪施法 | 清心占比 | 清心施法 | 差距 | 评级 |",
        "|------|---------|---------|---------|---------|------|------|",
    ]

    sorted_skills = sorted(
        all_skills,
        key=lambda s: xiaoxue_abilities.get(s, {}).get("pct", 0),
        reverse=True,
    )

    for skill_name in sorted_skills:
        ours = xiaoxue_abilities.get(skill_name, {"pct": 0, "hits": 0})
        tops = qingxin_abilities.get(skill_name, {"pct": 0, "hits": 0})
        pct_diff = ours["pct"] - tops["pct"]
        hits_diff = ours["hits"] - tops["hits"]

        lines.append(
            f"| {skill_name} | {ours['pct']:.1f}% | {ours['hits']} | "
            f"{tops['pct']:.1f}% | {tops['hits']} | "
            f"{pct_diff:+.1f}% / {hits_diff:+d} | {_rating(pct_diff)} |"
        )

    return "\n".join(lines)


def build_death_timeline(gb: dict, xiaoxue_name: str) -> str:
    """生成小雪死亡时间线（仅小雪的死亡事件）。"""
    deaths = [d for d in gb.get("deaths", []) if d["player"] == xiaoxue_name]
    if not deaths:
        return "本周零死亡 🎉"

    lines = ["| 时间 | 致死技能 | 来源 | 阶段 |", "|------|---------|------|------|"]
    for d in deaths:
        source_icon = "❓" if d.get("source", "?") == "?" else ""
        lines.append(
            f"| {d['time_sec']}s | {d['ability']} | {d['source']} {source_icon}| {d.get('phase', '-')} |"
        )
    return "\n".join(lines)


def build_milestone_progress(milestones: dict[str, bool]) -> str:
    """格式化里程碑进度条。"""
    if not milestones:
        return "(暂无数据)"
    lines = []
    desc_map = {
        "萌新出村": "首次完成 M0+",
        "蓝分入门": "vs 清心差距 ≤30%",
        "紫分进阶": "vs 清心差距 ≤15%",
        "橙分法神": "vs 清心差距 ≤5%",
    }
    for name, achieved in milestones.items():
        icon = "✅" if achieved else "⬜"
        desc = desc_map.get(name, "")
        lines.append(f"{icon} **{name}**: {desc}")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════
# 候选生成
# ═══════════════════════════════════════════════════════════════════


def generate_issues(
    meta: dict,
    gb: dict,
    xiaoxue_abilities: dict,
    qingxin_abilities: dict,
) -> list[dict]:
    """生成改进项候选列表（按优先级排序）。"""
    issues = []
    xiaoxue = _find_ice_mage(meta)
    if xiaoxue is None:
        return issues

    deaths = sum(1 for d in gb.get("deaths", []) if d["player"] == xiaoxue["name"])

    all_skills = set(list(xiaoxue_abilities.keys()) + list(qingxin_abilities.keys()))
    for skill_name in all_skills:
        ours = xiaoxue_abilities.get(skill_name)
        tops = qingxin_abilities.get(skill_name)

        if ours is None and tops is not None:
            pct_diff = tops["pct"]
            hits_diff = tops["hits"]
        elif ours is not None and tops is not None:
            pct_diff = tops["pct"] - ours["pct"]
            hits_diff = tops["hits"] - ours["hits"]
        else:
            continue

        if abs(pct_diff) < 1.0 and abs(hits_diff) < 2:
            continue

        priority = detect_priority(skill_name, ours, tops, deaths, 0.8)

        issues.append({
            "skill": skill_name,
            "our_pct": ours["pct"] if ours else 0,
            "top_pct": tops["pct"] if tops else 0,
            "pct_diff": round(pct_diff, 1),
            "our_hits": ours["hits"] if ours else 0,
            "top_hits": tops["hits"] if tops else 0,
            "hits_diff": hits_diff,
            "priority": priority,
        })

    priority_order = {"P0": 0, "P1": 1, "P2": 2}
    issues.sort(key=lambda x: (priority_order.get(x["priority"], 99), -abs(x["pct_diff"])))

    return issues


def _build_highlights(issues: list[dict], gb: dict, xiaoxue_name: str) -> str:
    """从差距数据中提取亮点候选。"""
    highlights = []

    close_skills = [i for i in issues if abs(i["pct_diff"]) <= 2.0 and i["priority"] == "P2"]
    if close_skills:
        names = ", ".join(i["skill"] for i in close_skills[:3])
        highlights.append(f"- {names} 占比与清心基准接近，继续保持")

    xiaoxue_deaths = sum(1 for d in gb.get("deaths", []) if d["player"] == xiaoxue_name)
    if xiaoxue_deaths == 0:
        highlights.append("- 本周零死亡，生存表现优秀")
    elif xiaoxue_deaths == 1:
        highlights.append("- 仅死亡 1 次，整体生存情况良好")

    int_count = gb.get("interrupts", {}).get(xiaoxue_name, 0)
    if int_count >= 10:
        highlights.append(f"- 打断 {int_count} 次，积极履行职能")

    return "\n".join(highlights) if highlights else "(等待模型评估)"


# ═══════════════════════════════════════════════════════════════════
# 辅助
# ═══════════════════════════════════════════════════════════════════


def _find_ice_mage(meta: dict) -> dict | None:
    """在 meta 的 players 中找冰法玩家。"""
    for p in meta.get("players", []):
        if p["spec"] == "Frost" and p["class"] == "Mage":
            return p
    # fallback: 专精可能是中文名
    for p in meta.get("players", []):
        if "Frost" in str(p.get("spec", "")) or "冰" in str(p.get("spec_cn", "")):
            if "Mage" in str(p.get("class", "")) or "法师" in str(p.get("class", "")):
                return p
    return None


def _rating(diff: float) -> str:
    """根据占比差距返回评级。"""
    if diff >= 0:
        return "A"
    if diff >= -3:
        return "B"
    if diff >= -5:
        return "C"
    return "D"


# ═══════════════════════════════════════════════════════════════════
# 骨架组装
# ═══════════════════════════════════════════════════════════════════


def build_skeleton(report_code: str) -> str:
    """[DEPRECATED] 组装完整骨架。请使用 core.report_builder.ReportBuilder。"""
    warnings.warn(
        "[DEPRECATED] xiaoxue_report_builder 已弃用，请使用 core.report_builder.ReportBuilder",
        DeprecationWarning,
        stacklevel=2,
    )
    inputs = load_inputs(report_code)
    meta = inputs["meta"]
    gb = inputs["group_b"]
    bm = inputs["benchmark"]
    prev = inputs["previous"]

    if not TEMPLATE_PATH.exists():
        print(f"错误: 模板文件不存在: {TEMPLATE_PATH}", file=sys.stderr)
        sys.exit(1)

    template = TEMPLATE_PATH.read_text(encoding="utf-8")

    xiaoxue = _find_ice_mage(meta)
    if xiaoxue is None:
        print("错误: meta 中未找到冰法玩家", file=sys.stderr)
        # 用第一个玩家尝试
        if meta.get("players"):
            xiaoxue = meta["players"][0]
            print(f"警告: 回退到第一位玩家: {xiaoxue['name']}", file=sys.stderr)
        else:
            sys.exit(1)

    # 从 progress.db 取最新快照
    from core.xiaoxue_tracker import get_latest, check_milestones, ascii_trend_chart

    latest = get_latest(count=1)
    current_snap = latest[0] if latest else {}

    # 快照中没有时，从 meta/gb 提取
    xiaoxue_abilities = current_snap.get("ability_pcts", {})
    ms = check_milestones(current_snap) if current_snap else {}

    # 从基准获取真实数据
    bm_skills = bm.get("skill_composition", {})
    bm_level = bm.get("source_report", {}).get("level", 12)
    bm_duration_ms = bm.get("source_report", {}).get("keystone_time_ms", 0)
    bm_total_damage = bm.get("source_report", {}).get("total_damage", 0)
    if bm_total_damage > 0 and bm_duration_ms > 0:
        bm_total_time_dps = int(bm_total_damage / (bm_duration_ms / 1000))
    else:
        bm_total_time_dps = bm.get("dps", 120000 + (bm_level - 10) * 5000 if bm_level > 0 else 120000)

    # ── 填入模板 ──
    result = template
    result = result.replace("{dungeon}", meta.get("dungeon_cn", "未知"))
    result = result.replace("{level}", str(meta.get("level", "?")))
    result = result.replace(
        "{timed_status}",
        "✅ 限时" if meta.get("timed") else "❌ 超时",
    )
    result = result.replace("{complete_time}", meta.get("complete_time", "?"))
    result = result.replace("{date}", datetime.now().strftime("%Y-%m-%d %H:%M"))

    result = result.replace("{benchmark_level}", str(bm_level))

    dps = xiaoxue.get("dps", 0) or 0
    # 修正为全程DPS（WCL显示风格）：总伤 / keystone_time
    # meta 不含玩家级 damage_total，需从 DB 读取
    db_path = PROJECT_DIR / "data" / "wcl_db" / f"{report_code}.db"
    if db_path.exists():
        import sqlite3
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        player_row = conn.execute(
            "SELECT p.damage_total, f.keystone_time FROM player p "
            "JOIN fight f ON f.report_code = (SELECT report_code FROM report LIMIT 1) "
            "WHERE p.class='Mage' AND p.spec='Frost' LIMIT 1"
        ).fetchone()
        if player_row and player_row["damage_total"] and player_row["keystone_time"]:
            total_dmg = player_row["damage_total"]
            keystone_sec = player_row["keystone_time"] / 1000
            dps = int(total_dmg / keystone_sec)
        conn.close()
    deaths = sum(1 for d in gb.get("deaths", []) if d["player"] == xiaoxue["name"])
    interrupts = gb.get("interrupts", {}).get(xiaoxue["name"], 0)

    # DPS 行
    result = result.replace("{dps}", format_num(dps))
    result = result.replace("{benchmark_dps}", format_num(bm_total_time_dps))
    dps_diff = dps - bm_total_time_dps
    dps_diff_str = format_num(abs(dps_diff))
    if dps_diff < 0:
        dps_diff_str = "-" + dps_diff_str
    dps_pct = (dps / bm_total_time_dps - 1) * 100 if bm_total_time_dps else 0
    result = result.replace("{dps_diff}", f"{dps_diff_str} ({dps_pct:+.1f}%)")

    # 死亡行
    result = result.replace("{deaths}", str(deaths))
    result = result.replace("{benchmark_deaths}", str(bm.get("deaths", 0)))
    death_diff = deaths - bm.get("deaths", 0)
    result = result.replace("{deaths_diff}", f"+{death_diff}" if death_diff > 0 else str(death_diff))

    # 打断行
    bm_interrupts = 12  # 从基准估算
    result = result.replace("{interrupts}", str(interrupts))
    result = result.replace("{benchmark_interrupts}", str(bm_interrupts))
    int_diff = interrupts - bm_interrupts
    result = result.replace("{int_diff}", f"+{int_diff}" if int_diff > 0 else str(int_diff))

    # 周环比
    if prev:
        result = result.replace("{dps_weekly}", _weekly_change(dps, prev.get("dps", 0)))
        result = result.replace(
            "{deaths_weekly}", _weekly_change(deaths, prev.get("deaths", 0))
        )
        result = result.replace(
            "{interrupts_weekly}", _weekly_change(interrupts, prev.get("interrupts", 0))
        )
    else:
        for key in ["dps_weekly", "deaths_weekly", "interrupts_weekly"]:
            result = result.replace(f"{{{key}}}", "-")

    # 技能评估表
    result = result.replace(
        "{skill_assessment_table}",
        build_skill_assessment(xiaoxue_abilities, bm_skills),
    )

    # 死亡时间线
    result = result.replace(
        "{death_timeline}",
        build_death_timeline(gb, xiaoxue["name"]),
    )

    # 改进项候选
    issues = generate_issues(meta, gb, xiaoxue_abilities, bm_skills)
    issues_text = "\n".join(
        f"- [{i['priority']}] **{i['skill']}**: 占比 {i['our_pct']}% vs "
        f"{i['top_pct']}%（差 {i['pct_diff']}%），"
        f"施法 {i['our_hits']} vs {i['top_hits']}（差 {i['hits_diff']}）"
        for i in issues[:8]
    )
    result = result.replace("{issues_candidates}", issues_text or "(无显著差距)")

    # 亮点
    result = result.replace(
        "{highlights_candidates}",
        _build_highlights(issues, gb, xiaoxue["name"]),
    )

    # 里程碑
    result = result.replace("{milestone_progress}", build_milestone_progress(ms))

    # 趋势图
    result = result.replace("{trend_chart}", ascii_trend_chart(metric="dps", count=6))

    # 周总览表已整体替换
    overview_table = build_weekly_overview(
        meta, gb, bm_total_time_dps, bm.get("deaths", 0), bm_interrupts,
        bm_level, current_snap, prev,
    )
    # 模板中 no placeholder for the full overview table yet (it's built in-line above)
    # The overview part is covered by the individual {{xxx}} placeholders

    result = result.replace("{generation_time}", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    # 写入
    output_path = CACHE_DIR / f"m2_xiaoxue_skeleton_{report_code}.md"
    output_path.write_text(result, encoding="utf-8")
    print(f"骨架已生成: {output_path}")
    print(f"占位符待填: DIAGNOSIS, DO_WELL_FINAL, IMPROVE_FINAL, "
          f"DEATH_ROOT_CAUSE, TRAINING_TASKS, COACH_NOTE")

    return result


def _weekly_change(current: float, previous: float) -> str:
    """格式化周环比变化。"""
    if not previous:
        return "-"
    diff = current - previous
    if diff > 0:
        return f"↑{diff}"
    elif diff < 0:
        return f"↓{abs(diff)}"
    return "→"


# ═══════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════


def main():
    import argparse

    parser = argparse.ArgumentParser(description="小雪指导报告骨架生成")
    parser.add_argument("report_code", help="小雪 WCL 报告代码")
    parser.add_argument("--output", "-o", help="输出路径（默认 data/cache/m2_xiaoxue_skeleton_{code}.md）")
    args = parser.parse_args()

    build_skeleton(args.report_code)


if __name__ == "__main__":
    main()
