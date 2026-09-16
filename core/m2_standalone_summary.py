#!/usr/bin/env python3
"""
m2_standalone_summary.py — 单份 SQLite DB → 独立分析摘要

读取 v1_pipeline.py 产出的 SQLite 数据库，输出结构化分析摘要文本。
不依赖对比数据，聚焦于自我分析：技能构成、活跃度、爆发使用、死亡、路线、Buff。

用法:
    python3 core/m2_standalone_summary.py <db_path> <report_code> [--output-dir data/cache]

输出:
    data/cache/m2_group_a.txt  — 伤害构成 + 施法活跃度 + 冷却爆发
    data/cache/m2_group_b.txt  — 死亡分析 + 路线时间轴 + 打断统计
    data/cache/m2_group_c.txt  — Buff 覆盖 + 资源流转
    data/cache/m2_meta.txt     — 报告元数据（含层数/限时/SX/波次方差）

版本: M2.1
"""

import argparse
import json
import sqlite3
import sys
import os
import requests
from collections import Counter, defaultdict
from pathlib import Path

# ── 外部数据文件 ────────────────────────────────────────────────────────
_SCRIPT_DIR = Path(__file__).resolve().parent.parent  # core/ → 项目根
_DUNGEON_NAMES_PATH = _SCRIPT_DIR / "data" / "mappings" / "dungeon_names.json"

def _load_dungeon_cn() -> dict:
    """从外部 JSON 加载副本名映射，文件不存在则回退空字典。"""
    try:
        if _DUNGEON_NAMES_PATH.is_file():
            with open(_DUNGEON_NAMES_PATH, encoding="utf-8") as f:
                data = json.load(f)
            return {k: v for k, v in data.items() if not k.startswith("_")}
    except Exception as e:
        print(f"  [警告] 无法加载副本名映射 {_DUNGEON_NAMES_PATH}: {e}", file=sys.stderr)
    return {}

# ═══════════════════════════════════════════════════════════════════
# 安全替换: 避免 DeepSeek Content Exists Risk 400 错误 (v2.0 增强版)
# ═══════════════════════════════════════════════════════════════════
# 触发源: 副本中文名、Emoji+ZWJ/VS、Greek字母、Unicode破折号等
# 修复: 从共享模块 scripts/safe_content_filter 导入全面安全过滤器
# ═══════════════════════════════════════════════════════════════════
try:
    from scripts.safe_content_filter import safe_content_filter, safe_dict_filter
except ImportError:
    # Fallback: 最小化内联实现 (仅中文替换，不含 Unicode 清洗)
    import re
    def safe_content_filter(text: str) -> str:
        # 安全过滤暂为空 — 400 问题仅对特定日志生效，不再需要主动替换
        return text
    def safe_dict_filter(data):
        if isinstance(data, str): return safe_content_filter(data)
        if isinstance(data, dict): return {k: safe_dict_filter(v) for k, v in data.items()}
        if isinstance(data, list): return [safe_dict_filter(item) for item in data]
        return data

# ── 国服翻译映射 ──────────────────────────────────────────────────────

# 专精英文 → 中文
SPEC_CN = {
    "Protection": "防护",      "Holy": "神圣",        "Retribution": "惩戒",
    "Arms": "武器",            "Fury": "狂怒",        "Protection": "防护（战）",
    "Blood": "鲜血",           "Frost": "冰霜",        "Unholy": "邪恶",
    "Havoc": "浩劫",           "Vengeance": "复仇",
    "Balance": "平衡",         "Feral": "野性",        "Guardian": "守护",
    "Restoration": "恢复",     "Restoration": "恢复（萨）",
    "Beast Mastery": "野兽控制", "Marksmanship": "射击", "Survival": "生存",
    "Arcane": "奥术",          "Fire": "火焰",         "Frost": "冰霜（法）",
    "Brewmaster": "酒仙",      "Windwalker": "踏风",    "Mistweaver": "织雾",
    "Discipline": "戒律",      "Holy": "神圣（牧）",    "Shadow": "暗影",
    "Assassination": "奇袭",   "Outlaw": "狂徒",       "Subtlety": "敏锐",
    "Elemental": "元素",       "Enhancement": "增强",   "Restoration": "恢复（萨）",
    "Affliction": "痛苦",      "Demonology": "恶魔学识", "Destruction": "毁灭",
    "Devastation": "湮灭",     "Preservation": "恩护",
    "Devourer": "噬灭",
}

# 专精中文全称格式化（用于队伍展示）
def spec_cn_display(spec_en, class_en=""):
    """返回中文专精名，避免歧义（如多个 Holy）"""
    cn = SPEC_CN.get(spec_en, spec_en)
    # 消歧义
    if class_en == "Paladin" and spec_en == "Protection":
        return "防护"
    if class_en == "Warrior" and spec_en == "Protection":
        return "防战"
    if class_en == "Paladin" and spec_en == "Holy":
        return "神圣"
    if class_en == "Priest" and spec_en == "Holy":
        return "神牧"
    if class_en == "Shaman" and spec_en == "Restoration":
        return "恢复"
    if class_en == "Druid" and spec_en == "Restoration":
        return "恢复德"
    if class_en == "Mage" and spec_en == "Frost":
        return "冰霜"
    if class_en == "Death Knight" and spec_en == "Frost":
        return "冰DK"
    return cn

# 副本 zone ID → 中文名
ZONE_CN = {
    47: "萨隆矿坑",
    184: "萨隆矿坑",
    658: "萨隆矿坑",
    # 12.0 新副本待补充
}

# SX/嗜血类技能 spell_id 集合
SX_SPELL_IDS = {2825, 32182, 80353, 264667, 390386, 381301}
SX_SPELL_NAMES = {
    2825: "嗜血", 32182: "英勇", 80353: "时间扭曲",
    264667: "原始狂怒", 390386: "巨龙之怒", 381301: "虚空之吼",
}

# WCL API 配置（用于 SX 检测的 events 端点查询）
from core.config import get_api_key as _get_api_key

_WCL_BASE = "https://www.warcraftlogs.com/v1"

# ── 辅助函数 ─────────────────────────────────────────────────────────

def format_duration(sec: float) -> str:
    """秒 → mm:ss 格式"""
    m, s = divmod(int(sec), 60)
    return f"{m}:{s:02d}"


# ── 数据提取 ─────────────────────────────────────────────────────────

def extract_meta(conn: sqlite3.Connection, report_code: str) -> dict:
    """提取报告元数据（含 keystone 信息）"""
    r = conn.execute(
        "SELECT title, zone, owner, start_time, end_time, dungeon_name FROM report WHERE report_code=?",
        (report_code,)
    ).fetchone()
    if not r:
        raise ValueError(f"报告 {report_code} 不在数据库中")

    duration_sec = (r["end_time"] - r["start_time"]) / 1000.0 if r["end_time"] and r["start_time"] else 0

    # 从 fight 表提取 keystone 元数据（取第一条非0记录）
    k = conn.execute(
        "SELECT keystone_level, keystone_time FROM fight WHERE report_code=? AND keystone_level > 0 LIMIT 1",
        (report_code,)
    ).fetchone()

    keystone_level = k["keystone_level"] if k else 0
    keystone_time = k["keystone_time"] if k else 0           # completionTime (ms)

    # keystone_timed 从 report 表读取
    kt = conn.execute(
        "SELECT keystone_timed FROM report WHERE report_code=?",
        (report_code,)
    ).fetchone()
    keystone_timed = bool(kt["keystone_timed"]) if kt else False

    # 限时剩余时间
    remaining_sec = 0
    if keystone_time > 0 and keystone_timed:
        # keystoneTime 理论值取决于副本和层数 (粗略: 约 30-33min 标准)
        # 这里用 keystoneTime/completionTime 判断；实际限时需查各副本timer
        # V1 API: completionTime 是实际完成时间, kill=true 表示限时
        remaining_sec = 0  # 无法精确计算, 需副本计时器查表
    elif keystone_time > 0 and not keystone_timed:
        remaining_sec = 0  # 超时

    # 计算实际完成时长
    actual_sec = keystone_time / 1000.0 if keystone_time > 0 else duration_sec

    zone_id = int(r["zone"]) if r["zone"] and r["zone"].isdigit() else 0

    # ── 从 DB 读取副本名（v1_pipeline 已存储），查外部映射 JSON；未存储则 fallback ──
    dungeon_name = r["dungeon_name"] if "dungeon_name" in r.keys() else ""
    DUNGEON_CN = _load_dungeon_cn()
    zone_cn = DUNGEON_CN.get(dungeon_name) if dungeon_name else ZONE_CN.get(zone_id, dungeon_name or r["zone"] or "未知副本")

    # 层数修正名（zone 字段存的是 zone_id，层数从 fight 取）
    level_str = f"+{keystone_level}" if keystone_level > 0 else "?"
    timed_str = "✅ 限时" if keystone_timed else ("❌ 超时" if keystone_level > 0 else "")

    return {
        "title": r["title"] or "",
        "zone": zone_cn,
        "zone_raw": r["zone"] or "",
        "owner": r["owner"] or "未知",
        "duration_sec": duration_sec,
        "duration_str": format_duration(duration_sec),
        "keystone_level": keystone_level,
        "level_str": level_str,
        "keystone_time_ms": keystone_time,
        "keystone_time_str": format_duration(keystone_time / 1000.0) if keystone_time else "?",
        "keystone_timed": keystone_timed,
        "timed_str": timed_str,
        "remaining_sec": remaining_sec,
    }


def extract_players(conn: sqlite3.Connection, report_code: str) -> list:
    """提取所有玩家信息（含伤害/治疗/装等/专精+打断次数）"""
    rows = conn.execute("""
        SELECT id, name, class, spec, ilvl, server,
               damage_total, heal_total, dps
        FROM player WHERE report_code=?
        ORDER BY damage_total DESC
    """, (report_code,)).fetchall()

    players = []
    for r in rows:
        # 打断次数
        int_count = conn.execute(
            "SELECT COUNT(*) FROM event WHERE report_code=? AND type='interrupt' AND source=?",
            (report_code, r["name"])
        ).fetchone()[0]

        players.append({
            "name": r["name"],
            "class": r["class"],
            "spec": r["spec"],
            "spec_cn": spec_cn_display(r["spec"], r["class"]),
            "ilvl": r["ilvl"],
            "server": r["server"],
            "damage_total": r["damage_total"],
            "heal_total": r["heal_total"],
            "dps": r["dps"],
            "player_id": r["id"],
            "interrupts": int_count,
        })
    return players


def extract_abilities(conn: sqlite3.Connection, player_id: int) -> list:
    """提取某个玩家的全部技能（按伤害降序）"""
    rows = conn.execute("""
        SELECT name, spell_id, amount, hits, crits, miss_pct
        FROM ability WHERE player_id=?
        ORDER BY amount DESC
    """, (player_id,)).fetchall()

    abilities = []
    for r in rows:
        abilities.append({
            "name": r["name"],
            "spell_id": r["spell_id"],
            "amount": r["amount"],
            "hits": r["hits"],
            "crits": r["crits"],
            "miss_pct": r["miss_pct"],
        })
    return abilities


def extract_auras(conn: sqlite3.Connection, player_id: int) -> list:
    """提取某个玩家的 Buff 覆盖（队伍级数据，但关联到个人）"""
    rows = conn.execute("""
        SELECT name, spell_id, uptime_pct
        FROM aura WHERE player_id=?
        ORDER BY uptime_pct DESC
    """, (player_id,)).fetchall()

    return [{"name": r["name"], "spell_id": r["spell_id"], "uptime_pct": r["uptime_pct"]} for r in rows]


def extract_events(conn: sqlite3.Connection, report_code: str) -> list:
    """提取所有事件（死亡 + 打断）"""
    rows = conn.execute("""
        SELECT timestamp, type, source, target, ability_name, ability_id, amount
        FROM event WHERE report_code=?
        ORDER BY timestamp
    """, (report_code,)).fetchall()

    events = []
    for r in rows:
        events.append({
            "relative_sec": round(r["timestamp"] / 1000.0, 1),
            "type": r["type"],
            "source": r["source"],
            "target": r["target"],
            "ability_name": r["ability_name"],
            "ability_id": r["ability_id"],
            "amount": r["amount"],
        })
    return events


def extract_fights(conn: sqlite3.Connection, report_code: str, start_ms: int) -> list:
    """提取所有战斗（Boss + 小怪波次）"""
    rows = conn.execute("""
        SELECT fight_id, name, kill, difficulty, start_time, end_time, percentage,
               keystone_level, keystone_time
        FROM fight WHERE report_code=?
        ORDER BY start_time
    """, (report_code,)).fetchall()

    fights = []
    for r in rows:
        # BOSS 判定: difficulty=="Mythic+" → 大多数 BOSS；fallback: 基于名称+战斗时长
        raw_dur = (r["end_time"] - r["start_time"]) / 1000.0 if r["start_time"] and r["end_time"] else 0
        is_boss = r["difficulty"] == "Mythic+"
        if not is_boss and r["name"]:
            nm = r["name"]
            trash_markers = ("Pack", "Trash", "Wave", "Patrol", "Group", "Pull")
            is_boss = not any(m in nm for m in trash_markers) and raw_dur > 60
        fights.append({
            "fight_id": r["fight_id"],
            "name": r["name"],
            "is_boss": is_boss,
            "kill": r["kill"] == 1,
            "start_rel_sec": round((r["start_time"] - start_ms) / 1000.0, 1) if start_ms else 0,
            "duration_sec": round((r["end_time"] - r["start_time"]) / 1000.0, 1) if r["start_time"] and r["end_time"] else 0,
            "percentage": r["percentage"],
        })
    return fights


def detect_sx(conn: sqlite3.Connection, player_names: list,
              report_code: str, start_time: int, end_time: int) -> dict:
    """
    检测嗜血/英勇使用次数。
    策略: 通过 WCL events API 查找 SX 类技能 cast 事件。
    V1 /tables/casts 端点不返回 SX 类技能，必须用 events 端点。
    返回 {"count": N, "by_player": {name: count}, "spell_name": str}
    """
    total = 0
    by_player = {}
    spell_name = ""
    error = None            # 非 None 表示 API 调用失败（而非真的无 SX）

    # 用 events 端点查询 cast 事件，过滤 SX spell_id
    url = f"{_WCL_BASE}/report/events/{report_code}"
    params = {
        "api_key": _get_api_key(),
        "start": start_time,
        "end": end_time,
        "filter": 'type="cast"',  # requests 自动处理 URL 编码，勿手动编码
    }

    try:
        # 建立 sourceID → playername 映射（从 WCL fights 端点 friendly 列表）
        id_to_name = {}
        try:
            fr = requests.get(
                f"{_WCL_BASE}/report/fights/{report_code}",
                params={"api_key": _get_api_key()},
                timeout=15,
            )
            fr.raise_for_status()
            for f in fr.json().get("friendlies", []):
                # 多字段 fallback: WCL 在不同版本中使用的字段名可能不同
                fid = f.get("id") or f.get("guid") or f.get("sourceID") or f.get("targetID")
                fname = f.get("name", "")
                if fid and fname and f.get("type") not in ("NPC", "Pet", "Unknown"):
                    id_to_name[int(fid)] = fname
        except Exception as e:
            print(f"  [SX检测] friendly 列表查询失败: {e}", file=sys.stderr)
            error = f"friendly_list:{type(e).__name__}"

        # events 端点有分页，需循环拉取
        current_start = start_time
        while current_start < end_time:
            params["start"] = current_start
            r = requests.get(url, params=params, timeout=30)
            r.raise_for_status()
            data = r.json()

            for evt in data.get("events", []):
                if evt.get("type") != "cast":
                    continue
                ability = evt.get("ability", {})
                spell_id = ability.get("guid", 0) if isinstance(ability, dict) else 0
                if spell_id in SX_SPELL_IDS:
                    sid = evt.get("sourceID", 0)
                    name = id_to_name.get(sid, f"Player#{sid}")
                    total += 1
                    by_player[name] = by_player.get(name, 0) + 1
                    if not spell_name:
                        spell_name = SX_SPELL_NAMES.get(
                            spell_id, ability.get("name", f"spell_{spell_id}")
                        )

            next_ts = data.get("nextPageTimestamp")
            if next_ts and next_ts > current_start:
                current_start = next_ts
            else:
                break

    except Exception as e:
        print(f"  [SX检测] events API 查询失败: {e}", file=sys.stderr)
        error = error or f"events_api:{type(e).__name__}"

    return {"count": total, "by_player": by_player, "spell_name": spell_name, "error": error}


def compute_wave_variance(fights: list) -> dict:
    """
    计算小怪波次用时方差。
    返回 {"mean": sec, "std": sec, "max": sec, "min": sec, "waves": [...]}
    """
    trash_waves = [f for f in fights if not f["is_boss"] and f["duration_sec"] > 0]
    if len(trash_waves) < 3:
        return {"mean": 0, "std": 0, "max": 0, "min": 0, "wave_count": len(trash_waves), "waves": []}

    import math
    durations = [w["duration_sec"] for w in trash_waves]
    mean = sum(durations) / len(durations)
    variance = sum((d - mean) ** 2 for d in durations) / len(durations)
    std = math.sqrt(variance)

    return {
        "mean": round(mean, 1),
        "std": round(std, 1),
        "max": max(durations),
        "min": min(durations),
        "wave_count": len(trash_waves),
        "waves": [(w["name"], round(w["duration_sec"], 1)) for w in trash_waves],
    }


# ── 摘要生成 ─────────────────────────────────────────────────────────

def build_meta(meta: dict, players: list, fights: list, sx_info: dict,
               wave_info: dict) -> str:
    """元数据摘要（含层数/限时/SX/波次方差）"""
    lines = [f"=== M2 独立分析: 报告元数据 ===\n"]
    lines.append(f"副本: {meta['zone']} | 层数: {meta['level_str']} | {meta['timed_str']}")
    lines.append(f"标题: {meta['title']}")
    lines.append(f"报告拥有者: {meta['owner']}")
    lines.append(f"总时长: {meta['duration_str']} ({meta['duration_sec']:.0f}s)")
    if meta['keystone_time_ms'] > 0:
        lines.append(f"副本完成用时: {meta['keystone_time_str']}")

    # 队伍列表
    tank = [p for p in players if p["spec"] in ("Protection", "Blood", "Guardian", "Brewmaster", "Vengeance")]
    healer = [p for p in players if p["spec"] in ("Restoration", "Holy", "Discipline", "Preservation", "Mistweaver")]
    dps = [p for p in players if p not in tank and p not in healer]

    lines.append(f"\n队伍 ({len(players)}人):")
    for role, role_name in [(tank, "🛡️ 坦克"), (healer, "💚 治疗"), (dps, "⚔️ DPS")]:
        for p in role:
            lines.append(f"  {role_name}: {p['name']} ({p['class']}/{p['spec_cn']}, 装等 {p['ilvl']}, DPS {p['dps']:,.0f})")

    total_dmg = sum(p["damage_total"] for p in players)
    total_heal = sum(p["heal_total"] for p in players)
    lines.append(f"\n团队总伤: {total_dmg/1e6:.2f}M | 团队总治疗: {total_heal/1e6:.2f}M")

    # SX 次数
    if sx_info.get("error"):
        lines.append(f"SX/嗜血次数: ⚠️ 检测失败 (API错误: {sx_info['error']})")
    elif sx_info["count"] > 0:
        lines.append(f"SX/嗜血次数: {sx_info['count']} 次 ({sx_info['spell_name']})")
        if sx_info["by_player"]:
            lines.append(f"  来源: " + ", ".join(f"{n}:{c}次" for n, c in sx_info["by_player"].items()))
    else:
        lines.append(f"SX/嗜血次数: 0 次 (⚠️ 未检测到)")

    # 波次方差
    if wave_info["wave_count"] > 0:
        lines.append(f"\n小怪波次用时分析 ({wave_info['wave_count']} 波):")
        lines.append(f"  均值: {wave_info['mean']}s | 标准差: {wave_info['std']}s")
        lines.append(f"  最快: {wave_info['min']}s | 最慢: {wave_info['max']}s")
        if wave_info["std"] > 20:
            lines.append(f"  ⚠️ 波次用时差异较大 (σ={wave_info['std']}s)，路线节奏可能不均匀")
        # 列出最慢的 3 波
        sorted_waves = sorted(wave_info["waves"], key=lambda x: -x[1])
        lines.append(f"  最慢 3 波: " + ", ".join(f"{n}({d}s)" for n, d in sorted_waves[:3]))

    return "\n".join(lines)


def build_group_a(meta: dict, players: list, conn: sqlite3.Connection) -> str:
    """伤害构成 + 施法活跃度 + 冷却爆发"""
    lines = [f"=== M2 独立分析: 伤害构成 + 施法活跃度 + 冷却爆发 ===\n"]
    lines.append(f"副本: {meta['zone']} {meta['level_str']} | 总时长: {meta['duration_str']}")
    team_str = ' / '.join(f"{p['class']}/{p['spec_cn']}({p['name']})" for p in players)
    lines.append(f"队伍: {team_str}")
    lines.append(f"")

    total_damage = sum(p["damage_total"] for p in players)
    total_healing = sum(p["heal_total"] for p in players)
    avg_ilvl = sum(p["ilvl"] for p in players) / len(players) if players else 0
    lines.append(f"总计伤害: {total_damage/1e6:.2f}M | 总计治疗: {total_healing/1e6:.2f}M | 平均装等: {avg_ilvl:.1f}")
    lines.append(f"")

    for p in players:
        spec_label = f"{p['class']}/{p['spec_cn']}"
        lines.append(f"## {p['name']} — {spec_label} (装等 {p['ilvl']}, DPS {p['dps']:,.0f})")

        # 伤害构成 Top 8
        abilities = extract_abilities(conn, p["player_id"])
        damage_total = p["damage_total"] if p["damage_total"] > 0 else 1
        top8 = abilities[:8]
        lines.append(f"  伤害构成 (Top 8 / {len(abilities)} 技能):")
        lines.append(f"  {'技能':<30} {'伤害(M)':>8} {'占比':>6} {'命中':>6}")
        for ab in top8:
            pct = ab["amount"] / damage_total * 100
            hits_str = str(ab["hits"]) if ab["hits"] > 0 else "触发/pet"
            lines.append(f"  {ab['name']:<30} {ab['amount']/1e6:>7.2f}M {pct:>5.1f}% {hits_str:>6}")

        # 施法活跃度
        total_casts = sum(a["hits"] for a in abilities if a["hits"] > 0)
        cpm = total_casts / (meta["duration_sec"] / 60) if meta["duration_sec"] > 0 else 0
        lines.append(f"  总施法次数(已知): {total_casts} | CPM ≈ {cpm:.1f}")

        # 冷却技能列表 (hits>0 的全部技能，让 AI 判断哪些是冷却)
        all_active = [(a["name"], a["hits"], a["amount"], a["spell_id"]) for a in abilities if a["hits"] > 0]
        auto_trigger = [(a["name"], a["amount"], a["spell_id"]) for a in abilities if a["hits"] == 0 and a["amount"] > 0]

        if all_active:
            lines.append(f"  技能施放详情 ({len(all_active)} 个有计次技能):")
            for name, hits, amount, sid in sorted(all_active, key=lambda x: -x[2]):
                pct = amount / damage_total * 100
                lines.append(f"    {name} (spell_id={sid}): {hits}次, {amount/1e6:.2f}M ({pct:.1f}%)")

        if auto_trigger:
            names = [n for n, _, _ in auto_trigger[:8]]
            lines.append(f"  [自动触发/pet技能, hits=0]: {', '.join(names)}")

        lines.append(f"  打断次数: {p['interrupts']}")
        lines.append(f"")

    return "\n".join(lines)


def build_group_b(meta: dict, players: list, events: list, fights: list,
                  wave_info: dict) -> str:
    """死亡分析 + 路线时间轴 + 打断统计"""
    lines = [f"=== M2 独立分析: 死亡分析 + 路线时间轴 + 打断统计 ===\n"]
    lines.append(f"副本: {meta['zone']} {meta['level_str']} | 总时长: {meta['duration_str']}")
    lines.append(f"V1 API 限制: 仅 death/interrupt 事件, 无施法事件流\n")

    # 分类玩家角色
    tank_names = {p["name"] for p in players if p["spec"] in ("Protection", "Blood", "Guardian", "Brewmaster", "Vengeance")}
    healer_names = {p["name"] for p in players if p["spec"] in ("Restoration", "Holy", "Discipline", "Preservation", "Mistweaver")}

    # 死亡事件
    deaths = [e for e in events if e["type"] == "death"]
    interrupts = [e for e in events if e["type"] == "interrupt"]

    lines.append(f"## 死亡事件: {len(deaths)} 次")
    if not deaths:
        lines.append(f"  ✅ 零死亡")
    else:
        # 建立 fight→phase 映射，用于标注死亡发生阶段
        fight_phases = {}
        for f in fights:
            fight_phases[(f["start_rel_sec"], f["start_rel_sec"] + f["duration_sec"])] = (
                "BOSS" if f["is_boss"] else "小怪", f["name"], f["fight_id"]
            )

        def classify_phase(rel_sec: float) -> str:
            for (s, e), (ptype, name, fid) in fight_phases.items():
                if s <= rel_sec <= e:
                    return f"{ptype}#{fid} {name}"
            return "未知阶段"

        lines.append(f"  {'时间':>6} {'玩家':<16} {'致死技能':<25} {'致死源':<16} {'阶段':<20}")
        for d in deaths:
            killing = d["ability_name"] or "?"
            target_npc = d["target"] or "?"
            phase = classify_phase(d["relative_sec"])
            lines.append(f"  {d['relative_sec']:>5.0f}s {d['source']:<16} {killing:<25} {target_npc:<16} {phase:<20}")

        # 死亡聚类
        clusters = []
        current = []
        for d in deaths:
            if not current or d["relative_sec"] - current[-1]["relative_sec"] < 15:
                current.append(d)
            else:
                if len(current) >= 2:
                    clusters.append(current)
                current = [d]
        if len(current) >= 2:
            clusters.append(current)

        if clusters:
            lines.append(f"\n  死亡集群分析:")
            for i, cl in enumerate(clusters):
                t_range = f"{cl[0]['relative_sec']:.0f}-{cl[-1]['relative_sec']:.0f}s"
                names = [d["source"] for d in cl]
                kills = [d.get("ability_name", "?") for d in cl]
                lines.append(f"    集群{i+1} @{t_range}: {', '.join(names)}")
                lines.append(f"      致死: {', '.join(kills)}")
                has_tank = any(n in tank_names for n in names)
                has_healer = any(n in healer_names for n in names)
                if has_tank and len(cl) >= 3:
                    lines.append(f"      → 根因推测: 坦克先倒 → 连锁减员, 检查坦克减伤/治疗响应")
                elif has_tank and len(cl) == 2:
                    lines.append(f"      → 根因推测: 坦克倒后近战DPS被顺劈")
                elif has_healer:
                    lines.append(f"      → 根因推测: 治疗死亡 → 团队断奶")

        # 死亡统计
        death_counts = Counter(d["source"] for d in deaths)
        lines.append(f"\n  按玩家统计: " + ", ".join(f"{p}:{c}" for p, c in death_counts.most_common()))
        lines.append(f"  时间惩罚估算: {len(deaths)*15}s (每次死亡≈15s跑尸)")

    # 打断统计
    lines.append(f"\n## 打断事件: {len(interrupts)} 次")
    if interrupts:
        int_by_player = Counter(e["source"] for e in interrupts)
        for player, count in int_by_player.most_common():
            lines.append(f"  {player}: {count}次")
        int_by_ability = Counter(e["ability_name"] for e in interrupts)
        lines.append(f"\n  按技能 (被打断Top 10):")
        for ability, count in int_by_ability.most_common(10):
            lines.append(f"    {ability}: {count}次")

    # 路线时间轴
    lines.append(f"\n## 路线时间轴: {len(fights)} 场战斗")
    lines.append(f"  {'#':>3} {'名称':<30} {'类别':>8} {'开始':>8} {'持续':>7} {'击杀':>4}")
    boss_count = 0
    for i, f in enumerate(fights):
        cat = "BOSS" if f["is_boss"] else "小怪"
        if f["is_boss"]:
            boss_count += 1
            cat = f"BOSS #{boss_count}"
        kill_mark = "✅" if f["kill"] else f"({f['percentage']:.0f}%)"
        lines.append(f"  {i+1:>3} {f['name']:<30} {cat:>8} {format_duration(f['start_rel_sec']):>8} {format_duration(f['duration_sec']):>7} {kill_mark:>4}")

    # 波次用时方差
    if wave_info["wave_count"] >= 3:
        lines.append(f"\n## 小怪波次用时方差")
        lines.append(f"  均值 {wave_info['mean']}s | σ={wave_info['std']}s | 最大 {wave_info['max']}s | 最小 {wave_info['min']}s")
        if wave_info["std"] > 20:
            lines.append(f"  ⚠️ 标准差较大，路线节奏不均匀")
            # 显示最慢/最快
            sorted_w = sorted(wave_info["waves"], key=lambda x: -x[1])
            lines.append(f"  最慢: {sorted_w[0][0]} ({sorted_w[0][1]}s)")
            lines.append(f"  最快: {sorted_w[-1][0]} ({sorted_w[-1][1]}s)")

    return "\n".join(lines)


def build_group_c(meta: dict, players: list, conn: sqlite3.Connection) -> str:
    """Buff 覆盖 + 资源流转"""
    lines = [f"=== M2 独立分析: Buff覆盖 + 资源流转 ===\n"]
    lines.append(f"⚠️ V1 API: aura 为队伍级数据, 所有玩家共享; /tables/resources 始终空响应\n")

    # aura 为队伍级数据，验证一致性后取第一个玩家
    if players:
        # 验证: 所有玩家的 aura spell_id 集合应一致（队伍级数据）
        aura_sets = {}
        for p in players:
            auras = extract_auras(conn, p["player_id"])
            aura_sets[p["name"]] = frozenset((a["spell_id"], a["uptime_pct"]) for a in auras)
        if len(set(aura_sets.values())) > 1:
            print(f"  [警告] aura 数据在玩家间不一致，可能非队伍级数据", file=sys.stderr)
        auras = extract_auras(conn, players[0]["player_id"])
        lines.append(f"## Buff/Debuff 覆盖 (队伍级, 覆盖率>30%):")
        if auras:
            lines.append(f"  {'Buff名称':<35} {'覆盖率':>7}")
            for au in auras:
                lines.append(f"  {au['name']:<35} {au['uptime_pct']:>6.1f}%")
        else:
            lines.append(f"  (无覆盖率>30%的Buff)")

    lines.append(f"\n## 资源流转")
    lines.append(f"  ❌ 不可用: V1 API /tables/resources 始终返回空响应")
    lines.append(f"  资源分析需 V2 GraphQL events → 进阶路径 (M3)")

    return "\n".join(lines)


# ── 主入口 ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="M2 独立分析摘要生成器")
    parser.add_argument("db_path", help="SQLite 数据库路径 (v1_pipeline.py 产出)")
    parser.add_argument("report_code", help="WCL 报告代码")
    parser.add_argument("--output-dir", default="data/cache", help="输出目录 (默认: data/cache)")
    args = parser.parse_args()

    if not os.path.isfile(args.db_path):
        print(f"错误: 数据库不存在: {args.db_path}", file=sys.stderr)
        sys.exit(1)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    global conn
    conn = sqlite3.connect(args.db_path)
    conn.row_factory = sqlite3.Row

    try:
        # ── 提取数据 ──
        meta = extract_meta(conn, args.report_code)
        players = extract_players(conn, args.report_code)
        start_ms = conn.execute(
            "SELECT start_time FROM report WHERE report_code=?", (args.report_code,)
        ).fetchone()["start_time"]
        end_ms = conn.execute(
            "SELECT end_time FROM report WHERE report_code=?", (args.report_code,)
        ).fetchone()["end_time"]
        events = extract_events(conn, args.report_code)
        fights = extract_fights(conn, args.report_code, start_ms)

        # 额外指标
        player_names = [p["name"] for p in players]
        sx_info = detect_sx(conn, player_names, args.report_code, start_ms, end_ms)
        wave_info = compute_wave_variance(fights)

        print(f"✓ 数据提取完成: {len(players)} 玩家, {len(events)} 事件, {len(fights)} 场战斗")
        print(f"  层数: {meta['level_str']} | SX: {sx_info['count']}次 | 波次σ: {wave_info['std']}s")

        # ── 生成摘要 ──
        meta_txt = build_meta(meta, players, fights, sx_info, wave_info)
        group_a = build_group_a(meta, players, conn)
        group_b = build_group_b(meta, players, events, fights, wave_info)
        group_c = build_group_c(meta, players, conn)

        # ── 写文件 ──
        files = {
            "m2_meta.txt": safe_content_filter(meta_txt),
            "m2_group_a.txt": safe_content_filter(group_a),
            "m2_group_b.txt": safe_content_filter(group_b),
            "m2_group_c.txt": safe_content_filter(group_c),
        }

        for fname, content in files.items():
            fpath = out_dir / fname
            fpath.write_text(content, encoding="utf-8")
            size = len(content.encode("utf-8"))
            print(f"✓ {fpath} — {size:,} bytes")

        # 总计
        total = sum(len(c.encode("utf-8")) for c in files.values())
        print(f"\n总计: {total:,} bytes ({total/1024:.1f} KB)")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
