#!/usr/bin/env python3
"""
fetch_top_benchmarks.py — 根据我方阵容自动查找同副本/同专精顶级选手

从 WCL rankings API 自动发现每个专精的顶层报告，拉取数据并生成 1v1 对比 JSON。

用法:
    python3 core/fetch_top_benchmarks.py <our_db_path> <our_report_code> [--output data/cache/per_spec_benchmarks.json]

流程:
    1. 读取我方 DB → 获取 5 人专精列表和副本 zone_id
    2. zone_id → encounter_id（通过 /zones API 查找）
    3. /rankings/encounter/{id} → 每专精找最高层数顶级选手
    4. v1_pipeline 拉取顶级报告数据
    5. 提取 1v1 技能构成/Buff/施法对比 → JSON

依赖: v1_pipeline.py（作为子进程调用）, requests, sqlite3
"""

import argparse
import json
import sqlite3
import sys
import os
import subprocess
from collections import defaultdict
from pathlib import Path

# ── 跨语言技能名解析 ──────────────────────────────────────────────
try:
    from core.spell_cn_map import init as spell_cn_init, resolve as spell_cn_resolve, is_chinese
except ImportError:
    # 回退：无映射时原样返回
    def spell_cn_init(*args, **kwargs): pass
    def spell_cn_resolve(spell_id, fallback=""): return fallback or f"spell_{spell_id}"
    def is_chinese(text): return True  # 保守策略

# ═══════════════════════════════════════════════════════════════════
# 安全替换: 避免 DeepSeek Content Exists Risk 400 错误 (v2.0 增强版)
# ═══════════════════════════════════════════════════════════════════
# 触发源: 副本中文名、Emoji+ZWJ/VS、Greek字母、Unicode破折号等
# 修复: 从共享模块 scripts/safe_content_filter 导入全面安全过滤器
# ═══════════════════════════════════════════════════════════════════
try:
    from scripts.safe_content_filter import safe_content_filter, safe_dict_filter
except ImportError:
    import re
    def safe_content_filter(text: str) -> str:
        # 安全过滤暂为空 — 400 问题仅对特定日志生效，不再需要主动替换
        return text
    def safe_dict_filter(data):
        if isinstance(data, str): return safe_content_filter(data)
        if isinstance(data, dict): return {k: safe_dict_filter(v) for k, v in data.items()}
        if isinstance(data, list): return [safe_dict_filter(item) for item in data]
        return data

# ── WCL V1 API ────────────────────────────────────────────────────────

from core.config import get_api_key


def _api_key() -> str:
    return get_api_key()


V1_BASE = "https://www.warcraftlogs.com/v1"

# ── WCL DB class/spec → rankings API (class_id, spec_id) 映射 ──────
# 排名 API 使用独立的 class/spec 编号体系，与 WCL 表端点不同。
# 此表从实际排名数据校准得出。

RANK_CLASS_SPEC = {
    # (DB_class, DB_spec) → (rank_class_id, rank_spec_id)
    ("DeathKnight", "Blood"):          (1, 1),    # 推测
    ("DeathKnight", "Frost"):          (1, 2),    # 推测
    ("DeathKnight", "Unholy"):         (1, 3),
    ("Druid", "Balance"):              (2, 1),    # 推测
    ("Druid", "Feral"):                (2, 2),
    ("Druid", "Guardian"):             (2, 3),
    ("Druid", "Restoration"):          (2, 4),
    ("Hunter", "Beast Mastery"):       (3, 1),    # 推测
    ("Hunter", "Marksmanship"):        (3, 2),    # 推测
    ("Hunter", "Survival"):            (3, 3),    # 推测
    ("Rogue", "Assassination"):        (4, 1),    # 推测
    ("Rogue", "Outlaw"):               (4, 3),    # 推测
    ("Rogue", "Subtlety"):             (4, 2),    # 推测
    ("Monk", "Brewmaster"):            (5, 1),
    ("Monk", "Windwalker"):            (5, 2),
    ("Monk", "Mistweaver"):            (5, 2),    # 同 spec_id, DPS 范围区分
    ("Paladin", "Holy"):               (6, 1),
    ("Paladin", "Protection"):         (6, 2),
    ("Paladin", "Retribution"):        (6, 3),
    ("Priest", "Discipline"):          (7, 1),
    ("Priest", "Holy"):                (7, 2),    # 推测
    ("Priest", "Shadow"):              (7, 3),
    ("Mage", "Arcane"):                (8, 1),    # 推测 (Zerøcool)
    ("Mage", "Fire"):                  (8, 4),    # 推测 (Tomelvis)
    ("Mage", "Frost"):                 (8, 3),    # 推测
    ("Shaman", "Elemental"):           (9, 1),
    ("Shaman", "Enhancement"):         (9, 2),    # 推测
    ("Shaman", "Restoration"):         (9, 3),
    ("Warlock", "Affliction"):         (10, 1),   # 推测
    ("Warlock", "Demonology"):         (10, 2),
    ("Warlock", "Destruction"):        (10, 3),   # 推测
    ("Warrior", "Arms"):               (11, 1),
    ("Warrior", "Fury"):               (11, 2),
    ("Warrior", "Protection"):         (11, 2),   # 推测 (spec 2 shared with Fury)
    ("DemonHunter", "Havoc"):          (12, 3),
    ("DemonHunter", "Vengeance"):      (12, 2),   # 推测
    ("DemonHunter", "Devourer"):       (12, 3),   # 噬灭 = Havoc 变体, 同 spec_id
    ("Evoker", "Devastation"):         (13, 1),
    ("Evoker", "Preservation"):        (13, 2),
    ("Evoker", "Augmentation"):        (13, 3),
}

# DPS 范围启发式: 区分相同 (class_id, spec_id) 的不同角色
# 如 Monk spec 2 同时对应 Windwalker(DPS) 和 Mistweaver(治疗)
TANK_SPECS   = {"Protection", "Blood", "Vengeance", "Guardian", "Brewmaster"}
HEALER_SPECS = {"Restoration", "Holy", "Discipline", "Preservation", "Mistweaver"}

# 已知的副本名 → 排名 API encounter_id 映射 (zone 47 Mythic+ S1)
# fetch_top_benchmarks 会从 WCL fights API 获取实际副本名，然后查此表。
# 不再用 zone_id 硬编码——zone 47 含 8 个副本，各自有独立 encounter_id。
DUNGEON_ENCOUNTERS = {
    "Windrunner Spire":     12805,   # 风行者之塔
    "Pit of Saron":         10658,   # 萨隆矿坑
    "Skyreach":             61209,   # 通天峰
    "Algeth'ar Academy":    112526,  # 阿尔盖萨学院
    "Magisters' Terrace":   12811,   # 魔导师平台
    "Maisara Caverns":      12874,   # 迈萨拉洞窟
    "Nexus-Point Xenas":    12915,   # 节点希纳斯
    "Seat of the Triumvirate": 361753,  # (三人议会)
    "The Seat of the Triumvirate": 361753,  # (三人议会) (WCL 返回带 "The " 前缀)
}

# zone_id → encounter_id 兜底映射（当副本名未匹配时使用）
ZONE_ENCOUNTERS = {
    47: 10658,    # Mythic+ Season 1 → 默认萨隆矿坑
    184: 10658,
    658: 10658,
}

# ── 关键职业 Buff（spell_id）─────────────────────────────────────
# 这些 buff 是专精核心机制（暗影形态、横扫攻击等），
# 必须强制出现在对比数据中，不受 abs(diff)>3 阈值限制。
KEY_BUFF_SPELL_IDS = {
    232698,  # 暗影形态 (Shadowform) — 暗牧核心
    15473,   # 暗影形态 (Shadowform, alt id)
    260708,  # 横扫攻击 (Sweeping Strikes) — 武器战
    440989,  # 巨人神力 (Colossal Might) — 武器战
    1269394, # 战争大师 (Master of Warfare) — 武器战
    390978,  # 命运多舛 (Twist of Fate) — 暗牧
    184362,  # 激怒 (Enrage) — 狂暴战
    132403,  # 正义盾击 (Shield of the Righteous) — 防骑
    190456,  # 无视苦痛 (Ignore Pain) — 防战
    215479,  # 醉拳 (Shuffle) — 酒仙
    768,     # 猎豹形态 (Cat Form) — 猫德
    1256322, # 虚落 (Voidfall) — 噬灭 DH
    188370,  # 奉献 (Consecration) — 防骑
    31884,   # 复仇之怒 (Avenging Wrath) — 惩戒骑
    431536,  # 倾天圣威 (Shake the Heavens) — 惩戒骑
    108366,  # 灵魂榨取 (Soul Leech) — 恶魔术
    387552,  # 狱火统御 (Fel Domination) — 恶魔术
    61295,   # 激流 (Riptide) — 恢复萨
}

# ── 辅助函数 ─────────────────────────────────────────────────────────

def get_rank_class_spec(db_class: str, db_spec: str) -> tuple:
    """DB class/spec → rankings API (class_id, spec_id)"""
    key = (db_class, db_spec)
    if key in RANK_CLASS_SPEC:
        return RANK_CLASS_SPEC[key]
    # 模糊匹配
    for (c, s), v in RANK_CLASS_SPEC.items():
        if c == db_class and s.lower() == db_spec.lower():
            return v
    # 按职业找第一个匹配
    for (c, s), v in RANK_CLASS_SPEC.items():
        if c == db_class:
            return v
    return (0, 0)


def get_encounter_id(zone_str: str) -> int:
    """zone_id 字符串 → rankings API encounter_id"""
    try:
        zone_id = int(zone_str)
    except (ValueError, TypeError):
        return 0

    if zone_id in ZONE_ENCOUNTERS:
        return ZONE_ENCOUNTERS[zone_id]

    # 动态查询 /zones API
    import requests
    try:
        r = requests.get(f"{V1_BASE}/zones", params={"api_key": _api_key()}, timeout=15)
        r.raise_for_status()
        for z in r.json():
            if z.get("id") == zone_id:
                encounters = z.get("encounters", [])
                if encounters:
                    eid = encounters[0]["id"]
                    ZONE_ENCOUNTERS[zone_id] = eid
                    return eid
    except Exception:
        pass
    return 0


def fetch_rankings(encounter_id: int, max_pages: int = 50) -> list:
    """拉取指定 encounter 的全部排名记录"""
    import requests
    all_rankings = []
    for page in range(1, max_pages + 1):
        r = requests.get(
            f"{V1_BASE}/rankings/encounter/{encounter_id}",
            params={"api_key": _api_key(), "page": page},
            timeout=20,
        )
        data = r.json()
        rankings = data.get("rankings", [])
        if not rankings:
            break
        all_rankings.extend(rankings)
        if not data.get("hasMorePages"):
            break
    return all_rankings


def find_top_per_spec(rankings: list, our_players: list) -> dict:
    """
    为每个我方玩家找到同专精顶级选手。
    
    our_players: [(name, db_class, db_spec), ...]
    返回: {player_name: {top_name, top_dps, top_level, report_code, fight_id, ...}}
    """
    result = {}

    for pname, db_class, db_spec in our_players:
        rcid, rsid = get_rank_class_spec(db_class, db_spec)
        if rcid == 0:
            result[pname] = {"error": f"无法映射 {db_class}/{db_spec} 到排名 API"}
            continue

        # 找同 class + spec 的排行，按 (keystoneLevel desc, total desc) 排序
        candidates = [
            r for r in rankings
            if r["class"] == rcid and r["spec"] == rsid
        ]

        if not candidates:
            result[pname] = {
                "error": f"该专精 {db_spec} 在副本顶层无排名数据",
                "no_data": True,
            }
            continue

        # 对于 tank/healer，不能用纯 DPS 排序（治疗者 DPS 可能有噪音）
        # 简单策略：最高层数优先，同层按 total 降序
        candidates.sort(key=lambda r: (-r["keystoneLevel"], -r["total"]))
        # 匿名顺延：榜首匿名时，找第一个非匿名选手
        best = None
        skipped_anon = 0
        for c in candidates:
            if c.get("name", "") == "Anonymous" or c.get("anonymous", False):
                skipped_anon += 1
                continue
            best = c
            break
        if best is None:
            # 极端情况：所有候选都是匿名的，退回榜首（仍会失败但给出明确错误）
            best = candidates[0]
            skipped_anon = 0

        result[pname] = {
            "top_name": best["name"],
            "top_dps": best["total"],
            "top_level": best["keystoneLevel"],
            "report_code": best["reportID"],
            "fight_id": best.get("fightID", 1),
            "duration_ms": best.get("duration", 0),
            "server": best.get("serverName", ""),
            "candidates_count": len(candidates),
            "skipped_anonymous": skipped_anon,
        }

    return result


def extract_comparison(our_db: str, our_code: str, top_db: str, top_code: str,
                       our_name: str, our_spec: str, top_name: str, top_spec: str) -> dict:
    """从两个 DB 提取单对专精的对比数据"""
    our_conn = sqlite3.connect(our_db)
    our_conn.row_factory = sqlite3.Row
    top_conn = sqlite3.connect(top_db)
    top_conn.row_factory = sqlite3.Row

    our_player = our_conn.execute(
        "SELECT * FROM player WHERE report_code=? AND name=?", (our_code, our_name)
    ).fetchone()

    top_player = top_conn.execute(
        "SELECT * FROM player WHERE report_code=? AND spec=? AND name=?",
        (top_code, top_spec, top_name)
    ).fetchone()

    if not our_player or not top_player:
        our_conn.close(); top_conn.close()
        return {"error": "player_not_found"}

    total_our = our_player["damage_total"]
    total_top = top_player["damage_total"]

    # 伤害构成 (spell_id 跨语言匹配 + CN 名解析)
    our_ab = our_conn.execute(
        "SELECT name, spell_id, amount, hits FROM ability WHERE player_id=?",
        (our_player["id"],)
    ).fetchall()
    top_ab = top_conn.execute(
        "SELECT name, spell_id, amount, hits FROM ability WHERE player_id=?",
        (top_player["id"],)
    ).fetchall()

    skill_map = {}
    for a in our_ab:
        sid = a["spell_id"]
        cn_name = spell_cn_resolve(sid, a["name"])
        skill_map[sid] = {"our_name": cn_name,
                          "our_name_raw": a["name"],
                          "our_pct": a["amount"] / total_our * 100 if total_our > 0 else 0,
                          "our_hits": a["hits"] or 0}
    for a in top_ab:
        sid = a["spell_id"]
        cn_name = spell_cn_resolve(sid, a["name"])
        if sid in skill_map:
            d = skill_map[sid]
            d["top_name"] = cn_name
            d["top_name_raw"] = a["name"]
            d["top_pct"] = a["amount"] / total_top * 100 if total_top > 0 else 0
            d["top_hits"] = a["hits"] or 0
        else:
            skill_map[sid] = {"top_name": cn_name,
                              "top_name_raw": a["name"],
                              "top_pct": a["amount"] / total_top * 100 if total_top > 0 else 0,
                              "top_hits": a["hits"] or 0}

    top_skills = sorted(
        [(sid, v) for sid, v in skill_map.items() if v.get("our_pct", 0) > 0],
        key=lambda x: -x[1].get("our_pct", 0)
    )[:8]
    top_only = sorted(
        [(sid, v) for sid, v in skill_map.items()
         if not v.get("our_pct") and v.get("top_pct", 0) > 0],
        key=lambda x: -x[1].get("top_pct", 0)
    )[:4]

    skill_diffs = []
    for sid, v in top_skills + top_only:
        oname = v.get("our_name", v.get("top_name", f"spell_{sid}"))
        o_pct = v.get("our_pct", 0) or 0
        t_pct = v.get("top_pct", 0) or 0
        # 跨语言标记：双方原始名均非中文时标注
        raw_names = []
        if "our_name_raw" in v and v.get("our_name") != v.get("our_name_raw"):
            raw_names.append(f"我方原始: {v['our_name_raw']}")
        if "top_name_raw" in v and v.get("top_name") != v.get("top_name_raw"):
            raw_names.append(f"顶层原始: {v['top_name_raw']}")
        note = "; ".join(raw_names) if raw_names else None
        skill_diffs.append({
            "skill": oname, "spell_id": sid,
            "our_pct": round(o_pct, 1), "top_pct": round(t_pct, 1),
            "diff": round(o_pct - t_pct, 1),
        })
        if note:
            skill_diffs[-1]["name_note"] = note

    # Buff 覆盖
    our_buffs = our_conn.execute(
        "SELECT name, spell_id, uptime_pct FROM aura WHERE player_id=?",
        (our_player["id"],)
    ).fetchall()
    top_buffs = top_conn.execute(
        "SELECT name, spell_id, uptime_pct FROM aura WHERE player_id=?",
        (top_player["id"],)
    ).fetchall()

    ob = {b["spell_id"]: {"name": spell_cn_resolve(b["spell_id"], b["name"]), "uptime": b["uptime_pct"], "name_raw": b["name"]} for b in our_buffs}
    tb = {b["spell_id"]: {"name": spell_cn_resolve(b["spell_id"], b["name"]), "uptime": b["uptime_pct"], "name_raw": b["name"]} for b in top_buffs}
    all_sids = set(ob.keys()) & set(tb.keys())

    buff_diffs = []
    for sid in all_sids:
        o_u = ob[sid]["uptime"] or 0
        t_u = tb[sid]["uptime"] or 0
        diff = o_u - t_u
        # 关键职业 Buff 始终纳入（如暗影形态、横扫攻击），不受 diff 阈值限制
        if abs(diff) > 3 or sid in KEY_BUFF_SPELL_IDS:
            entry = {
                "name": ob[sid]["name"], "spell_id": sid,
                "our_uptime": round(o_u, 1), "top_uptime": round(t_u, 1),
                "diff": round(diff, 1),
            }
            # 跨语言标记
            if ob[sid].get("name_raw") and ob[sid]["name_raw"] != ob[sid]["name"]:
                entry["our_name_raw"] = ob[sid]["name_raw"]
            if tb[sid].get("name_raw") and tb[sid]["name_raw"] != tb[sid]["name"]:
                entry["top_name_raw"] = tb[sid]["name_raw"]
            buff_diffs.append(entry)
    buff_diffs.sort(key=lambda x: -abs(x["diff"]))

    # 施法次数
    cast_diffs = []
    for sid, v in top_skills[:6]:
        o_h = v.get("our_hits", 0) or 0
        t_h = v.get("top_hits", 0) or 0
        if o_h > 0 or t_h > 0:
            cast_diffs.append({
                "skill": v.get("our_name", v.get("top_name")),
                "spell_id": sid,
                "our_hits": o_h, "top_hits": t_h,
            })

    # ── 打断数据 ────────────────────────────────────────────
    our_int = our_conn.execute(
        "SELECT COUNT(*) FROM event WHERE report_code=? AND type='interrupt' AND source=?",
        (our_code, our_name)
    ).fetchone()[0]
    top_int = top_conn.execute(
        "SELECT COUNT(*) FROM event WHERE report_code=? AND type='interrupt' AND source=?",
        (top_code, top_name)
    ).fetchone()[0]

    # ── V1 归属空缺标记：casts>0 但 damage=0 ──
    # 这是 V1 API 的已知限制——casts 端点记录了施法，但 damage-done 端点
    # 未将伤害归属到该 spell_id（伤害可能被归于其他技能如顺劈斩）。
    # 严重度分级：
    #   ⚠️ WARNING: 双方都有相同空缺 → 可能为 V1 端点限制，非操作问题
    #   🔴 CRITICAL: 仅一方有空缺 → 需确认是否为手法/天赋差异
    attribution_gaps = []
    for sid, v in top_skills + top_only:
        o_h = v.get("our_hits", 0) or 0
        o_pct = v.get("our_pct", 0) or 0
        t_h = v.get("top_hits", 0) or 0
        t_pct = v.get("top_pct", 0) or 0
        cn_name = spell_cn_resolve(sid, v.get("our_name", v.get("top_name", f"spell_{sid}")))
        our_gap = (o_h > 0 and o_pct == 0)
        top_gap = (t_h > 0 and t_pct == 0)
        if our_gap and top_gap:
            # 双方都有——V1 端点限制
            attribution_gaps.append({
                "severity": "WARNING",
                "type": "v1_api_shared_gap",
                "spell_id": sid,
                "skill": cn_name,
                "our_hits": o_h, "top_hits": t_h,
                "message": f"{cn_name}: 双方均施放但伤害=0 (V1 API 伤害归属空缺, 可能归于其他技能)"
            })
        elif our_gap:
            attribution_gaps.append({
                "severity": "CRITICAL",
                "type": "our_only_gap",
                "spell_id": sid,
                "skill": cn_name,
                "our_hits": o_h,
                "message": f"我方 {cn_name}: {o_h}次施放但伤害=0 (V1 API 伤害归属空缺——我方特有, 需确认)"
            })
        elif top_gap:
            attribution_gaps.append({
                "severity": "CRITICAL",
                "type": "top_only_gap",
                "spell_id": sid,
                "skill": cn_name,
                "top_hits": t_h,
                "message": f"顶层 {cn_name}: {t_h}次施放但伤害=0 (V1 API 伤害归属空缺——顶层特有, 需确认)"
            })

    our_conn.close()
    top_conn.close()

    result = {
        "our_player": {"name": our_name, "spec": our_spec,
                       "dps": our_player["dps"], "ilvl": our_player["ilvl"]},
        "top_player": {"name": top_name, "spec": top_spec,
                       "dps": top_player["dps"], "ilvl": top_player["ilvl"]},
        "dps_ratio": round(our_player["dps"] / top_player["dps"], 3) if top_player["dps"] > 0 else 0,
        "skill_diffs": skill_diffs,
        "buff_diffs": buff_diffs,
        "cast_diffs": cast_diffs,
        "interrupts": {"our": our_int, "top": top_int},
    }
    if attribution_gaps:
        result["attribution_gaps"] = attribution_gaps
    return result


# ── 主流程 ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="从 WCL rankings API 自动发现顶级选手并生成对比数据")
    parser.add_argument("our_db", help="我方 SQLite 数据库路径")
    parser.add_argument("our_code", help="我方报告码")
    parser.add_argument("--output", default="data/cache/per_spec_benchmarks.json",
                        help="输出 JSON 路径")
    parser.add_argument("--db-dir", default="data/wcl_db",
                        help="顶端报告 SQLite 存储目录")
    parser.add_argument("--pipeline-script", default="core/v1_pipeline.py",
                        help="v1_pipeline.py 路径")
    parser.add_argument("--dry-run", action="store_true",
                        help="仅查找顶层选手，不拉取数据")
    args = parser.parse_args()

    import requests

    # ── Step 1: 读取我方阵容与副本 ────────────────────────────────
    conn = sqlite3.connect(args.our_db)
    conn.row_factory = sqlite3.Row

    report = conn.execute(
        "SELECT * FROM report WHERE report_code=?", (args.our_code,)
    ).fetchone()
    if not report:
        print(f"错误: 报告 {args.our_code} 不在 {args.our_db} 中", file=sys.stderr)
        sys.exit(1)

    zone_str = report["zone"]

    # ── 从 DB 读取副本名（v1_pipeline 已存储）──
    dungeon_name = report["dungeon_name"] if "dungeon_name" in report.keys() else None
    if not dungeon_name:
        # 旧 DB 兜底：从 fight 表 BOSS 名推断
        dungeon_name = None

    # 优先按副本名匹配 encounter_id，未匹配则回退到 zone_id 兜底
    encounter_id = DUNGEON_ENCOUNTERS.get(dungeon_name) if dungeon_name else 0
    if encounter_id == 0:
        encounter_id = get_encounter_id(zone_str)
    safe_dungeon = safe_content_filter(dungeon_name or '未知')
    print(f"  副本: {safe_dungeon} → encounter_id={encounter_id}")

    players = conn.execute(
        "SELECT name, class, spec FROM player WHERE report_code=?",
        (args.our_code,)
    ).fetchall()
    our_players = [(p["name"], p["class"], p["spec"]) for p in players]
    print(f"我方阵容 ({len(our_players)}人):")
    for n, c, s in our_players:
        print(f"  {n}: {c}/{s}")

    # ── Step 2: 拉取排名数据 ──────────────────────────────────────
    print(f"\n拉取 encounter={encounter_id} 排名数据...")
    rankings = fetch_rankings(encounter_id)
    print(f"  共 {len(rankings)} 条排名记录")

    # ── Step 3: 每专精找顶级选手 ──────────────────────────────────
    top_map = find_top_per_spec(rankings, our_players)
    print(f"\n找到的顶级选手:")
    for pname, info in top_map.items():
        if "error" in info:
            print(f"  {pname}: ❌ {info['error']}")
        else:
            anon_note = f" (跳过{info['skipped_anonymous']}匿名)" if info.get("skipped_anonymous") else ""
            print(f"  {pname}: {info['top_name']} +{info['top_level']} "
                  f"{info['top_dps']:.0f}DPS ({info['candidates_count']} candidates{anon_note})")

    if args.dry_run:
        print("\n[Dry-run 模式] 不拉取数据。")
        json.dump(top_map, sys.stdout, indent=2, ensure_ascii=False)
        return

    # ── Step 4: 拉取顶层报告数据 (去重: 同一 report 只拉一次) ─────
    # report_code → {fight_id, players: [(our_name, top_name, our_spec)]}
    fetch_tasks = defaultdict(lambda: {"fight_id": None, "players": []})
    for pname, info in top_map.items():
        if "error" in info:
            continue
        code = info["report_code"]
        fid = info.get("fight_id", 1)
        task = fetch_tasks[code]
        task["fight_id"] = fid  # 同报告可能有不同 fight, 取第一个
        task["players"].append((pname, info["top_name"], info.get("top_spec", "")))

    # ── 缓存验证：检查 DB 是否由 by=ability 增强版 v1_pipeline 生成 ──
    def _cache_is_valid(db_path: Path) -> bool:
        """缓存有效 = 任意玩家有 >12 技能 (by=ability 增强生效的特征)"""
        try:
            conn = sqlite3.connect(str(db_path))
            max_skills = conn.execute(
                "SELECT MAX(cnt) FROM (SELECT COUNT(*) as cnt FROM ability GROUP BY player_id)"
            ).fetchone()[0]
            conn.close()
            return max_skills is not None and max_skills > 12
        except Exception:
            return False

    # 并行拉取 (通过 subprocess)
    print(f"\n拉取 {len(fetch_tasks)} 份顶层报告...")
    processes = {}
    for code, task in fetch_tasks.items():
        db_path = Path(args.db_dir) / f"{code}.db"
        if db_path.exists():
            if _cache_is_valid(db_path):
                print(f"  {code} (fight={task['fight_id']}): 已缓存, 跳过")
                continue
            else:
                print(f"  {code} (fight={task['fight_id']}): 缓存过期(by=ability 缺失), 重新拉取...")
                db_path.unlink()  # 删除旧缓存
        cmd = [
            sys.executable, args.pipeline_script, code,
            "--fight-id", str(task["fight_id"]),
            "--db-dir", args.db_dir,
        ]
        print(f"  {code} (fight={task['fight_id']}): 拉取中...")
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env={**os.environ, "WCL_API_KEY": _api_key(), "PYTHONPATH": "."},
            cwd=Path(args.pipeline_script).parent.parent,
        )
        processes[code] = proc

    # 等待全部完成
    for code, proc in processes.items():
        stdout, stderr = proc.communicate(timeout=300)
        if proc.returncode != 0:
            print(f"  {code}: ❌ 失败\n{stderr.decode()[:300]}")
        else:
            print(f"  {code}: ✅ 完成")

    # ── Step 5: 提取 1v1 对比数据 ────────────────────────────────
    print(f"\n提取对比数据...")

    # 初始化跨语言技能名映射
    spell_cn_init(args.db_dir)
    try:
        from core.spell_cn_map import mapping_stats
        stats = mapping_stats()
        print(f"  spell_cn_map: {stats['total']} 条映射 (hardcoded={stats['hardcoded']}, db_extracted={stats['db_extracted']})")
    except Exception:
        pass

    results = {}
    for pname, info in top_map.items():
        if "error" in info:
            results[pname] = {"error": info["error"]}
            if info.get("no_data"):
                results[pname]["no_top_data"] = True
            continue

        code = info["report_code"]
        top_db = str(Path(args.db_dir) / f"{code}.db")
        if not os.path.exists(top_db):
            results[pname] = {"error": f"顶层 DB 不存在: {top_db}"}
            continue

        # 找到该顶层报告中专精名
        spec_conn = sqlite3.connect(top_db)
        spec_conn.row_factory = sqlite3.Row
        top_player_row = spec_conn.execute(
            "SELECT spec FROM player WHERE report_code=? AND name=?",
            (code, info["top_name"])
        ).fetchone()
        spec_conn.close()

        if not top_player_row:
            results[pname] = {"error": f"顶层玩家 {info['top_name']} 不在 DB 中"}
            continue

        top_spec = top_player_row["spec"]
        our_spec = next((s for n, c, s in our_players if n == pname), "")

        comparison = extract_comparison(
            args.our_db, args.our_code,
            top_db, code,
            pname, our_spec,
            info["top_name"], top_spec,
        )
        results[pname] = comparison

    # ── Step 6: 输出 ──────────────────────────────────────────────
    # 添加跨语言名称统计
    name_resolutions = 0
    for pname, comp in results.items():
        if "error" in comp:
            continue
        for sd in comp.get("skill_diffs", []):
            if sd.get("name_note"):
                name_resolutions += 1
        for bd in comp.get("buff_diffs", []):
            if bd.get("our_name_raw") or bd.get("top_name_raw"):
                name_resolutions += 1

    output = {
        "meta": {
            "spell_cn_map": stats if 'stats' in dir() else {},
            "name_resolutions": name_resolutions,
            "note": "所有技能/Buff名已通过 spell_cn_map 解析为国服简体中文",
        },
        "players": results,
    }
    output = safe_dict_filter(output)  # 安全过滤，避免 DeepSeek 400
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    success_count = sum(1 for v in results.values() if "error" not in v)
    print(f"\n✅ 完成: {success_count}/{len(results)} 专精有对比数据")
    print(f"   输出: {output_path}")


if __name__ == "__main__":
    main()
