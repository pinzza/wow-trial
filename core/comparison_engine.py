#!/usr/bin/env python3
"""
comparison_engine.py — 读取两份 wcl_parser 产出的 SQLite 数据库，
逐维度对比计算，输出 8 节结构化 JSON。

用法:
    python comparison_engine.py \\
      --our-db /path/to/our.db --our-code qavZzKjfyNhmF7V1 \\
      --top-db /path/to/top.db --top-code xxxxxxxxxxxxxxxx \\
      --output comparison_result.json
"""

import argparse
import json
import sqlite3

# === Content Safety Filter (DeepSeek 400 防护 v2.0 增强版) ===
try:
    from scripts.safe_content_filter import safe_dict_filter as _safe_filter
except ImportError:
    # 安全过滤暂为空 — 400 问题仅对特定日志生效，不再需要主动替换
    def _safe_filter(obj):
        # 安全过滤暂为空 — 400 问题仅对特定日志生效，不再需要主动替换
        return obj
import sys
import os
from collections import defaultdict
from datetime import datetime, timezone

RESOURCE_TYPES = {"resource", "energize", "drain", "refresh"}


# ── 辅助函数 ─────────────────────────────────────────────────────────


def load_db(db_path: str, report_code: str) -> sqlite3.Connection:
    """连接 SQLite 并确认 report_code 存在。"""
    if not os.path.isfile(db_path):
        print(f"错误: 数据库文件不存在: {db_path}", file=sys.stderr)
        sys.exit(1)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT 1 FROM report WHERE report_code=?", (report_code,)
    ).fetchone()
    if not row:
        print(f"错误: 报告 {report_code} 不在 {db_path} 中", file=sys.stderr)
        sys.exit(1)
    return conn


def read_meta(our_conn: sqlite3.Connection, our_code: str,
              top_conn: sqlite3.Connection, top_code: str,
              args) -> dict:
    """构建 meta 节。"""
    def fetch_meta(conn, code):
        r = conn.execute(
            "SELECT title, start_time, end_time, zone, owner FROM report WHERE report_code=?",
            (code,)
        ).fetchone()
        return dict(r) if r else {}
    our_m = fetch_meta(our_conn, our_code)
    top_m = fetch_meta(top_conn, top_code)
    return {
        "our_code": our_code,
        "our_zone": our_m.get("zone", ""),
        "our_title": our_m.get("title", ""),
        "top_code": top_code,
        "top_zone": top_m.get("zone", ""),
        "top_title": top_m.get("title", ""),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def get_time_base(conn: sqlite3.Connection, report_code: str) -> tuple:
    """返回 (start_ms, end_ms)。"""
    r = conn.execute(
        "SELECT start_time, end_time FROM report WHERE report_code=?",
        (report_code,)
    ).fetchone()
    return r["start_time"], r["end_time"]


def rel_sec(ts_ms: int, start_ms: int) -> float:
    """绝对 WCL 时间戳 (ms) → 相对秒数 (相对于报告开始)。"""
    return round((ts_ms - start_ms) / 1000, 1)


def safe_sec(val):
    """将值转为秒数 (输入 ms 或 None)。"""
    if val is None:
        return 0.0
    return round(val / 1000, 1)


def same_spec_pairs(our_players: list, top_players: list) -> list:
    """
    同名专精一一配对。
    按 spec 分组，组内按 damage_total 降序，zip 配对。
    多出的玩家标记为单边。
    """
    def group(players):
        g = defaultdict(list)
        for p in players:
            g[p["spec"]].append(p)
        for spec in g:
            g[spec].sort(key=lambda x: x["damage_total"], reverse=True)
        return g

    our_g = group(our_players)
    top_g = group(top_players)
    pairs = []
    all_specs = set(list(our_g.keys()) + list(top_g.keys()))
    for spec in sorted(all_specs):
        ours = our_g.get(spec, [])
        tops = top_g.get(spec, [])
        n = min(len(ours), len(tops))
        for i in range(n):
            pairs.append({
                "spec": spec,
                "our": {"name": ours[i].get("name",""), "damage_total": ours[i].get("damage_total",0)},
                "top": {"name": tops[i].get("name",""), "damage_total": tops[i].get("damage_total",0)},
            })
        for i in range(n, len(ours)):
            pairs.append({
                "spec": spec,
                "our": {"name": ours[i].get("name",""), "damage_total": ours[i].get("damage_total",0)},
                "top": None,
            })
        for i in range(n, len(tops)):
            pairs.append({
                "spec": spec,
                "our": None,
                "top": {"name": tops[i].get("name",""), "damage_total": tops[i].get("damage_total",0)},
            })
    return pairs


# ── 第 1 节: 伤害构成 ─────────────────────────────────────────────


def compute_damage_composition(our_conn: sqlite3.Connection, our_code: str,
                                top_conn: sqlite3.Connection, top_code: str) -> dict:
    """伤害构成：每玩家 Top 8 技能占比 + 同名专精配对。"""

    def build_players(conn, code):
        rows = conn.execute("""
            SELECT p.id, p.name, p.class, p.spec, p.damage_total,
                   a.name as ability_name, a.spell_id, a.amount
            FROM player p
            JOIN ability a ON a.player_id = p.id
            WHERE p.report_code = ? AND a.amount > 0
            ORDER BY p.damage_total DESC, a.amount DESC
        """, (code,)).fetchall()

        player_map = {}
        for r in rows:
            name = r["name"]
            if name not in player_map:
                player_map[name] = {
                    "name": name,
                    "class": r["class"],
                    "spec": r["spec"],
                    "damage_total": r["damage_total"],
                    "top_abilities": [],
                }
            if len(player_map[name]["top_abilities"]) < 8:
                pct = round(r["amount"] / r["damage_total"] * 100, 1) if r["damage_total"] > 0 else 0
                player_map[name]["top_abilities"].append({
                    "name": r["ability_name"],
                    "spell_id": r["spell_id"],
                    "amount": r["amount"],
                    "pct": pct,
                })
        return list(player_map.values())

    our_players = build_players(our_conn, our_code)
    top_players = build_players(top_conn, top_code)
    pairs = same_spec_pairs(our_players, top_players)

    return {
        "our_players": our_players,
        "top_players": top_players,
        "same_spec_pairs": pairs,
    }


# ── 第 2 节: 施法活跃度 ────────────────────────────────────────────


def compute_cast_activity(our_conn: sqlite3.Connection, our_code: str,
                           top_conn: sqlite3.Connection, top_code: str) -> dict:
    """施法活跃度：CPM。无时间戳，不做窗口密度/间隔分析。"""

    limitation = ("无 cast 事件时间戳。CPM 基于 ability.hits 聚合施法次数计算。"
                  "窗口密度和间隔分析不可用。")

    def build_players(conn, code):
        start_ms, end_ms = get_time_base(conn, code)
        duration_sec = max((end_ms - start_ms) / 1000, 1)
        rows = conn.execute("""
            SELECT p.name, SUM(a.hits) as total_casts
            FROM player p
            LEFT JOIN ability a ON a.player_id = p.id
            WHERE p.report_code = ?
            GROUP BY p.id, p.name
            ORDER BY total_casts DESC
        """, (code,)).fetchall()

        result = []
        for r in rows:
            casts = r["total_casts"] or 0
            cpm = round(casts / (duration_sec / 60), 1) if duration_sec > 0 else 0
            result.append({
                "name": r["name"],
                "total_casts": casts,
                "duration_sec": round(duration_sec, 1),
                "cpm": cpm,
                "window_density_5s": {
                    "available": False,
                    "note": "无 cast 事件时间戳，窗口密度分析不可用",
                },
                "long_gap_count": {
                    "available": False,
                    "note": "无 cast 事件时间戳，间隔分析不可用",
                },
                "max_gap_sec": {
                    "available": False,
                    "note": "无 cast 事件时间戳，最大间隔计算不可用",
                },
            })
        return result

    our_players = build_players(our_conn, our_code)
    top_players = build_players(top_conn, top_code)

    return {
        "available": True,
        "limitation": limitation,
        "our_players": our_players,
        "top_players": top_players,
    }


# ── 第 3 节: 冷却与爆发 ────────────────────────────────────────────


def compute_cooldown_usage(our_conn: sqlite3.Connection, our_code: str,
                            top_conn: sqlite3.Connection, top_code: str) -> dict:
    """冷却与爆发：列出每玩家所有技能的施法次数 (来自 ability.hits)。"""

    limitation = ("施法数据来自 ability.hits 聚合统计 (非独立施法事件)。"
                  "无施法时间戳，无法分析爆发对齐时机。")

    def build_players(conn, code):
        rows = conn.execute("""
            SELECT p.name, p.class, p.spec,
                   a.name as ability_name, a.spell_id, a.hits as cast_count, a.amount
            FROM player p
            JOIN ability a ON a.player_id = p.id
            WHERE p.report_code = ?
            ORDER BY p.name, a.hits DESC
        """, (code,)).fetchall()

        player_map = {}
        unmapped = []
        for r in rows:
            name = r["name"]
            if name not in player_map:
                player_map[name] = {
                    "name": name,
                    "class": r["class"],
                    "spec": r["spec"],
                    "all_abilities": [],
                }
            spell_id = r["spell_id"]
            ability_name = r["ability_name"]
            raw_hits = r["cast_count"] or 0
            raw_amount = r["amount"] or 0
            # hits=0 但 damage>0 → V1 API 漏算 (DoT/通道技能常见), 标记为"使用过"
            eff_casts = raw_hits if raw_hits > 0 else (1 if raw_amount > 0 else 0)
            if spell_id == 0 or not ability_name:
                unmapped.append({
                    "spell_id": spell_id,
                    "name": ability_name or "",
                    "cast_count": eff_casts,
                })
            player_map[name]["all_abilities"].append({
                "spell_id": spell_id,
                "name": ability_name,
                "cast_count": eff_casts,
                "damage_amount": raw_amount,
            })
        return list(player_map.values()), unmapped

    our_players, our_unmapped = build_players(our_conn, our_code)
    top_players, top_unmapped = build_players(top_conn, top_code)

    return {
        "available": True,
        "limitation": limitation,
        "our_players": our_players,
        "top_players": top_players,
        "unmapped_spells": {
            "our": our_unmapped,
            "top": top_unmapped,
        },
    }


# ── 第 4 节: 死亡与承伤 ────────────────────────────────────────────


def compute_deaths_and_damage(our_conn: sqlite3.Connection, our_code: str,
                               top_conn: sqlite3.Connection, top_code: str) -> dict:
    """死亡 + 打断。无 damage 事件，无死前伤害序列。"""

    def build_side(conn, code):
        # event.timestamp 已是相对于报告开始的 ms (与 fight.start_time 同基准)
        # 直接除以 1000 转为秒即可

        # 死亡事件
        death_rows = conn.execute("""
            SELECT timestamp, source, ability_name, ability_id
            FROM event
            WHERE report_code = ? AND type = 'death'
            ORDER BY timestamp
        """, (code,)).fetchall()

        deaths = []
        for d in death_rows:
            ts = d["timestamp"]
            deaths.append({
                "player": d["source"],
                "relative_sec": round(ts / 1000, 1),
                "killing_ability": d["ability_name"],
                "killing_spell_id": d["ability_id"],
                "pre_death_damage_5s": {
                    "available": False,
                    "note": ("无 damage 事件 (event.type='damage')。"
                             "V1 API table 端点不提供 damage 事件详情。"),
                },
            })

        # 打断事件
        int_rows = conn.execute("""
            SELECT timestamp, source, target, ability_name, ability_id
            FROM event
            WHERE report_code = ? AND type = 'interrupt'
            ORDER BY timestamp
        """, (code,)).fetchall()

        by_player = defaultdict(int)
        by_player = defaultdict(int)
        by_ability = defaultdict(lambda: {"ability_name": "", "spell_id": 0, "count": 0})
        for ir in int_rows:
            by_player[ir["source"]] += 1
            key = ir["ability_id"]
            by_ability[key]["count"] += 1
            by_ability[key]["ability_name"] = ir["ability_name"]
            by_ability[key]["spell_id"] = key

        interrupts = {
            "available": True,
            "total": len(int_rows),
            "by_player": [
                {"player": p, "count": c}
                for p, c in sorted(by_player.items(), key=lambda x: -x[1])
            ],
            "by_ability": sorted(
                by_ability.values(),
                key=lambda x: x["count"],
                reverse=True,
            ),
        }

        return {
            "deaths": deaths,
            "interrupts": interrupts,
            "total_npc_casts": {
                "available": False,
                "note": "无 cast 事件，无法统计 NPC 施法次数。",
            },
        }

    return {
        "our": build_side(our_conn, our_code),
        "top": build_side(top_conn, top_code),
    }


# ── 第 5 节: 路线与时间轴 ──────────────────────────────────────────


def compute_route_timeline(our_conn: sqlite3.Connection, our_code: str,
                            top_conn: sqlite3.Connection, top_code: str) -> dict:
    """路线时间轴：fight 表时间线。NPC 无按 fight 分组。"""

    def build_side(conn, code):
        start_ms, _ = get_time_base(conn, code)

        fight_rows = conn.execute("""
            SELECT fight_id, name, kill, difficulty, start_time, end_time, percentage
            FROM fight
            WHERE report_code = ?
            ORDER BY start_time
        """, (code,)).fetchall()

        # 所有 NPC (全局)
        npc_rows = conn.execute("""
            SELECT name, npc_id, type, COUNT(*) as count
            FROM npc
            WHERE report_code = ?
            GROUP BY name, npc_id
            ORDER BY name
        """, (code,)).fetchall()

        all_npcs = [{"name": n["name"], "npc_id": n["npc_id"],
                      "type": n["type"]} for n in npc_rows]

        fights = []
        boss_list = []
        total_duration = 0
        boss_duration = 0

        for f in fight_rows:
            dur = safe_sec(f["end_time"] - f["start_time"])
            is_boss = f["difficulty"] == "Mythic+"
            total_duration += dur
            if is_boss:
                boss_duration += dur
                boss_list.append(f["name"])

            fights.append({
                "fight_id": f["fight_id"],
                "name": f["name"] or "Unnamed Fight",
                "is_boss": is_boss,
                "kill": bool(f["kill"]),
                "start_rel_sec": rel_sec(f["start_time"], start_ms),
                "end_rel_sec": rel_sec(f["end_time"], start_ms),
                "duration_sec": dur,
                "npcs": {
                    "available": False,
                    "note": "NPC 表 fight_id=1 (聚合数据)，无法按战斗分组。",
                },
            })

        return {
            "fights": fights,
            "npcs_global": {
                "available": True,
                "note": "NPC 数据为全副本聚合 (未按战斗分组)。",
                "npcs": all_npcs,
            },
            "boss_time_pct": round(boss_duration / total_duration * 100, 1) if total_duration > 0 else 0,
            "trash_time_pct": round((total_duration - boss_duration) / total_duration * 100, 1) if total_duration > 0 else 0,
            "boss_order": boss_list,
        }

    our_side = build_side(our_conn, our_code)
    top_side = build_side(top_conn, top_code)

    # Boss 顺序比较
    our_order = our_side["boss_order"]
    top_order = top_side["boss_order"]
    shared = [b for b in our_order if b in top_order]
    our_only = [b for b in our_order if b not in top_order]
    top_only = [b for b in top_order if b not in our_order]

    return {
        "our": our_side,
        "top": top_side,
        "boss_order_match": our_order == top_order,
        "boss_order_diff": {
            "our_only": our_only,
            "top_only": top_only,
            "shared": shared,
        },
    }


# ── 第 6 节: 资源流转 ──────────────────────────────────────────────


def compute_resource_cycling(our_conn: sqlite3.Connection, our_code: str,
                              top_conn: sqlite3.Connection, top_code: str) -> dict:
    """资源流转：V1 API 无 resource 事件，始终不可用。"""
    return {
        "available": False,
        "note": ("V1 API /report/tables/resources/ 端点返回空响应。"
                 "资源流转分析需要 V2 API 或 GraphQL 端点。"),
    }


# ── 第 7 节: Buff 与增益覆盖 ──────────────────────────────────────


def compute_buff_coverage(our_conn: sqlite3.Connection, our_code: str,
                           top_conn: sqlite3.Connection, top_code: str) -> dict:
    """Buff 覆盖率 + 同名专精 buff 差异。"""

    limitation = ("Buff 数据为队伍级别 (V1 buffs 端点不按玩家分组)。"
                  "同队所有玩家共享相同的 buff 列表。")

    def build_players(conn, code):
        rows = conn.execute("""
            SELECT p.name, p.spec, a.name as aura_name, a.spell_id, a.uptime_pct
            FROM player p
            JOIN aura a ON a.player_id = p.id
            WHERE p.report_code = ?
            ORDER BY p.name, a.uptime_pct DESC
        """, (code,)).fetchall()

        player_map = {}
        for r in rows:
            name = r["name"]
            if name not in player_map:
                player_map[name] = {
                    "name": name,
                    "spec": r["spec"],
                    "damage_total": 0,
                    "auras": [],
                }
            player_map[name]["auras"].append({
                "name": r["aura_name"],
                "spell_id": r["spell_id"],
                "uptime_pct": r["uptime_pct"],
            })
        return list(player_map.values())

    our_players = build_players(our_conn, our_code)
    top_players = build_players(top_conn, top_code)

    # 同名专精配对 buff 差异
    pairs_list = same_spec_pairs(our_players, top_players)
    buff_diffs = []
    for pair in pairs_list:
        if not pair["our"] or not pair["top"]:
            continue
        our_name = pair["our"]["name"]
        top_name = pair["top"]["name"]
        our_auras = {}
        top_auras = {}
        for p in our_players:
            if p["name"] == our_name:
                our_auras = {a["spell_id"]: a["uptime_pct"] for a in p["auras"]}
                break
        for p in top_players:
            if p["name"] == top_name:
                top_auras = {a["spell_id"]: a["uptime_pct"] for a in p["auras"]}
                break

        if not our_auras or not top_auras:
            continue

        # 计算差值，取 Top 8（过滤掉单边独有的消耗品/团队阵容 buff）
        diffs = []
        all_spell_ids = set(list(our_auras.keys()) + list(top_auras.keys()))
        for sid in all_spell_ids:
            o = our_auras.get(sid, 0)
            t = top_auras.get(sid, 0)
            diffs.append({
                "spell_id": sid,
                "our_pct": o,
                "top_pct": t,
                "diff": round(o - t, 1),
            })

        # 获取 spell_id → name 映射 (从双方玩家的 auras)
        name_map = {}
        for p in our_players + top_players:
            for a in p["auras"]:
                sid = a["spell_id"]
                if sid not in name_map:
                    name_map[sid] = a["name"]
        for d in diffs:
            d["aura_name"] = name_map.get(d["spell_id"], "")

        # ── 过滤：排除单边独有的 buff（消耗品/团队阵容差异）──
        # 若某一方覆盖率为 0，说明是该方独有的合剂/凡图斯符文/食物/职业光环，
        # 不是操作差异，不应占据 Top N 位置。
        combat_relevant = [d for d in diffs if d["our_pct"] > 0 and d["top_pct"] > 0]
        diffs = combat_relevant if combat_relevant else diffs  # 兜底：无交集则保留全部

        diffs.sort(key=lambda x: abs(x["diff"]), reverse=True)
        buff_diffs.append({
            "spec": pair["spec"],
            "our_player": our_name,
            "top_player": top_name,
            "top_diffs": diffs[:8],  # 从 5 扩到 8，过滤后更有空间
        })

    return {
        "available": True,
        "limitation": limitation,
        "our_players": our_players,
        "top_players": top_players,
        "same_spec_buff_diff": buff_diffs,
    }


# ── 第 8 节: 汇总指标 ──────────────────────────────────────────────


def compute_summary(our_conn: sqlite3.Connection, our_code: str,
                     top_conn: sqlite3.Connection, top_code: str) -> dict:
    """汇总指标：全局聚合 + DPS 比值。"""

    def build_side(conn, code):
        start_ms, end_ms = get_time_base(conn, code)
        duration_sec = round((end_ms - start_ms) / 1000, 1)

        total_damage = conn.execute(
            "SELECT COALESCE(SUM(damage_total), 0) FROM player WHERE report_code=?",
            (code,)
        ).fetchone()[0]
        total_healing = conn.execute(
            "SELECT COALESCE(SUM(heal_total), 0) FROM player WHERE report_code=?",
            (code,)
        ).fetchone()[0]
        total_deaths = conn.execute(
            "SELECT COUNT(*) FROM event WHERE report_code=? AND type='death'",
            (code,)
        ).fetchone()[0]
        avg_ilvl = conn.execute(
            "SELECT COALESCE(AVG(ilvl), 0) FROM player WHERE report_code=?",
            (code,)
        ).fetchone()[0]

        return {
            "total_damage": total_damage,
            "total_healing": total_healing,
            "total_deaths": total_deaths,
            "avg_ilvl": round(avg_ilvl, 1),
            "total_duration_sec": duration_sec,
        }

    our_side = build_side(our_conn, our_code)
    top_side = build_side(top_conn, top_code)

    # DPS 比值
    our_dps_rows = our_conn.execute(
        "SELECT name, spec, dps, damage_total FROM player WHERE report_code=?",
        (our_code,)
    ).fetchall()
    top_dps_rows = top_conn.execute(
        "SELECT name, spec, dps, damage_total FROM player WHERE report_code=?",
        (top_code,)
    ).fetchall()

    # 同名专精配对 (用 damage_total 排序，确保同专精多玩家时排序稳定)
    our_players_list = [
        {"name": r["name"], "spec": r["spec"], "damage_total": r["damage_total"]}
        for r in our_dps_rows
    ]
    top_players_list = [
        {"name": r["name"], "spec": r["spec"], "damage_total": r["damage_total"]}
        for r in top_dps_rows
    ]

    # name→dps 查找
    our_dps_map = {r["name"]: r["dps"] for r in our_dps_rows}
    top_dps_map = {r["name"]: r["dps"] for r in top_dps_rows}

    pairs = same_spec_pairs(our_players_list, top_players_list)

    dps_ratios = []
    our_total_dps = 0
    top_total_dps = 0
    for pair in pairs:
        if not pair["our"] or not pair["top"]:
            continue
        o_name = pair["our"]["name"]
        t_name = pair["top"]["name"]
        o_dps = our_dps_map.get(o_name, 0) or 0
        t_dps = top_dps_map.get(t_name, 0) or 0
        our_total_dps += o_dps
        top_total_dps += t_dps
        dps_ratios.append({
            "spec": pair["spec"],
            "our_player": o_name,
            "our_dps": o_dps,
            "top_player": t_name,
            "top_dps": t_dps,
            "ratio": round(o_dps / t_dps, 3) if t_dps > 0 else None,
        })

    return {
        "our": our_side,
        "top": top_side,
        "dps_ratios": dps_ratios,
        "overall_dps_ratio": round(our_total_dps / top_total_dps, 3) if top_total_dps > 0 else None,
    }


# ── 主入口 ──────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="comparison_engine.py — 读取两份 wcl_parser SQLite 数据库，"
                    "输出 8 节结构化 JSON 比较结果。"
    )
    parser.add_argument("--our-db", required=True, help="我方 DB 路径")
    parser.add_argument("--our-code", required=True, help="我方报告代码")
    parser.add_argument("--top-db", required=True, help="顶层 DB 路径")
    parser.add_argument("--top-code", required=True, help="顶层报告代码")
    parser.add_argument("--output", default="comparison_result.json",
                        help="输出 JSON 路径 (默认: comparison_result.json)")
    args = parser.parse_args()

    # 加载 DB
    our_conn = load_db(args.our_db, args.our_code)
    top_conn = load_db(args.top_db, args.top_code)

    # 组装输出
    result = {}
    sections = [
        ("meta", lambda: read_meta(our_conn, args.our_code, top_conn, args.top_code, args)),
        ("summary", lambda: compute_summary(our_conn, args.our_code, top_conn, args.top_code)),
        ("damage_composition", lambda: compute_damage_composition(our_conn, args.our_code, top_conn, args.top_code)),
        ("cast_activity", lambda: compute_cast_activity(our_conn, args.our_code, top_conn, args.top_code)),
        ("cooldown_usage", lambda: compute_cooldown_usage(our_conn, args.our_code, top_conn, args.top_code)),
        ("deaths_and_damage", lambda: compute_deaths_and_damage(our_conn, args.our_code, top_conn, args.top_code)),
        ("route_timeline", lambda: compute_route_timeline(our_conn, args.our_code, top_conn, args.top_code)),
        ("resource_cycling", lambda: compute_resource_cycling(our_conn, args.our_code, top_conn, args.top_code)),
        ("buff_coverage", lambda: compute_buff_coverage(our_conn, args.our_code, top_conn, args.top_code)),
    ]

    for key, func in sections:
        try:
            result[key] = func()
        except Exception as e:
            print(f"警告: 节 '{key}' 计算失败: {e}", file=sys.stderr)
            result[key] = {"available": False, "error": str(e)}

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(_safe_filter(result), f, ensure_ascii=False, indent=2)

    print(f"比较结果已写入: {args.output}")
    our_conn.close()
    top_conn.close()


if __name__ == "__main__":
    main()
