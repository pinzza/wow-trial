#!/usr/bin/env python3
"""
从 comparison JSON 中提取 3 组"分析就绪"摘要（每组 2-5KB），
供 mplus-benchmark 的 delegate_task 子 Agent 直接消费。

Group A: 伤害构成 + 施法活跃度 + 冷却爆发
Group B: 死亡分析 + 路线对比 + 打断统计
Group C: Buff覆盖 + 资源循环

用法:
    python build_analysis_summaries.py comparison_xxx.json
"""

import json
import sys
from collections import Counter
from pathlib import Path

# ── 专精 → 角色判定 ──
TANK_SPECS = {"Protection", "Blood", "Vengeance", "Guardian", "Brewmaster"}
HEALER_SPECS = {"Restoration", "Preservation", "Mistweaver", "Holy", "Discipline"}

# ── zone_id → 副本名（12.0 Midnight；旧 TWW zone 47 也保留兼容）──
ZONE_NAMES = {
    "47": "萨隆矿坑 (TWW S1)",   # The War Within 兼容
    # Midnight 12.0 zones (待确认)
}


def build_player_spec_map(data):
    """从 comparison JSON 各章节收集 name → spec 映射"""
    spec_map = {}
    sections = ["damage_composition", "cast_activity", "cooldown_usage",
                "deaths_and_damage", "buff_coverage"]
    for sec_name in sections:
        sec = data.get(sec_name, {})
        for side in ["our", "top"]:
            for p in sec.get(f"{side}_players", []):
                name = p.get("name", "")
                spec = p.get("spec", "")
                if name and spec:
                    spec_map[name] = spec
    # dps_ratios 也补充
    for r in data.get("summary", {}).get("dps_ratios", []):
        if "our_player" in r:
            spec_map[r["our_player"]] = r["spec"]
        if "top_player" in r:
            spec_map[r["top_player"]] = r["spec"]
    return spec_map


def get_role(spec):
    """根据专精名判定角色：坦克/治疗/DPS"""
    if spec in TANK_SPECS:
        return "坦克"
    if spec in HEALER_SPECS:
        return "治疗"
    return "DPS"


def get_dungeon_name(zone_id):
    """zone_id → 副本名，未知时返回 zone_<id>"""
    return ZONE_NAMES.get(zone_id, f"zone_{zone_id}")


def collect_team_composition(data, side):
    """收集一方队伍的专精列表，返回 '(spec1/spec2/...) 格式'"""
    specs = []
    spec_map = build_player_spec_map(data)
    # 从 damage_composition 收集（最可靠）
    for p in data.get("damage_composition", {}).get(f"{side}_players", []):
        s = p.get("spec", "")
        if s:
            specs.append(s)
    if not specs:
        # fallback: 用 spec_map 中匹配 side 的玩家
        # 通过 dps_ratios 推断
        for r in data.get("summary", {}).get("dps_ratios", []):
            key = f"{side}_player"
            if key in r:
                specs.append(r["spec"])
    return "/".join(specs) if specs else "?"


def load_json(path):
    with open(path) as f:
        return json.load(f)


def find_player(section, side, name):
    players = section.get(f"{side}_players", [])
    return next((p for p in players if p["name"] == name), None)


def spell_label(our_name, top_name):
    """Return display label: 中文名(英文名) if different, else just 中文名"""
    if our_name != top_name:
        return f"{our_name}({top_name})"
    return our_name


def build_group_a(data):
    """伤害构成 + 施法活跃度 + 冷却爆发 — 用 spell_id 做跨语言匹配"""
    dc = data["damage_composition"]
    ca = data["cast_activity"]
    cu = data["cooldown_usage"]
    ssp = dc.get("same_spec_pairs", [])
    summary = data["summary"]

    lines = ["=== GROUP A: 伤害构成 + 施法活跃度 + 冷却爆发 ===\n"]
    # 动态副本+阵容信息
    meta = data.get("meta", {})
    zone_id = meta.get("our_zone", meta.get("top_zone", "?"))
    dungeon = get_dungeon_name(zone_id)
    our_comp = collect_team_composition(data, "our")
    top_comp = collect_team_composition(data, "top")
    lines.append(f"{dungeon} | 我方: {our_comp} | 顶层: {top_comp}")

    # DPS ratio overview
    ratios = summary.get("dps_ratios", [])
    if ratios:
        lines.append(f"\nDPS 比率总览 (整体={summary.get('overall_dps_ratio',0):.2f}):")
        for r in ratios:
            lines.append(f"  {r['spec']}: {r['our_dps']:.0f} vs {r['top_dps']:.0f} = {r['ratio']:.2f}")

    lines.append("")

    # --- Spec-paired: use spell_id for matching ---
    for pair in ssp:
        spec = pair["spec"]
        our_entry = pair.get("our") or {}
        top_entry = pair.get("top") or {}
        our_name = our_entry.get("name")
        top_name = top_entry.get("name")
        if not our_name or not top_name:
            continue

        our_dc = find_player(dc, "our", our_name)
        top_dc = find_player(dc, "top", top_name)
        our_cast = find_player(ca, "our", our_name)
        top_cast = find_player(ca, "top", top_name)
        our_cd = find_player(cu, "our", our_name)
        top_cd = find_player(cu, "top", top_name)

        lines.append(f"## {spec}: {our_name} vs {top_name}")

        # Damage composition — match by spell_id
        if our_dc and top_dc:
            our_dmg = our_dc["damage_total"]
            top_dmg = top_dc["damage_total"]
            lines.append(f"总伤: {our_dmg/1e6:.1f}M vs {top_dmg/1e6:.1f}M (ratio={our_dmg/top_dmg:.2f})")

            our_by_id = {a["spell_id"]: a for a in our_dc["top_abilities"]}
            top_by_id = {a["spell_id"]: a for a in top_dc["top_abilities"]}
            common_ids = set(our_by_id.keys()) & set(top_by_id.keys())
            our_only_ids = set(our_by_id.keys()) - common_ids
            top_only_ids = set(top_by_id.keys()) - common_ids

            lines.append(f"  {'技能':<28} {'我方%':>6} {'顶层%':>6} {'差':>6}")
            # Sort common by max pct
            sorted_common = sorted(common_ids, key=lambda sid: -max(our_by_id[sid]["pct"], top_by_id[sid]["pct"]))
            for sid in sorted_common:
                our_a = our_by_id[sid]
                top_a = top_by_id[sid]
                label = spell_label(our_a["name"], top_a["name"])
                diff = our_a["pct"] - top_a["pct"]
                lines.append(f"  {label:<28} {our_a['pct']:>5.1f}% {top_a['pct']:>5.1f}% {diff:>+5.1f}%")
            if our_only_ids:
                names = [our_by_id[sid]["name"] for sid in our_only_ids]
                lines.append(f"  仅我方: {', '.join(names)}")
            if top_only_ids:
                names = [top_by_id[sid]["name"] for sid in top_only_ids]
                lines.append(f"  仅顶层: {', '.join(names)}")

        # CPM
        if our_cast and top_cast:
            our_cpm = our_cast["cpm"]
            top_cpm = top_cast["cpm"]
            lines.append(f"CPM: {our_cpm:.1f} vs {top_cpm:.1f} (差={our_cpm-top_cpm:+.1f})")
            our_gaps = our_cast.get("long_gap_count")
            top_gaps = top_cast.get("long_gap_count")
            if isinstance(our_gaps, (int, float)) and isinstance(top_gaps, (int, float)):
                lines.append(f"  长间隔(>5s): {our_gaps}次 vs {top_gaps}次")

        # Cooldown abilities — match by spell_id
        if our_cd and top_cd:
            our_by_id = {a["spell_id"]: a for a in our_cd["all_abilities"]}
            top_by_id = {a["spell_id"]: a for a in top_cd["all_abilities"]}
            common_ids = set(our_by_id.keys()) & set(top_by_id.keys())
            our_only_ids = set(our_by_id.keys()) - common_ids
            top_only_ids = set(top_by_id.keys()) - common_ids

            # Only show abilities with actual casts on either side
            active = [(sid, our_by_id[sid]["cast_count"], top_by_id[sid]["cast_count"])
                      for sid in common_ids
                      if our_by_id[sid]["cast_count"] > 0 or top_by_id[sid]["cast_count"] > 0]
            active.sort(key=lambda x: -max(x[1], x[2]))

            if active:
                lines.append("技能施放 (我方vs顶层):")
                for sid, our_c, top_c in active:
                    label = spell_label(our_by_id[sid]["name"], top_by_id[sid]["name"])
                    # 标记 damage=0 的技能
                    our_dmg = our_by_id[sid].get("damage_amount", 0)
                    top_dmg = top_by_id[sid].get("damage_amount", 0)
                    flag = ""
                    if (our_c > 0 and our_dmg == 0) or (top_c > 0 and top_dmg == 0):
                        flag = " ⚠️伤害归属空缺"
                    lines.append(f"  {label:<28} {our_c:>5} vs {top_c:>5}{flag}")

                # ── 每击伤害 / 归属分析 ──
                # 对于次数差 ≥2x 或 伤害=0 的技能，补充上下文
                dmg_notes = []
                our_dc_by_id = {a["spell_id"]: a for a in (our_dc["top_abilities"] if our_dc else [])}
                top_dc_by_id = {a["spell_id"]: a for a in (top_dc["top_abilities"] if top_dc else [])}
                for sid, our_c, top_c in active:
                    our_dmg = our_by_id[sid].get("damage_amount", 0)
                    top_dmg = top_by_id[sid].get("damage_amount", 0)
                    if our_c > 0 and top_c > 0:
                        ratio_c = our_c / top_c
                        # 伤害占比（来自 damage_composition）
                        our_pct = our_dc_by_id.get(sid, {}).get("pct", 0)
                        top_pct = top_dc_by_id.get(sid, {}).get("pct", 0)
                        if our_pct > 0 and top_pct > 0 and ratio_c < 0.6:
                            ratio_pct = our_pct / top_pct
                            per_our = our_dmg / our_c if our_dmg > 0 else 0
                            per_top = top_dmg / top_c if top_dmg > 0 else 0
                            label = spell_label(our_by_id[sid]["name"], top_by_id[sid]["name"])
                            dmg_notes.append(
                                f"  * {label}: 施放次数比={ratio_c:.2f}, "
                                f"伤害占比比={ratio_pct:.2f}, "
                                f"每击={per_our/1000:.0f}K/{per_top/1000:.0f}K "
                                f"({'效率相近' if per_our > 0 and per_top > 0 and 0.7 < per_our/(per_top or 1) < 1.3 else '效率差异大'})"
                            )
                    # V1 归属空缺: cast>0 但 damage=0
                    if our_c > 0 and our_dmg == 0:
                        label = our_by_id[sid]["name"]
                        if label not in [n.split(":")[0].strip("* ") for n in dmg_notes]:
                            dmg_notes.append(f"  * {label}: {our_c}次施放, 伤害=0 (V1 API 伤害归属空缺)")
                    if top_c > 0 and top_dmg == 0:
                        label = top_by_id[sid]["name"]
                        key = f"{label}: {top_c}次施放, 伤害=0 (V1 API 伤害归属空缺)"
                        if not any(key in n for n in dmg_notes):
                            dmg_notes.append(f"  * {label}: {top_c}次施放, 伤害=0 (V1 API 伤害归属空缺)")
                if dmg_notes:
                    lines.append("\n施放次数 vs 伤害占比 深度分析:")
                    for note in dmg_notes:
                        lines.append(note)

            # Auto-cast (both 0)
            zero = [(sid, our_by_id[sid]["name"]) for sid in common_ids
                    if our_by_id[sid]["cast_count"] == 0 and top_by_id[sid]["cast_count"] == 0]
            if zero:
                names = [spell_label(n, top_by_id[sid]["name"]) for sid, n in zero]
                lines.append(f"  [自动触发/pet技能, cast=0: {', '.join(names[:5])}]")

            if our_only_ids:
                names = [our_by_id[sid]["name"] for sid in our_only_ids]
                lines.append(f"  仅我方: {', '.join(names)}")
            if top_only_ids:
                names = [top_by_id[sid]["name"] for sid in top_only_ids]
                lines.append(f"  仅顶层: {', '.join(names)}")

        lines.append("")

    # --- Non-matched specs ---
    matched_our = set()
    matched_top = set()
    for pair in ssp:
        o = (pair.get("our") or {}).get("name")
        t = (pair.get("top") or {}).get("name")
        if o:
            matched_our.add(o)
        if t:
            matched_top.add(t)

    unmatched_our = [p for p in cu.get("our_players", []) if p["name"] not in matched_our]
    unmatched_top = [p for p in cu.get("top_players", []) if p["name"] not in matched_top]

    if unmatched_our or unmatched_top:
        lines.append("## 未匹配专精 (阵容差异)\n")
        for side_key, side_label, players in [
            ("our_players", "我方", unmatched_our),
            ("top_players", "顶层", unmatched_top),
        ]:
            for p in players:
                dc_p = find_player(dc, "our" if side_label == "我方" else "top", p["name"])
                cast_p = find_player(ca, "our" if side_label == "我方" else "top", p["name"])
                dmg = dc_p["damage_total"] / 1e6 if dc_p else 0
                cpm_val = cast_p["cpm"] if cast_p else "N/A"
                ab_strs = [f"{a['name']}({a['cast_count']})" for a in p["all_abilities"]]
                lines.append(f"  [{side_label}] {p['spec']} {p['name']}: 总伤={dmg:.1f}M CPM={cpm_val}")
                lines.append(f"    技能: {', '.join(ab_strs)}")
        lines.append("")

    return "\n".join(lines)


# ── 打断技能分类（spell_id → 施法者类型 / 职责说明）──
# BOSS: BOSS 专属技能，仅在有限战斗窗口内可打断，是大优先级
# RANGED: 远程单位施法，近战打断属于额外贡献（不是主要责任）
# GENERIC: 小怪通用读条，全员有责
INTERRUPT_SPELL_INFO = {
    1278893: {"label": "湮灭之箭", "caster": "Ick (2号BOSS)", "type": "BOSS", "note": "远程BOSS技能，近战打断属紧急补救"},
    1258431: {"label": "暗影箭", "caster": "小怪/通灵师", "type": "GENERIC", "note": ""},
    1258436: {"label": "冰霜箭", "caster": "小怪/法师", "type": "GENERIC", "note": ""},
    1271479: {"label": "虚空爆发", "caster": "小怪", "type": "GENERIC", "note": ""},
    1271074: {"label": "寒冰冲击", "caster": "小怪", "type": "GENERIC", "note": ""},
    1264186: {"label": "暗影束缚", "caster": "小怪", "type": "GENERIC", "note": ""},
    1262941: {"label": "瘟疫箭", "caster": "小怪", "type": "GENERIC", "note": ""},
    1258997: {"label": "猛拽掌握", "caster": "小怪", "type": "GENERIC", "note": "近战范围"},
}
def build_group_b(data):
    """死亡分析 + 路线对比 + 打断统计"""
    dd = data["deaths_and_damage"]
    rt = data["route_timeline"]
    dc = data["damage_composition"]
    spec_map = build_player_spec_map(data)

    lines = ["=== GROUP B: 死亡分析 + 路线对比 + 打断统计 ===\n"]
    lines.append("V1 API 限制: pre_death_damage_5s 不可用\n")

    # Deaths
    our_deaths = dd["our"]["deaths"]
    top_deaths = dd["top"]["deaths"]

    lines.append(f"## 我方: {len(our_deaths)} 次死亡")
    lines.append(f"  {'时间':>6} {'玩家':<16} {'专精':<14} {'致死技能':<22} {'角色':<6}")
    for d in our_deaths:
        killing = d.get("killing_ability") or "?"
        player = d["player"]
        spec = spec_map.get(player, "?")
        role = get_role(spec)
        lines.append(f"  {d['relative_sec']:>5.0f}s {player:<16} {spec:<14} {killing:<22} {role:<6}")

    # Death clusters with root cause hints
    clusters = []
    current = []
    for d in our_deaths:
        if not current or d["relative_sec"] - current[-1]["relative_sec"] < 15:
            current.append(d)
        else:
            if len(current) >= 2:
                clusters.append(current)
            current = [d]
    if len(current) >= 2:
        clusters.append(current)

    if clusters:
        lines.append("\n死亡集群分析:")
        for i, cl in enumerate(clusters):
            t_range = f"{cl[0]['relative_sec']:.0f}-{cl[-1]['relative_sec']:.0f}s"
            names = [d["player"] for d in cl]
            kills = [d.get("killing_ability", "?") for d in cl]
            lines.append(f"  集群{i+1} @{t_range}: {', '.join(names)}")
            lines.append(f"    致死: {', '.join(kills)}")
            has_tank = any(get_role(spec_map.get(d["player"], "")) == "坦克" for d in cl)
            has_healer = any(get_role(spec_map.get(d["player"], "")) == "治疗" for d in cl)
            if has_tank and len(cl) >= 3:
                lines.append(f"    → 根因推测: 坦克先倒 → 连锁减员, 检查坦克减伤覆盖/治疗响应")
            elif has_tank and len(cl) == 2:
                lines.append(f"    → 根因推测: 坦克倒后近战DPS被顺劈, 检查坦克减伤/走位")
            elif has_healer:
                lines.append(f"    → 根因推测: 治疗死亡 → 团队断奶, 检查治疗站位/自保")

    # Death statistics — 基于专精判定角色
    tank_deaths = sum(1 for d in our_deaths if get_role(spec_map.get(d["player"], "")) == "坦克")
    healer_deaths = sum(1 for d in our_deaths if get_role(spec_map.get(d["player"], "")) == "治疗")
    dps_deaths = len(our_deaths) - tank_deaths - healer_deaths
    lines.append(f"\n死亡统计: 坦克{tank_deaths}次 治疗{healer_deaths}次 DPS{dps_deaths}次")
    lines.append(f"  时间惩罚估算: {len(our_deaths)*15}s (每次死亡≈15s跑尸/复活)")
    lines.append(f"  非战斗时间占比: {len(our_deaths)*15/(data['summary']['our']['total_duration_sec'])*100:.0f}%")
    # Per-player
    death_counts = Counter(d["player"] for d in our_deaths)
    lines.append(f"  按玩家: " + ", ".join(f"{p}:{c}" for p,c in death_counts.most_common()))

    lines.append(f"\n## 顶层: {len(top_deaths)} 次死亡")
    for d in top_deaths:
        lines.append(f"  {d['relative_sec']:.0f}s {d['player']} - {d.get('killing_ability','?')}")

    # Route
    lines.append(f"\n## 路线")
    lines.append(f"BOSS顺序匹配: {rt.get('boss_order_match', False)}")
    lines.append(f"我方 {len(rt['our'])}场战斗/{data['summary']['our']['total_duration_sec']:.0f}s (多副本聚合)")
    lines.append(f"顶层 {len(rt['top'])}场战斗/{data['summary']['top']['total_duration_sec']:.0f}s (单副本)")
    lines.append("⚠️ 我方多副本聚合, 路线对比不做深度分析")

    # ── 阵容差异检测（用于打断可比性判断）──
    our_specs = set()
    top_specs = set()
    for p in dc.get("our_players", []):
        our_specs.add(p.get("spec", ""))
    for p in dc.get("top_players", []):
        top_specs.add(p.get("spec", ""))
    spec_diff_note = ""
    if our_specs != top_specs:
        only_us = our_specs - top_specs
        only_top = top_specs - our_specs
        parts = []
        if only_us:
            parts.append(f"我方独有: {', '.join(sorted(only_us))}")
        if only_top:
            parts.append(f"顶层独有: {', '.join(sorted(only_top))}")
        spec_diff_note = "; ".join(parts)

    # Interrupts — 按技能分类展示
    our_intr = dd["our"].get("interrupts", {})
    top_intr = dd["top"].get("interrupts", {})

    lines.append(f"\n## 打断")
    if our_intr.get("available"):
        lines.append(f"我方: {our_intr.get('total', 0)}次")
        if spec_diff_note:
            lines.append(f"  ⚠️ 阵容差异: {spec_diff_note} — 打断总数不可直接对比")
        for e in our_intr.get("by_player", []):
            lines.append(f"  {e['player']}: {e['count']}")
        # 按 spell_id 分类打断目标
        lines.append("\n打断技能分布:")
        boss_interrupts = []
        generic_interrupts = []
        for ab in our_intr.get("by_ability", []):
            sid = ab.get("spell_id", 0)
            info = INTERRUPT_SPELL_INFO.get(sid, {})
            label = info.get("label", ab.get("ability_name", "?"))
            note = info.get("note", "")
            caster = info.get("caster", "")
            count = ab.get("count", 0)
            line = f"  {label}: {count}次"
            if caster:
                line += f" ({caster})"
            if note:
                line += f" — {note}"
            if info.get("type") == "BOSS":
                boss_interrupts.append(line)
            else:
                generic_interrupts.append(line)
        if boss_interrupts:
            lines.append("  [BOSS 专属技能 — 仅在特定战斗窗口可打断]")
            for l in boss_interrupts:
                lines.append(l)
        if generic_interrupts:
            lines.append("  [小怪通用技能 — 全程出现，全员有责]")
            for l in generic_interrupts:
                lines.append(l)
        lines.append("\n  ⚠️ 注意: BOSS远程技能(如湮灭之箭)由远离本体的单位施放，")
        lines.append("     近战职业难以参与打断。若近战参与了此类打断 → 应视为亮点/紧急补救。")
        lines.append("     报告分析时不应将此类技能的打断缺口归责于近战职业。")

    if top_intr.get("available"):
        lines.append(f"\n顶层: {top_intr.get('total', 0)}次")
        for e in top_intr.get("by_player", []):
            lines.append(f"  {e['player']}: {e['count']}")

    return "\n".join(lines)


# ── 关键职业 Buff（spell_id → 中文名）──
# 这些 Buff 是专精核心机制，无论 diff 大小都应出现在对比中
CLASS_SIGNATURE_BUFFS = {
    "Arms":          [(260708, "横扫攻击"), (440989, "巨人神力"), (1269394, "战争大师")],
    "Fury":          [(184362, "激怒"), (262232, "战争机器")],
    "Protection":    [(132403, "正义盾击"), (190456, "无视苦痛")],
    "Shadow":        [(232698, "暗影形态"), (390978, "命运多舛"), (194249, "虚空形态")],
    "Demonology":    [(108366, "灵魂榨取"), (387552, "狱火统御")],
    "Retribution":   [(31884, "复仇之怒"), (431536, "倾天圣威")],
    "Restoration":   [(61295, "激流"), (207400, "先祖活力")],
    "Brewmaster":    [(215479, "醉拳"), (195630, "飘渺酒")],
    "Feral":         [(768, "猎豹形态"), (5217, "猛虎之怒")],
}
def build_group_c(data):
    """Buff覆盖 + 资源循环"""
    bc = data["buff_coverage"]
    rc = data.get("resource_cycling", {})

    lines = ["=== GROUP C: Buff覆盖 + 资源循环 ===\n"]

    # Resource
    lines.append("## 资源循环")
    lines.append(f"可用: {rc.get('available', False)} — {rc.get('note', 'V1 API 限制')}")

    # Buff
    lines.append(f"\n## Buff覆盖 (V1 限制: 队伍级数据)")
    lines.append(f"可用性: {bc.get('available')}")

    if bc.get("available"):
        lines.append("\n### 我方团队 Buff (非消耗品, 3-99%)")
        our_auras = {}
        for p in bc.get("our_players", []):
            for a in p.get("auras", []):
                name = a["name"]
                upt = a.get("uptime_pct", 0)
                if 3.0 < upt < 99.0:
                    our_auras[name] = max(our_auras.get(name, 0), upt)
        for name, upt in sorted(our_auras.items(), key=lambda x: -x[1])[:8]:
            lines.append(f"  {name}: {upt:.1f}%")

        lines.append("\n### 顶层团队 Buff")
        top_auras = {}
        for p in bc.get("top_players", []):
            for a in p.get("auras", []):
                name = a["name"]
                upt = a.get("uptime_pct", 0)
                if 3.0 < upt < 99.0:
                    top_auras[name] = max(top_auras.get(name, 0), upt)
        for name, upt in sorted(top_auras.items(), key=lambda x: -x[1])[:8]:
            lines.append(f"  {name}: {upt:.1f}%")

        # Same-spec buff diffs — format as readable table
        diff = bc.get("same_spec_buff_diff", [])
        if diff:
            lines.append(f"\n### 同专精 Buff 差异 ({len(diff)} 对)")
            lines.append(f"  {'专精':<14} {'Buff':<22} {'我方%':>6} {'顶层%':>6}")
            for entry in diff:
                spec = entry.get("spec", "?")
                for d in entry.get("top_diffs", [])[:5]:
                    aura = d.get("aura_name", "?")
                    our_p = d.get("our_pct", 0)
                    top_p = d.get("top_pct", 0)
                    lines.append(f"  {spec:<14} {aura:<22} {our_p:>5.0f}% {top_p:>5.0f}%")

        # ── 关键职业 Buff 强制展示（无论 diff 排名如何）──
        # 从 diff 数据中查找 CLASS_SIGNATURE_BUFFS 里定义的 buff，
        # 始终展示，确保横扫攻击/暗影形态等核心机制不会被挤出视线。
        key_buffs_found = []
        for entry in diff:
            spec = entry.get("spec", "?")
            targets = CLASS_SIGNATURE_BUFFS.get(spec, [])
            if not targets:
                continue
            our_name = entry.get("our_player", "?")
            top_name = entry.get("top_player", "?")
            # 从 entry 的所有 diffs 中查找目标 spell_ids
            for d in entry.get("top_diffs", []):
                sid = d.get("spell_id", 0)
                for target_sid, cn_name in targets:
                    if sid == target_sid:
                        our_p = d.get("our_pct", 0)
                        top_p = d.get("top_pct", 0)
                        key_buffs_found.append({
                            "spec": spec, "aura": cn_name,
                            "our": our_p, "top": top_p,
                            "our_player": our_name, "top_player": top_name,
                        })
        if key_buffs_found:
            lines.append(f"\n### 🔑 关键职业 Buff 对比（{len(key_buffs_found)} 项，强制展示）")
            lines.append(f"  {'专精':<14} {'Buff':<22} {'我方%':>6} {'顶层%':>6} {'差距':>6}")
            for kb in key_buffs_found:
                gap = kb["our"] - kb["top"]
                lines.append(f"  {kb['spec']:<14} {kb['aura']:<22} {kb['our']:>5.1f}% {kb['top']:>5.1f}% {gap:>+5.1f}%")
            # 如果某个目标 buff 完全没有出现（双方覆盖都为0），也标注
            for spec, targets in CLASS_SIGNATURE_BUFFS.items():
                matched_sids = {kb["aura"] for kb in key_buffs_found if kb["spec"] == spec}
                for sid, cn_name in targets:
                    if cn_name not in matched_sids:
                        # 检查是否在 diff 数据中存在对应的 spec entry
                        spec_entry = next((e for e in diff if e.get("spec") == spec), None)
                        if spec_entry:
                            lines.append(f"  {spec:<14} {cn_name:<22}    N/A    N/A  (数据缺失)")

    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        json_path = "/home/code/wow-trial/comparison_2MvpNR4fqQkznaCT_v2.json"
    else:
        json_path = sys.argv[1]

    data = load_json(json_path)

    cache_dir = Path("/home/code/wow-trial/data/cache")
    cache_dir.mkdir(parents=True, exist_ok=True)

    groups = {
        "group_a": build_group_a(data),
        "group_b": build_group_b(data),
        "group_c": build_group_c(data),
    }

    for name, content in groups.items():
        path = cache_dir / f"{name}_summary.txt"
        path.write_text(content, encoding="utf-8")
        print(f"[{name}] {len(content)} chars ({len(content)/1024:.1f} KB) → {path}")

    total = sum(len(c) for c in groups.values())
    print(f"\n总计: {total} chars ({total/1024:.1f} KB)")


if __name__ == "__main__":
    main()
