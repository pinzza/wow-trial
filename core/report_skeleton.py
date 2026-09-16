#!/usr/bin/env python3
"""
core/report_skeleton.py — M2 报告骨架预生成

读取 data/cache/ 下的 per_spec_benchmarks.json + 4 个 txt，输出预填充 Markdown
报告骨架，模型只需替换 7 个占位符即可完成最终报告。

用法:
    PYTHONPATH=. python3 core/report_skeleton.py <report_code>
示例:
    PYTHONPATH=. python3 core/report_skeleton.py gkNF6VHnWY3tLamT

输出: data/cache/m2_skeleton.md
"""

import argparse
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from core.spell_cn_map import resolve as spell_cn_resolve

# ── 路径 ──────────────────────────────────────────────────────────────
CACHE_DIR = Path("data/cache")
OUTPUT_PATH = Path("data/cache/m2_skeleton.md")
INPUT_FILES = {
    "benchmarks": CACHE_DIR / "per_spec_benchmarks.json",
    "meta": CACHE_DIR / "m2_meta.txt",
    "group_a": CACHE_DIR / "m2_group_a.txt",
    "group_b": CACHE_DIR / "m2_group_b.txt",
    "group_c": CACHE_DIR / "m2_group_c.txt",
}


# ── 专精中文映射 ──────────────────────────────────────────────────────
SPEC_CN: dict[str, str] = {
    "Protection": "防护", "Holy": "神圣", "Retribution": "惩戒",
    "Arms": "武器", "Fury": "狂怒",
    "Blood": "鲜血", "Frost": "冰霜", "Unholy": "邪恶",
    "Havoc": "浩劫", "Vengeance": "复仇",
    "Balance": "平衡", "Feral": "野性", "Guardian": "守护",
    "Restoration": "恢复",
    "Beast Mastery": "野兽控制", "Marksmanship": "射击", "Survival": "生存",
    "Arcane": "奥术", "Fire": "火焰",
    "Brewmaster": "酒仙", "Windwalker": "踏风", "Mistweaver": "织雾",
    "Discipline": "戒律", "Shadow": "暗影",
    "Assassination": "奇袭", "Outlaw": "狂徒", "Subtlety": "敏锐",
    "Elemental": "元素", "Enhancement": "增强",
    "Affliction": "痛苦", "Demonology": "恶魔学识", "Destruction": "毁灭",
    "Devastation": "湮灭", "Preservation": "恩护",
    "Devourer": "噬灭",
}

# (class, spec) → 中文全称（消歧义）
SPEC_CN_FULL: dict[tuple[str, str], str] = {
    ("Warrior", "Arms"): "武器战", ("Warrior", "Fury"): "狂怒战",
    ("Death Knight", "Frost"): "冰DK", ("Death Knight", "Unholy"): "邪DK", ("Death Knight", "Blood"): "血DK",
    ("Priest", "Holy"): "神牧", ("Priest", "Discipline"): "戒律牧", ("Priest", "Shadow"): "暗牧",
    ("Paladin", "Holy"): "奶骑", ("Paladin", "Protection"): "防骑", ("Paladin", "Retribution"): "惩戒骑",
    ("Shaman", "Restoration"): "恢复萨", ("Shaman", "Elemental"): "元素萨", ("Shaman", "Enhancement"): "增强萨",
    ("Druid", "Restoration"): "恢复德", ("Druid", "Balance"): "鸟德", ("Druid", "Feral"): "猫德", ("Druid", "Guardian"): "熊德",
    ("Mage", "Frost"): "冰法", ("Mage", "Fire"): "火法", ("Mage", "Arcane"): "奥法",
    ("Monk", "Brewmaster"): "酒仙", ("Monk", "Windwalker"): "踏风", ("Monk", "Mistweaver"): "织雾",
    ("Warlock", "Demonology"): "恶魔术", ("Warlock", "Affliction"): "痛苦术", ("Warlock", "Destruction"): "毁灭术",
    ("Rogue", "Assassination"): "奇袭贼", ("Rogue", "Outlaw"): "狂徒贼", ("Rogue", "Subtlety"): "敏锐贼",
    ("Hunter", "Beast Mastery"): "兽王猎", ("Hunter", "Marksmanship"): "射击猎", ("Hunter", "Survival"): "生存猎",
    ("Evoker", "Devastation"): "湮灭", ("Evoker", "Preservation"): "恩护", ("Evoker", "Devourer"): "噬灭（唤魔师）",
 ("Demon Hunter", "Havoc"): "浩劫DH", ("Demon Hunter", "Vengeance"): "复仇DH",
 ("Demon Hunter", "Devourer"): "噬灭DH",
 }

# 中文 → 英文专精名反向映射（用于解析 meta 中的中文专精）
SPEC_CN_REVERSE: dict[str, str] = {}
for _spec_en, _cn in SPEC_CN.items():
    if _cn not in SPEC_CN_REVERSE:
        SPEC_CN_REVERSE[_cn] = _spec_en
# 用 SPEC_CN_FULL 的完整名称覆盖
for (_class_en, _spec_en), _cn_full in SPEC_CN_FULL.items():
    SPEC_CN_REVERSE[_cn_full] = _spec_en

HEALER_SPECS: set[str] = {"Restoration", "Holy", "Discipline", "Preservation", "Mistweaver"}
TANK_SPECS: set[str] = {"Protection", "Blood", "Guardian", "Brewmaster", "Vengeance"}

# 通用消耗品关键词（过滤 buff_diffs）
CONSUMABLE_KEYWORDS: list[str] = ["凡图斯", "合剂", "进食充分", "御酒"]

# 跨职业 Buff（由其他职业提供，玩家无法自主控制）
CROSS_CLASS_BUFF_NAMES: set[str] = {
    "天怒",           # Augmentation Evoker
    "战斗怒吼",        # Warrior
    "真言术：韧",      # Priest
    "狂风",           # Shaman Windfury
    "灵魂链接",        # Shaman
    "先祖活力",        # Shaman
    "大地生命武器",     # Shaman
    "激流",           # Shaman
    "潮汐奔涌",        # Shaman
    "治疗之泉",        # Shaman
    "飞行模式：驭空术",
    "水之护盾",        # Shaman
    "大地之盾",        # Shaman (healer-specific, cross-class for non-healers)
}

# 被动治疗技能（治疗专精的伤害技能实际是被动/自动治疗）
PASSIVE_HEALING_SKILLS: set[str] = {
    "治疗之雨", "回响", "梦境吐息", "精神之花", "璀璨回响",
}


# ── 辅助函数 ──────────────────────────────────────────────────────────

def spec_cn_name(spec_en: str, class_en: str = "") -> str:
    """返回中文专精名（含消歧义）。"""
    if class_en:
        key = (class_en, spec_en)
        if key in SPEC_CN_FULL:
            return SPEC_CN_FULL[key]
    return SPEC_CN.get(spec_en, spec_en)


def format_num(n: float) -> str:
    """格式化数字为带逗号整数。"""
    return f"{n:,.0f}"


def rating_from_diff(diff: float) -> str:
    """根据 diff 值返回评级字母。diff 为负表示我方低于顶层。"""
    if diff >= 0:
        return "A"
    if diff >= -3:
        return "B"
    if diff >= -5:
        return "C"
    return "D"


def rating_from_ratio(ratio: float) -> str:
    """根据比率返回评级。"""
    if ratio >= 0.85:
        return "A"
    if ratio >= 0.70:
        return "B"
    if ratio >= 0.60:
        return "C"
    return "D"


def rating_from_pct_diff(our_pct: float, top_pct: float) -> str:
    """根据我们的百分比 vs 顶层百分比返回评级。"""
    diff = our_pct - top_pct
    return rating_from_diff(diff)


def rating_from_int_compare(our_int: int, top_int: int) -> str:
    """根据打断次数比较返回评级。"""
    if our_int >= top_int:
        return "A"
    if our_int >= top_int * 0.75:
        return "B"
    if our_int >= top_int * 0.5:
        return "C"
    return "D"


# ── 数据读取层 ─────────────────────────────────────────────────────────

def load_meta(meta_path: str) -> dict[str, Any]:
    """解析 m2_meta.txt → 结构化 dict。"""
    path = Path(meta_path)
    if not path.is_file():
        print(f"错误: meta 文件不存在: {meta_path}", file=sys.stderr)
        sys.exit(1)

    text = path.read_text(encoding="utf-8")
    lines = [l.rstrip() for l in text.split("\n") if l.strip()]

    result: dict[str, Any] = {
        "code": "", "fight_id": 0,
        "dungeon_cn": "", "level": 0, "timed": False,
        "duration_sec": 0, "complete_time": "",
        "players": [],
        "total_damage": 0, "total_healing": 0,
        "sx_count": 0, "sx_source": "",
        "wave_info": {},
    }

    for line in lines:
        # 副本: 三头议会 | 层数: +14 | [OK] 限时
        m = re.match(r"副本:\s*(.+?)\s*\|?\s*层数:\s*\+?(\d+|.)?\s*\|?\s*(?:\[OK\]|\[X\])?\s*(限时|超时)?", line)
        if m:
            result["dungeon_cn"] = m.group(1).strip()
            level_str = m.group(2)
            result["level"] = int(level_str) if level_str and level_str.isdigit() else 0
            timed_str = m.group(3)
            result["timed"] = "限时" in line and "超时" not in line

        # 总时长: 26:47 (1608s)
        m = re.match(r"总时长:\s*(\d+:\d+)\s*\((\d+)s\)", line)
        if m:
            result["duration_str"] = m.group(1)
            result["duration_sec"] = int(m.group(2))

        # 副本完成用时: 29:35
        m = re.match(r"副本完成用时:\s*(\d+:\d+)", line)
        if m:
            result["complete_time"] = m.group(1)

        # [T] 坦克: 我真会救你 (Monk/酒仙, 装等 280, DPS 85,058)
        # Note: meta file lines have leading whitespace; use \s* prefix
        m = re.match(
            r"\s*\[(T|H|D)\]\s*(?:坦克|治疗|DPS)?:\s*(\S+)\s*\((\w+)/(\S+?),\s*装等\s*(\d+),\s*DPS\s*([\d,]+)\)",
            line,
        )
        if m:
            role_tag = m.group(1)
            role_map = {"T": "tank", "H": "healer", "D": "dps"}
            class_en = m.group(3)
            spec_cn_raw = m.group(4)  # Chinese spec name from meta
            # Reverse-map Chinese spec name → English spec name
            spec_en = SPEC_CN_REVERSE.get(spec_cn_raw, spec_cn_raw)
            result["players"].append({
                "name": m.group(2),
                "class": class_en,
                "spec": spec_en,
                "spec_cn": spec_cn_name(spec_en, class_en),
                "role": role_map.get(role_tag, "dps"),
                "ilvl": int(m.group(5)),
                "dps": int(m.group(6).replace(",", "")),
            })

        # 团队总伤: 685.97M | 团队总治疗: 228.88M
        m = re.match(r"团队总伤:\s*([\d.]+)M\s*\|\s*团队总治疗:\s*([\d.]+)M", line)
        if m:
            result["total_damage"] = float(m.group(1)) * 1e6
            result["total_healing"] = float(m.group(2)) * 1e6

        # SX/嗜血次数: 3 次 (嗜血)
        m = re.match(r"SX/嗜血次数:\s*(\d+)\s*次", line)
        if m:
            result["sx_count"] = int(m.group(1))

        # 来源: 当归煲腊鸭:3次
        if "来源:" in line:
            result["sx_source"] = line.replace("来源:", "").strip()

    return result


def load_group_b(gb_path: str) -> dict[str, Any]:
    """解析 m2_group_b.txt → 结构化 dict。"""
    path = Path(gb_path)
    if not path.is_file():
        print(f"错误: group_b 文件不存在: {gb_path}", file=sys.stderr)
        sys.exit(1)

    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")

    result: dict[str, Any] = {
        "deaths": [],
        "death_clusters": [],
        "interrupts": {},
        "fights": [],
    }

    section = None
    death_header_skipped = False
    int_header_skipped = False
    fight_header_skipped = False

    for line in lines:
        stripped = line.strip()

        # Section detection
        if "死亡事件:" in stripped:
            section = "deaths"
            death_header_skipped = False
            continue
        if "打断事件:" in stripped:
            section = "interrupts"
            int_header_skipped = False
            continue
        if "路线时间轴:" in stripped:
            section = "fights"
            fight_header_skipped = False
            continue
        if "小怪波次" in stripped:
            section = "waves"
            continue
        if "死亡集群" in stripped:
            section = "clusters"
            continue

        if not stripped or stripped.startswith("==="):
            continue

        # ── Death events ──
        if section == "deaths":
            # Skip the table header row
            if "时间" in stripped and "玩家" in stripped:
                death_header_skipped = True
                continue
            if death_header_skipped and not stripped.startswith("---"):
                # Parse: 584s 沾繁霜而至曙 幽影箭矢 ? BOSS#8 Rift Warden
                # Or without phase: 584s 沾繁霜而至曙 幽影箭矢 ?
                m = re.match(
                    r"(\d+)s\s+(\S+)\s+(.+?)\s{2,}(\S+)\s+(.+)",
                    stripped,
                )
                if m:
                    result["deaths"].append({
                        "time_sec": int(m.group(1)),
                        "player": m.group(2),
                        "ability": m.group(3).strip(),
                        "source": m.group(4).strip(),
                        "phase": m.group(5).strip(),
                    })

        # ── Interrupts ──
        if section == "interrupts":
            if "按技能" in stripped:
                # 按技能部分不是按玩家的打断数据，切换 section 不再处理
                section = "interrupts_abilities"
                continue
            if "按玩家" in stripped:
                continue
            if stripped.startswith("---"):
                continue
            # 不穷锋: 25次
            m = re.match(r"(\S+):\s*(\d+)次", stripped)
            if m:
                result["interrupts"][m.group(1)] = int(m.group(2))

        # ── Fights ──
        if section == "fights":
            if "#" in stripped and "名称" in stripped:
                fight_header_skipped = True
                continue
            if fight_header_skipped:
                m = re.match(
                    r"\s*(\d+)\s+(.+?)\s+(BOSS\s*#?\d*|小怪)\s+(\d+:\d+)\s+(\d+:\d+)\s+(.+?)$",
                    stripped,
                )
                if m:
                    kill_str = m.group(6).strip()
                    is_kill = kill_str == "[OK]" or kill_str == "✅"
                    pct = 0
                    pct_m = re.match(r"\((\d+)%\)", kill_str)
                    if pct_m:
                        pct = int(pct_m.group(1))
                    result["fights"].append({
                        "id": int(m.group(1)),
                        "name": m.group(2).strip(),
                        "type": "boss" if "BOSS" in m.group(3) else "trash",
                        "start": m.group(4),
                        "duration": m.group(5),
                        "kill": is_kill,
                        "percentage": pct,
                    })

    # ── 死亡聚类 ──
    deaths = result["deaths"]
    clusters = []
    current = []
    for d in deaths:
        if not current or d["time_sec"] - current[-1]["time_sec"] < 15:
            current.append(d)
        else:
            if len(current) >= 2:
                clusters.append(current)
            current = [d]
    if len(current) >= 2:
        clusters.append(current)
    result["death_clusters"] = clusters

    return result


def load_benchmarks(bm_path: str) -> dict[str, Any]:
    """解析 per_spec_benchmarks.json → 结构化 dict，并重新解析未翻译的技能名。"""
    path = Path(bm_path)
    if not path.is_file():
        print(f"错误: benchmarks 文件不存在: {bm_path}", file=sys.stderr)
        sys.exit(1)

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    # ── 重新解析未翻译的技能名 ──
    players = data.get("players", {})
    for pname, pdata in players.items():
        # skill_diffs: 用 spell_cn_map 重新解析
        for sd in pdata.get("skill_diffs", []):
            sid = sd.get("spell_id", 0)
            if sid:
                resolved = spell_cn_resolve(sid, sd["skill"])
                if resolved != sd["skill"]:
                    sd["skill"] = resolved
        # cast_diffs: 同样重新解析
        for cd in pdata.get("cast_diffs", []):
            sid = cd.get("spell_id", 0)
            if sid:
                resolved = spell_cn_resolve(sid, cd["skill"])
                if resolved != cd["skill"]:
                    cd["skill"] = resolved

    return data


# ── Buff 过滤策略 ─────────────────────────────────────────────────────

def is_consumable(buff_name: str) -> bool:
    """判断是否为通用消耗品。"""
    return any(kw in buff_name for kw in CONSUMABLE_KEYWORDS)


def filter_buff_diffs(buff_diffs: list[dict[str, Any]], player_spec: str) -> list[dict[str, Any]]:
    """过滤 buff_diffs，只保留该专精可自主控制的 Buff。

    过滤规则:
    1. 移除通用消耗品
    2. 移除覆盖率 100% 的（无差异，无信息量）
    3. 移除跨职业 Buff
    4. 治疗专精特有 Buff 只保留给治疗本人
    """
    filtered = []
    for bd in buff_diffs:
        name = bd["name"]

        # 规则1: 通用消耗品
        if is_consumable(name):
            continue

        # 规则2: 覆盖率 100% 的双边满覆盖
        if bd.get("our_uptime", 0) == 100.0 and bd.get("top_uptime", 0) == 100.0:
            continue

        # 规则3: 跨职业 Buff
        if name in CROSS_CLASS_BUFF_NAMES:
            # 治疗特有 Buff: 只保留给相应治疗
            if player_spec in HEALER_SPECS and name in {
                "大地之盾", "大地生命武器", "激流", "潮汐奔涌",
                "治疗之泉", "水之护盾", "灵魂链接", "先祖活力",
            }:
                filtered.append(bd)
            continue

        filtered.append(bd)

    return filtered


# ── 表格生成层 ─────────────────────────────────────────────────────────

def build_header(meta: dict[str, Any]) -> str:
    """标题 + 基础信息块。"""
    timed_str = "限时" if meta["timed"] else "超时"
    level_str = f"+{meta['level']}" if meta["level"] else "?"
    dungeon = meta.get("dungeon_cn", "未知副本")
    title = f"# M2 报告: {dungeon} +{meta['level']} | {timed_str}"

    lines = [title, ""]
    dur = meta.get("duration_str", f"{meta['duration_sec'] // 60}:{meta['duration_sec'] % 60:02d}")
    lines.append(f"**时长**: {dur}",)
    if meta.get("complete_time"):
        lines.append(f"**完成用时**: {meta['complete_time']}")

    # 队伍
    lines.append("")
    lines.append("**队伍**:")
    lines.append("| 角色 | 玩家 | 专精 | 装等 | DPS |")
    lines.append("|------|------|------|------|-----|")
    for p in meta.get("players", []):
        role_icon = {"tank": "🛡️ 坦克", "healer": "💚 治疗", "dps": "⚔️ DPS"}
        role_str = role_icon.get(p["role"], "⚔️ DPS")
        dps_str = format_num(p["dps"])
        lines.append(f"| {role_str} | {p['name']} | {p['spec_cn']} | {p['ilvl']} | {dps_str} |")

    # 额外信息
    lines.append("")
    total_dmg = meta.get("total_damage", 0)
    total_heal = meta.get("total_healing", 0)
    sx_count = meta.get("sx_count", 0)
    lines.append(f"团队总伤: {total_dmg / 1e6:.2f}M | 团队总治疗: {total_heal / 1e6:.2f}M")
    lines.append(f"SX/嗜血: {sx_count} 次 ({meta.get('sx_source', '?')})")
    lines.append("")

    return "\n".join(lines)


def build_core_table(meta: dict[str, Any], gb: dict[str, Any], benchmarks: dict[str, Any]) -> str:
    """📈 核心数据表（5行×6列，含汇总行）。"""
    bm_players = benchmarks.get("players", {})
    death_counts = Counter(d["player"] for d in gb.get("deaths", []))

    lines = ["## 📈 核心数据表", ""]
    lines.append("| 玩家 | 专精 | DPS | 装等 | 打断 | 死亡 |")
    lines.append("|------|------|-----|------|------|------|")

    total_dps = 0
    total_ilvl = 0
    total_int = 0
    total_deaths = 0
    player_count = 0

    for p in meta.get("players", []):
        name = p["name"]
        dps = p["dps"]
        ilvl = p["ilvl"]
        spec_cn_val = p["spec_cn"]

        # 打断 count
        interrupts = gb.get("interrupts", {}).get(name, 0)

        # 死亡 count
        deaths = death_counts.get(name, 0)

        lines.append(f"| {name} | {spec_cn_val} | {format_num(dps)} | {ilvl} | {interrupts} | {deaths} |")

        total_dps += dps
        total_ilvl += ilvl
        total_int += interrupts
        total_deaths += deaths
        player_count += 1

    # 汇总行
    if player_count > 0:
        avg_dps = total_dps // player_count
        avg_ilvl = total_ilvl / player_count
        lines.append(f"| **汇总** | | **{format_num(avg_dps)}** | **{avg_ilvl:.1f}** | **{total_int}** | **{total_deaths}** |")

    lines.append("")
    return "\n".join(lines)


def build_death_timeline(gb: dict[str, Any]) -> str:
    """💀 死亡时间线表格。"""
    deaths = gb.get("deaths", [])
    lines = ["## 💀 死亡分析", ""]

    if not deaths:
        lines.append("✅ 零死亡，全队表现优秀。")
        lines.append("")
        lines.append("{{DEATH_ROOT_CAUSE}}")
        lines.append("")
        return "\n".join(lines)

    lines.append(f"共 **{len(deaths)} 次死亡**:")
    lines.append("")
    lines.append("| 时间 | 玩家 | 致死技能 | 致死源 | 阶段 |")
    lines.append("|------|------|----------|--------|------|")
    for d in deaths:
        t = d["time_sec"]
        mm, ss = divmod(t, 60)
        time_str = f"{mm}:{ss:02d}"
        lines.append(f"| {time_str} | {d['player']} | {d['ability']} | {d['source']} | {d['phase']} |")

    # 死亡集群
    clusters = gb.get("death_clusters", [])
    if clusters:
        lines.append("")
        lines.append("**死亡集群**:")
        for i, cl in enumerate(clusters, 1):
            t_start = cl[0]["time_sec"]
            t_end = cl[-1]["time_sec"]
            names = [d["player"] for d in cl]
            kills = [d["ability"] for d in cl]
            lines.append(f"- 集群{i} @{t_start}-{t_end}s: {', '.join(names)}")
            lines.append(f"  - 致死: {', '.join(kills)}")

    lines.append("")
    lines.append("{{DEATH_ROOT_CAUSE}}")
    lines.append("")
    return "\n".join(lines)


def build_player_skill_table(player_name: str, bm_data: dict[str, Any], gb: dict[str, Any], meta: dict[str, Any], diag_idx: int) -> str:
    """单个玩家的技能评估对比表（5列：指标|我方|顶层|差距|评级）。"""
    pdata = bm_data.get(player_name)
    if not pdata:
        return f"### {player_name}\n\n(无 benchmark 数据)\n\n{{DIAGNOSIS_{diag_idx}}}\n"

    our = pdata["our_player"]
    top = pdata["top_player"]
    spec = our.get("spec", "")
    class_en = our.get("class", "")
    spec_cn_val = spec_cn_name(spec, class_en)
    top_name = top.get("name", "?")
    dps_ratio = pdata.get("dps_ratio", 0)

    # 检查是否为治疗
    is_healer = spec in HEALER_SPECS

    lines = [f"### {player_name} — {spec_cn_val}", ""]
    lines.append(f"**对比顶层**: {top_name} ({spec_cn_val}, DPS {format_num(top['dps'])})")
    lines.append("")
    lines.append("| 指标 | 我方 | 顶层 | 差距 | 评级 |")
    lines.append("|------|------|------|------|------|")

    # 行1: DPS 比率
    ratio_str = f"{dps_ratio:.0%}"
    ratio_pct = dps_ratio * 100
    if is_healer:
        ratio_label = "DPS比率（治疗）"
    else:
        ratio_label = "DPS比率"
    ratio_top = "100%"
    gap_str = f"{dps_ratio - 1.0:+.0%}"
    ratio_rating = rating_from_ratio(dps_ratio)
    lines.append(f"| {ratio_label} | {ratio_str} | {ratio_top} | {gap_str} | {ratio_rating} |")

    # 行2: 核心技能 diff
    skill_diffs = pdata.get("skill_diffs", [])
    # 对于治疗，标记被动治疗技能
    for sd in skill_diffs:
        if is_healer and sd["skill"] in PASSIVE_HEALING_SKILLS:
            sd_label = f"{sd['skill']} [被动治疗]"
        else:
            sd_label = sd["skill"]
        diff = sd.get("diff", 0)
        lines.append(
            f"| {sd_label} | {sd.get('our_pct', '?')}% | {sd.get('top_pct', '?')}% | {diff:+.1f}% | "
            f"{rating_from_pct_diff(sd.get('our_pct', 0), sd.get('top_pct', 0))} |"
        )

    # 行3: 施法次数 diff
    cast_diffs = pdata.get("cast_diffs", [])
    for cd in cast_diffs:
        our_casts = cd.get("our_hits", 0)
        top_casts = cd.get("top_hits", 0)
        cast_ratio = our_casts / top_casts if top_casts > 0 else 1.0
        cd_label = f"{cd['skill']} (施法)"
        lines.append(
            f"| {cd_label} | {our_casts}次 | {top_casts}次 | "
            f"{our_casts - top_casts:+d} | {rating_from_ratio(cast_ratio)} |"
        )

    # 行4: Buff 覆盖率 diff（过滤后）
    buff_diffs = pdata.get("buff_diffs", [])
    filtered_buffs = filter_buff_diffs(buff_diffs, spec)
    # 最多展示 5 条最重要的（diff 绝对值最大的）
    filtered_buffs.sort(key=lambda x: abs(x.get("diff", 0)), reverse=True)
    for bd in filtered_buffs[:5]:
        our_up = bd.get("our_uptime", 0)
        top_up = bd.get("top_uptime", 0)
        diff = bd.get("diff", 0)
        lines.append(
            f"| {bd['name']} (覆盖) | {our_up:.1f}% | {top_up:.1f}% | {diff:+.1f}% | "
            f"{rating_from_pct_diff(our_up, top_up)} |"
        )

    # 行5: 打断次数
    int_data = pdata.get("interrupts", {})
    if isinstance(int_data, dict):
        our_int = int_data.get("our", 0)
        top_int = int_data.get("top", 0)
    elif isinstance(int_data, list) and len(int_data) >= 2:
        our_int = int_data[0]
        top_int = int_data[1]
    else:
        our_int = 0
        top_int = 0
    int_rating = rating_from_int_compare(our_int, top_int)
    lines.append(f"| 打断 | {our_int}次 | {top_int}次 | {our_int - top_int:+d} | {int_rating} |")

    lines.append("")
    lines.append(f"{{{{DIAGNOSIS_{diag_idx}}}}}")
    lines.append("")
    return "\n".join(lines)


def build_skill_assessment_section(meta: dict[str, Any], benchmarks: dict[str, Any], gb: dict[str, Any]) -> str:
    """🔧 技能使用评估 — 每人一张对比表。"""
    lines = ["## 🔧 技能使用评估", ""]

    for i, p in enumerate(meta.get("players", []), 1):
        table = build_player_skill_table(p["name"], benchmarks.get("players", {}), gb, meta, i)
        lines.append(table)

    return "\n".join(lines)


# ── 候选生成层 ─────────────────────────────────────────────────────────

def generate_highlights(meta: dict[str, Any], benchmarks: dict[str, Any], gb: dict[str, Any]) -> list[str]:
    """基于量化数据生成"做得好"候选。"""
    candidates: list[str] = []
    bm_players = benchmarks.get("players", {})
    death_counts = Counter(d["player"] for d in gb.get("deaths", []))
    interrupts = gb.get("interrupts", {})

    # 1) DPS比率最高 / ≥85%
    best_ratio = -1
    best_name = ""
    player_hits: list[tuple[str, float]] = []
    for pname, pdata in bm_players.items():
        ratio = pdata.get("dps_ratio", 0)
        player_hits.append((pname, ratio))
        if ratio > best_ratio:
            best_ratio = ratio
            best_name = pname
    for pname, ratio in sorted(player_hits, key=lambda x: -x[1]):
        if ratio >= 0.85:
            spec_cn_val = ""
            for p in meta.get("players", []):
                if p["name"] == pname:
                    spec_cn_val = p["spec_cn"]
                    break
            candidates.append(f"- {pname}({spec_cn_val}) DPS 比率 {ratio:.0%} ≥ 85%，输出表现优秀")
        elif ratio == best_ratio and ratio < 0.85:
            spec_cn_val = ""
            for p in meta.get("players", []):
                if p["name"] == pname:
                    spec_cn_val = p["spec_cn"]
                    break
            candidates.append(f"- {pname}({spec_cn_val}) DPS 比率 {ratio:.0%}，队伍最高")

    # 2) 打断最多 / ≥均值1.5x
    if interrupts:
        avg_int = sum(interrupts.values()) / len(interrupts)
        for pname, count in sorted(interrupts.items(), key=lambda x: -x[1]):
            if count >= avg_int * 1.5:
                candidates.append(f"- {pname} 打断 {count} 次（均值 {avg_int:.0f} 的 {count/avg_int:.1f}x），打断表现积极")
            elif count == max(interrupts.values()):
                candidates.append(f"- {pname} 打断 {count} 次，全队最高")

    # 3) 零死亡玩家
    zero_death = [p["name"] for p in meta.get("players", []) if death_counts.get(p["name"], 0) == 0]
    for name in zero_death:
        spec_cn_val = ""
        for p in meta.get("players", []):
            if p["name"] == name:
                spec_cn_val = p["spec_cn"]
                break
        candidates.append(f"- {name}({spec_cn_val}) 零死亡，生存表现好")

    # 4) 全队亮点: 伤害/治疗总量
    total_dmg = meta.get("total_damage", 0)
    total_heal = meta.get("total_healing", 0)
    if total_dmg > 0:
        candidates.append(f"- 全队总伤 {total_dmg / 1e6:.2f}M，总治疗 {total_heal / 1e6:.2f}M")

    # 5) 核心 Buff 高覆盖
    for pname, pdata in bm_players.items():
        buff_diffs = pdata.get("buff_diffs", [])
        spec = pdata.get("our_player", {}).get("spec", "")
        filtered = filter_buff_diffs(buff_diffs, spec)
        high_uptime = [b for b in filtered if b.get("our_uptime", 0) >= 95]
        for b in high_uptime[:2]:
            candidates.append(f"- {pname} 核心 Buff {b['name']} 覆盖率 {b['our_uptime']:.0f}% ≥ 95%")

    # 去重，最多 5 条
    seen: set[str] = set()
    unique: list[str] = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            unique.append(c)
    return unique[:5]


def generate_issues(meta: dict[str, Any], benchmarks: dict[str, Any], gb: dict[str, Any]) -> list[dict[str, Any]]:
    """基于量化数据生成"需要改进"候选，含优先级。"""
    issues: list[dict[str, Any]] = []
    bm_players = benchmarks.get("players", {})
    death_counts = Counter(d["player"] for d in gb.get("deaths", []))

    for pname, pdata in bm_players.items():
        spec = pdata.get("our_player", {}).get("spec", "")
        is_healer = spec in HEALER_SPECS

        # P0: DPS < 60%（精确治疗不触发此条）
        ratio = pdata.get("dps_ratio", 1.0)
        if ratio < 0.60 and not is_healer:
            issues.append({
                "player": pname,
                "priority": "P0",
                "desc": f"DPS 比率仅 {ratio:.0%}，显著低于顶层（<60%），需检查输出循环和优先级是否存在根本问题",
                "type": "dps",
            })
        elif ratio < 0.70 and not is_healer:
            # P2-ish for lower but not critical
            issues.append({
                "player": pname,
                "priority": "P1",
                "desc": f"DPS 比率 {ratio:.0%}，低于顶层 30%+，存在较大提升空间",
                "type": "dps",
            })

        # P1: Buff 覆盖率差距 >20%
        buff_diffs = pdata.get("buff_diffs", [])
        filtered = filter_buff_diffs(buff_diffs, spec)
        for bd in filtered:
            diff = bd.get("diff", 0)
            if diff < -20:
                issues.append({
                    "player": pname,
                    "priority": "P1",
                    "desc": f"Buff {bd['name']} 覆盖率 {bd['our_uptime']:.0f}% vs 顶层 {bd['top_uptime']:.0f}%（差 {diff:.0f}%），需检查覆盖中断原因",
                    "type": "buff",
                })
                break  # 最多一条 buff 问题

        # P1: 打断 < 顶层 50%
        int_data = pdata.get("interrupts", {})
        if isinstance(int_data, dict):
            our_int = int_data.get("our", 0)
            top_int = int_data.get("top", 0)
        else:
            our_int = 0
            top_int = 0
        if top_int > 0 and our_int < top_int * 0.5:
            issues.append({
                "player": pname,
                "priority": "P1",
                "desc": f"打断 {our_int} 次，仅顶层 {top_int} 次的 {our_int/top_int:.0%}（<50%），需提升打断意识",
                "type": "interrupt",
            })

        # P2: 死亡 ≥3
        deaths = death_counts.get(pname, 0)
        if deaths >= 3:
            issues.append({
                "player": pname,
                "priority": "P2",
                "desc": f"死亡 {deaths} 次（全队最高之一），需检查死亡根因并优化生存意识",
                "type": "death",
            })
        elif deaths >= 2:
            issues.append({
                "player": pname,
                "priority": "P2",
                "desc": f"死亡 {deaths} 次，存在生存隐患",
                "type": "death",
            })

    # Deduplicate, keep only highest priority per player per type
    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, Any]] = []
    for iss in sorted(issues, key=lambda x: (0 if x["priority"] == "P0" else 1 if x["priority"] == "P1" else 2)):
        key = (iss["player"], iss["type"])
        if key not in seen:
            seen.add(key)
            unique.append(iss)

    return unique[:5]


def generate_mvp_candidates(meta: dict[str, Any], benchmarks: dict[str, Any], gb: dict[str, Any]) -> dict[str, Any]:
    """生成 MVP/战犯的候选排名。"""
    bm_players = benchmarks.get("players", {})
    death_counts = Counter(d["player"] for d in gb.get("deaths", []))
    interrupts = gb.get("interrupts", {})

    mvp_scores: dict[str, float] = {}
    culprit_scores: dict[str, float] = {}

    for pname, pdata in bm_players.items():
        ratio = pdata.get("dps_ratio", 0)
        spec = pdata.get("our_player", {}).get("spec", "")
        is_tank = spec in TANK_SPECS

        # MVP score: DPS ratio × 50 + 打断 bonus + 死亡 penalty
        score = ratio * 50

        int_data = pdata.get("interrupts", {})
        if isinstance(int_data, dict):
            our_int = int_data.get("our", 0)
        else:
            our_int = 0
        score += min(our_int * 2, 15)  # interrupt bonus, max 15

        deaths = death_counts.get(pname, 0)
        score -= deaths * 5  # death penalty

        # Tank bonus: survival matters more
        if is_tank and deaths == 0:
            score += 10

        mvp_scores[pname] = score

        # Culprit score: death penalty + low DPS
        cscore = deaths * 10
        if ratio < 0.6:
            cscore += 20
        elif ratio < 0.7:
            cscore += 10
        if is_tank and deaths > 0:
            cscore += 15
        culprit_scores[pname] = cscore

    return {
        "mvp_scores": dict(sorted(mvp_scores.items(), key=lambda x: -x[1])),
        "culprit_scores": dict(sorted(culprit_scores.items(), key=lambda x: -x[1])),
    }


def generate_improvement_items(player_name: str, benchmarks: dict[str, Any], gb: dict[str, Any]) -> list[str]:
    """为单个玩家生成改进计划 checklist 初稿。"""
    items: list[str] = []
    pdata = benchmarks.get("players", {}).get(player_name)
    if not pdata:
        return ["- [ ] (无基准数据)"]

    spec = pdata.get("our_player", {}).get("spec", "")
    is_healer = spec in HEALER_SPECS

    # DPS 比率
    ratio = pdata.get("dps_ratio", 0)
    if ratio < 0.85:
        target_ratio = min(ratio + 0.15, 1.0)
        items.append(f"- [ ] 提升 DPS 至 {target_ratio:.0%} 比率（当前 {ratio:.0%}）")

    # 技能 diff
    skill_diffs = pdata.get("skill_diffs", [])
    for sd in skill_diffs:
        diff = sd.get("diff", 0)
        if diff < -3:
            skill_name = sd["skill"]
            if is_healer and skill_name in PASSIVE_HEALING_SKILLS:
                skill_name += " [被动治疗]"
            target_pct = sd.get("top_pct", 0)
            items.append(f"- [ ] 提高 {skill_name} 占比至 ~{target_pct:.0f}%（当前 {sd.get('our_pct', 0):.0f}%，差 {abs(diff):.0f}%）")

    # 施法次数
    cast_diffs = pdata.get("cast_diffs", [])
    for cd in cast_diffs:
        our_hits = cd.get("our_hits", 0)
        top_hits = cd.get("top_hits", 0)
        if top_hits > 0 and our_hits / top_hits < 0.8:
            items.append(f"- [ ] 增加 {cd['skill']} 施法次数至 ~{top_hits} 次（当前 {our_hits} 次）")

    # Buff 覆盖
    buff_diffs = pdata.get("buff_diffs", [])
    filtered = filter_buff_diffs(buff_diffs, spec)
    for bd in filtered[:3]:
        diff = bd.get("diff", 0)
        if diff < -10:
            items.append(f"- [ ] 提升 {bd['name']} 覆盖率至 ~{bd['top_uptime']:.0f}%（当前 {bd['our_uptime']:.0f}%）")

    # 打断
    int_data = pdata.get("interrupts", {})
    if isinstance(int_data, dict):
        our_int = int_data.get("our", 0)
        top_int = int_data.get("top", 0)
    else:
        our_int = 0
        top_int = 0
    if top_int > 0 and our_int < top_int:
        items.append(f"- [ ] 增加打断至 ~{top_int} 次（当前 {our_int} 次）")

    return items[:6]  # 最多 6 条


def build_improvement_plan(meta: dict[str, Any], benchmarks: dict[str, Any], gb: dict[str, Any]) -> str:
    """📅 改进计划 — 每人 checklist 初稿。"""
    lines = ["## 📅 改进计划", ""]

    for p in meta.get("players", []):
        name = p["name"]
        spec_cn_val = p["spec_cn"]
        items = generate_improvement_items(name, benchmarks, gb)
        lines.append(f"### {name} — {spec_cn_val}")
        lines.append("")
        if items:
            lines.extend(items)
        else:
            lines.append("- [ ] (无需明显改进)")
        lines.append("")

    lines.append("{{PLAN_FINAL}}")
    lines.append("")
    return "\n".join(lines)


def build_highlights_section(meta: dict[str, Any], benchmarks: dict[str, Any], gb: dict[str, Any]) -> str:
    """✅ 做得好 节。"""
    lines = ["## ✅ 做得好", ""]
    candidates = generate_highlights(meta, benchmarks, gb)
    if candidates:
        lines.extend(candidates)
    else:
        lines.append("(未生成候选)")
    lines.append("")
    lines.append("{{DO_WELL_FINAL}}")
    lines.append("")
    return "\n".join(lines)


def build_issues_section(meta: dict[str, Any], benchmarks: dict[str, Any], gb: dict[str, Any]) -> str:
    """❌ 需要改进 节。"""
    lines = ["## ❌ 需要改进", ""]
    issues = generate_issues(meta, benchmarks, gb)
    if issues:
        for iss in issues:
            lines.append(f"- [{iss['priority']}] {iss['player']}: {iss['desc']}")
    else:
        lines.append("(未生成问题候选)")
    lines.append("")
    lines.append("{{IMPROVE_FINAL}}")
    lines.append("")
    return "\n".join(lines)


def build_mvp_section(meta: dict[str, Any], benchmarks: dict[str, Any], gb: dict[str, Any]) -> str:
    """🎤 MVP/战犯 节。"""
    lines = ["## 🎤 MVP/战犯", ""]
    candidates = generate_mvp_candidates(meta, benchmarks, gb)

    lines.append("**MVP 候选（按得分排序）**:")
    for pname, score in candidates.get("mvp_scores", {}).items():
        pct = 0
        if pname in benchmarks.get("players", {}):
            pct = benchmarks["players"][pname].get("dps_ratio", 0) * 100
        deaths = Counter(d["player"] for d in gb.get("deaths", [])).get(pname, 0)
        ints = gb.get("interrupts", {}).get(pname, 0)
        lines.append(f"- {pname}: DPS {pct:.0f}% | 打断 {ints} | 死亡 {deaths} | 综合 {score:.0f}")

    lines.append("")
    lines.append("{{MVP_FINAL}}")
    lines.append("")
    return "\n".join(lines)


# ── 组装层 ────────────────────────────────────────────────────────────

def build_skeleton(meta: dict[str, Any], gb: dict[str, Any], bm: dict[str, Any]) -> str:
    """组装完整骨架 markdown。"""
    sections: list[str] = []

    # §1 标题 + 基础信息
    sections.append(build_header(meta))
    sections.append("---")
    sections.append("")

    # §2 核心数据表
    sections.append(build_core_table(meta, gb, bm))
    sections.append("---")
    sections.append("")

    # §3 做得好
    sections.append(build_highlights_section(meta, bm, gb))
    sections.append("---")
    sections.append("")

    # §4 需要改进
    sections.append(build_issues_section(meta, bm, gb))
    sections.append("---")
    sections.append("")

    # §5 死亡分析
    sections.append(build_death_timeline(gb))
    sections.append("---")
    sections.append("")

    # §6 技能使用评估
    sections.append(build_skill_assessment_section(meta, bm, gb))
    sections.append("---")
    sections.append("")

    # §7 MVP/战犯
    sections.append(build_mvp_section(meta, bm, gb))
    sections.append("---")
    sections.append("")

    # §8 改进计划
    sections.append(build_improvement_plan(meta, bm, gb))

    return "\n".join(sections)


# ── 主入口 ────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="M2 报告骨架预生成")
    parser.add_argument("report_code", help="WCL 报告代码")
    args = parser.parse_args()

    report_code = args.report_code

    # 验证输入文件
    for name, fpath in INPUT_FILES.items():
        if not fpath.is_file():
            print(f"错误: {name} 文件不存在: {fpath}", file=sys.stderr)
            sys.exit(1)

    print(f"✓ 输入文件验证通过 ({report_code})")

    # 读取数据
    meta = load_meta(str(INPUT_FILES["meta"]))
    print(f"✓ 解析 meta: {meta['dungeon_cn']} +{meta['level']} | {len(meta['players'])} 人")

    gb = load_group_b(str(INPUT_FILES["group_b"]))
    print(f"✓ 解析 group_b: {len(gb['deaths'])} 死亡 | {len(gb['interrupts'])} 打断 | {len(gb['fights'])} 战斗")

    bm = load_benchmarks(str(INPUT_FILES["benchmarks"]))
    bm_players = bm.get("players", {})
    print(f"✓ 解析 benchmarks: {len(bm_players)} 位玩家")
    for pname, pdata in bm_players.items():
        o = pdata["our_player"]
        ratio = pdata.get("dps_ratio", 0)
        print(f"    {pname}: {o.get('spec','?')} DPS {o.get('dps',0):.0f} 比率 {ratio:.0%}")

    # 生成骨架
    skeleton = build_skeleton(meta, gb, bm)

    # 写输出
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(skeleton, encoding="utf-8")
    size = len(skeleton.encode("utf-8"))
    print(f"✓ 骨架已写入: {OUTPUT_PATH} ({size:,} bytes, {size / 1024:.1f} KB)")

    # 验证占位符
    placeholders = [
        "{{DO_WELL_FINAL}}", "{{IMPROVE_FINAL}}", "{{DEATH_ROOT_CAUSE}}",
        "{{DIAGNOSIS_1}}", "{{DIAGNOSIS_2}}", "{{DIAGNOSIS_3}}",
        "{{DIAGNOSIS_4}}", "{{DIAGNOSIS_5}}",
        "{{MVP_FINAL}}", "{{PLAN_FINAL}}",
    ]
    for ph in placeholders:
        if ph not in skeleton:
            print(f"  ⚠️ 缺失占位符: {ph}", file=sys.stderr)
    print(f"✓ 占位符验证完成 ({sum(1 for ph in placeholders if ph in skeleton)}/{len(placeholders)} 存在)")


if __name__ == "__main__":
    main()
