#!/usr/bin/env python3
"""
V1 API → SQLite 数据管道

通过 WCL V1 API 的结构化 table 端点获取汇总数据，聚合写入 wcl_parser 格式的 SQLite。

用法:
    python v1_pipeline.py <报告代码> [--db-dir /path/to/wcl_db] [--api-key KEY]

示例:
    python v1_pipeline.py qavZzKjfyNhmF7V1
    python v1_pipeline.py qavZzKjfyNhmF7V1 --db-dir ./test_db
"""

import sys
import os
import json
import time
import argparse
import sqlite3
from collections import defaultdict

import requests

from wcl_parser.storage.writer import SQLiteWriter
from wcl_parser.storage.schema import TABLES, INDEXES

# Spec ID → (Class, Spec) 映射 (12.0 Midnight)
SPEC_MAP = {
    250:  ("Death Knight", "Blood"),       251: ("Death Knight", "Frost"),
    252:  ("Death Knight", "Unholy"),       577: ("Demon Hunter", "Havoc"),
    581:  ("Demon Hunter", "Vengeance"),    102: ("Druid", "Balance"),
    103:  ("Druid", "Feral"),               104: ("Druid", "Guardian"),
    105:  ("Druid", "Restoration"),         1467: ("Evoker", "Devastation"),
    1468: ("Evoker", "Preservation"),       253: ("Hunter", "Beast Mastery"),
    254:  ("Hunter", "Marksmanship"),       255: ("Hunter", "Survival"),
    62:   ("Mage", "Arcane"),               63: ("Mage", "Fire"),
    64:   ("Mage", "Frost"),                268: ("Monk", "Brewmaster"),
    269:  ("Monk", "Windwalker"),           270: ("Monk", "Mistweaver"),
    65:   ("Paladin", "Holy"),              66: ("Paladin", "Protection"),
    70:   ("Paladin", "Retribution"),       256: ("Priest", "Discipline"),
    257:  ("Priest", "Holy"),               258: ("Priest", "Shadow"),
    259:  ("Rogue", "Assassination"),       260: ("Rogue", "Outlaw"),
    261:  ("Rogue", "Subtlety"),            262: ("Shaman", "Elemental"),
    263:  ("Shaman", "Enhancement"),        264: ("Shaman", "Restoration"),
    265:  ("Warlock", "Affliction"),        266: ("Warlock", "Demonology"),
    267:  ("Warlock", "Destruction"),       71: ("Warrior", "Arms"),
    72:   ("Warrior", "Fury"),              73: ("Warrior", "Protection"),
}

# 英雄天赋检测: talentTree 节点 ID → 英雄天赋名
# 通过 combatantInfo.talentTree 的节点 ID 判断，同时用 aura 表 spell_id 交叉验证
HERO_TALENT_TREE_MAP = {
    # Warrior
    112121: "巨神兵(Colossus)",     112126: "巨神兵(Colossus)",
    112135: "巨神兵(Colossus)",     112144: "巨神兵(Colossus)",
    112122: "屠戮者(Slayer)",       112128: "屠戮者(Slayer)",
    112131: "屠戮者(Slayer)",       112145: "屠戮者(Slayer)",
    112123: "山丘领主(Thane)",      112129: "山丘领主(Thane)",
    112134: "山丘领主(Thane)",      112146: "山丘领主(Thane)",
}

def detect_hero_talent(spec: str, talent_tree: list) -> str:
    """从 talentTree 和 spec 解析英雄天赋名"""
    if not talent_tree:
        return ""
    for node in talent_tree:
        nid = node.get("id", 0)
        if nid in HERO_TALENT_TREE_MAP:
            return HERO_TALENT_TREE_MAP[nid]
    return ""


# icon spec 名称校正: V1 API 偶尔返回错误的 class 部分
# "DemonHunter-Devourer" → DH 第3专精 噬灭（Devourer），非唤魔师
# 当前 WCL icon 中 "Devourer" 已正确对应 DemonHunter，无需校正
ICON_CLASS_FIX = {
    # 已无需要校正的条目（Devourer 保持为 DemonHunter）
}

# icon spec 名称 → 标准专精名映射
ICON_SPEC_FIX = {
    # "Devourer" 已是标准专精名（恶魔猎手 噬灭），无需映射到其他名称
}

V1_BASE = "https://www.warcraftlogs.com/v1"
TABLE_TYPES = [
    "damage-done", "healing", "damage-taken", "summary",
    "casts", "deaths", "interrupts", "buffs", "resources",
]


class V1Client:
    """V1 API 请求封装 (限速 + 重试)"""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "wow-trial-v1/1.0"})
        self._count = 0

    def _get(self, path: str, params: dict = None) -> dict:
        if params is None:
            params = {}
        params["api_key"] = self.api_key
        url = f"{V1_BASE}{path}"

        for attempt in range(3):
            try:
                resp = self.session.get(url, params=params, timeout=60)
                if resp.status_code == 429:
                    time.sleep(2 ** attempt)
                    continue
                resp.raise_for_status()
                self._count += 1
                text = resp.text.strip()
                if not text:
                    return {}
                return resp.json()
            except Exception as e:
                if attempt < 2:
                    time.sleep(1)
                    continue
                raise RuntimeError(f"API 错误 ({url}): {e}") from e

    def fetch_fights(self, report_code: str) -> dict:
        return self._get(f"/report/fights/{report_code}", {"translate": "true"})

    def fetch_table(self, report_code: str, table_type: str,
                    source_id: int = None, start_time: int = 0,
                    end_time: int = 999999999999, by: str = None) -> dict:
        params = {"start": start_time, "end": end_time}
        if source_id is not None:
            params["sourceid"] = source_id
        if by is not None:
            params["by"] = by
        return self._get(f"/report/tables/{table_type}/{report_code}", params)


def parse_class_spec(entry: dict) -> tuple:
    """从 table entry 解析 (class, spec)，含 icon 名称校正"""
    class_name = entry.get("type", "")
    icon = entry.get("icon", "")
    # icon 优先: "Monk-Brewmaster" → class=Monk, spec=Brewmaster
    if "-" in icon:
        parts = icon.split("-", 1)
        class_name = parts[0]
        spec_name = parts[1]
        # 校正 V1 API 的 icon class 错误
        if spec_name in ICON_CLASS_FIX:
            class_name = ICON_CLASS_FIX[spec_name]
        # 校正 icon spec 名称
        if spec_name in ICON_SPEC_FIX:
            spec_name = ICON_SPEC_FIX[spec_name]
    else:
        spec_name = ""
    return class_name, spec_name


def build_pipeline(report_code: str, api_key: str, db_dir: str,
                   fight_id: int = None) -> str:
    """
    完整管道: 获取 → 聚合 → 写入 SQLite

    返回: db_path
    """
    client = V1Client(api_key)
    writer = SQLiteWriter(db_dir=db_dir)

    print(f"[1/5] 获取报告元数据...")
    meta = client.fetch_fights(report_code)
    report_title = meta.get("title", "")
    report_start = meta.get("start", 0)
    report_end = meta.get("end", 0)
    report_zone = str(meta.get("zone", ""))
    report_owner = meta.get("owner", "")

    # 构建 ID 映射
    friendlies = {}   # id → {name, class, server, icon}
    for f in meta.get("friendlies", []):
        cls, _ = parse_class_spec(f)
        friendlies[f["id"]] = {
            "name": f["name"], "class": cls,
            "server": f.get("server", ""), "icon": f.get("icon", ""),
        }

    enemies = {}  # id → {name, type}
    for e in meta.get("enemies", []):
        enemies[e["id"]] = {"name": e["name"], "type": e.get("type", "add")}

    # dungeonPulls → fight 列表
    fights = meta.get("fights", [])
    dungeon_pulls = []
    keystone_level = 0
    keystone_time = 0
    keystone_timed = False
    for f in fights:
        if f.get("dungeonPulls"):
            dungeon_pulls = f["dungeonPulls"]
            keystone_level = f.get("keystoneLevel", 0)
            keystone_time = f.get("completionTime", 0)
            keystone_timed = f.get("kill", False)
            break

    if not dungeon_pulls:
        # 非 M+ 报告，直接用 fights
        dungeon_pulls = [{"id": f["id"], "name": f.get("name", ""),
                          "start_time": f["start_time"], "end_time": f["end_time"],
                          "kill": f.get("kill", False)} for f in fights]

    print(f"  报告: {report_title}, {len(friendlies)} 名玩家, {len(dungeon_pulls)} 个 pull")

    # ── 按 fight_id 过滤 ──────────────────────────────────────────────
    table_start, table_end = 0, 999999999999
    if fight_id is not None:
        # 先查顶层 fights（WCL fight ID），再查子 dungeon_pulls
        matched = [f for f in fights if f.get("id") == fight_id]
        if not matched:
            matched = [p for p in dungeon_pulls if p.get("id") == fight_id]
        if not matched:
            avail_pulls = [p.get('id') for p in dungeon_pulls[:10]]
            avail_fights = [f.get('id') for f in fights[:5] if f.get('boss', 0) > 0]
            raise ValueError(
                f"未找到 fight_id={fight_id} "
                f"(pulls: {avail_pulls}, boss fights: {avail_fights}...)")
        target = matched[0]
        # 保存副本名（target 后续会被重写）
        _dungeon_name = target.get("name", "")
        # 更新 keystone 元数据（可能不同于默认的 dungeonPulls fight）
        keystone_level = target.get("keystoneLevel", keystone_level)
        keystone_time = target.get("completionTime", keystone_time)
        keystone_timed = target.get("kill", keystone_timed)
        sub_pulls = target.get("dungeonPulls", [])
        if sub_pulls:
            table_start = min(p["start_time"] for p in sub_pulls)
            table_end = max(p["end_time"] for p in sub_pulls)
            dungeon_pulls = sub_pulls
            name = target.get("name", "") or f"Fight #{fight_id}"
            print(f"  🎯 限定 fight #{fight_id}: {name} "
                  f"({len(dungeon_pulls)} pulls, {(table_end-table_start)/1000:.0f}s)")
        else:
            table_start = target["start_time"]
            table_end = target["end_time"]
            dungeon_pulls = [{"id": target["id"], "name": target.get("name", ""),
                              "start_time": target["start_time"],
                              "end_time": target["end_time"],
                              "kill": target.get("kill", False),
                              "boss": target.get("boss", 0)}]
            print(f"  🎯 限定 fight #{fight_id}: {target.get('name','?')} "
                  f"({(table_end-table_start)/1000:.0f}s)")
        report_start = table_start
        report_end = table_end
    elif dungeon_pulls:
        # [修复] 无 --fight-id 时自动检测 M+ 时间窗口
        table_start = min(p["start_time"] for p in dungeon_pulls)
        table_end = max(p["end_time"] for p in dungeon_pulls)
        print(f"  自动检测 M+ 时间窗口: {(table_end-table_start)/1000:.0f}s "
              f"({len(dungeon_pulls)} pulls)")

    # ── 获取各 table 数据 ─────────────────────────────────────────────
    print(f"[2/5] 获取 table 数据...")
    tables = {}
    for ttype in TABLE_TYPES:
        try:
            data = client.fetch_table(report_code, ttype,
                                       start_time=table_start, end_time=table_end)
            tables[ttype] = data
            size = len(str(data))
            print(f"  {ttype}: {size/1024:.0f}KB")
        except Exception as e:
            print(f"  {ttype}: 失败 ({e})")
            tables[ttype] = {}

    # ── 聚合玩家数据 ──────────────────────────────────────────────────
    print(f"[3/5] 聚合玩家数据...")

    dd = tables.get("damage-done", {})
    heal = tables.get("healing", {})
    summary = tables.get("summary", {})
    casts_data = tables.get("casts", {})
    buffs_data = tables.get("buffs", {})

    dd_entries = dd.get("entries", [])
    heal_entries = heal.get("entries", [])
    summary_dd = {e["name"]: e["total"] for e in summary.get("damageDone", [])}
    summary_heal = {e["name"]: e["total"] for e in summary.get("healingDone", [])}

    # 构建 healer totals 索引
    heal_totals = {}
    for he in heal_entries:
        heal_totals[he["name"]] = he.get("total", 0)

    # ── 逐玩家获取完整技能列表 (by=ability 突破 Top 5 截断) ──────
    print(f"    [增强] 逐玩家获取完整技能列表...")
    player_name_to_id = {}
    for fid, finfo in friendlies.items():
        player_name_to_id[finfo["name"]] = int(fid)

    # 从全局 dd_entries 确定在队玩家
    team_players = []
    for e in dd_entries:
        nm = e["name"]
        if nm in player_name_to_id:
            team_players.append((nm, player_name_to_id[nm], e))

    new_dd_entries = []
    cast_counts = {}
    cast_abilities = {}
    for pname, pid, orig_entry in team_players:
        try:
            # damage-done: by=ability 返回每个技能作为独立 entry
            dd_data = client.fetch_table(report_code, "damage-done",
                                          source_id=pid, start_time=table_start,
                                          end_time=table_end, by="ability")
            abilities = []
            for ab_entry in dd_data.get("entries", []):
                ab_total = ab_entry.get("total", 0)
                if ab_total > 0:  # 只保留有伤害的技能
                    abilities.append({
                        "name": ab_entry.get("name", ""),
                        "guid": ab_entry.get("guid", 0),
                        "total": ab_total,
                        "type": ab_entry.get("type", ""),
                    })
            new_entry = {
                "name": pname,
                "total": orig_entry.get("total", sum(a["total"] for a in abilities)),
                "itemLevel": orig_entry.get("itemLevel", 0),
                "activeTime": orig_entry.get("activeTime", 0),
                "type": orig_entry.get("type", ""),
                "icon": orig_entry.get("icon", ""),
                "abilities": abilities,
            }
            new_dd_entries.append(new_entry)

            # casts: by=ability 同样获取完整列表
            cast_data = client.fetch_table(report_code, "casts",
                                            source_id=pid, start_time=table_start,
                                            end_time=table_end, by="ability")
            cast_abs = []
            for ca in cast_data.get("entries", []):
                ca_total = ca.get("total", 0)
                if ca_total > 0:
                    cast_abs.append({
                        "name": ca.get("name", ""),
                        "guid": ca.get("guid", 0),
                        "total": ca_total,
                        "type": ca.get("type", ""),
                    })
            cast_abilities[pname] = cast_abs
            cast_counts[pname] = sum(ca.get("total", 0) for ca in cast_abs)
        except Exception as e:
            # fallback: 使用原始数据
            print(f"      ⚠️ {pname}: 逐玩家查询失败 ({e})，回退原始数据")
            new_dd_entries.append(orig_entry)
            orig_casts = next((ce for ce in casts_data.get("entries", [])
                               if ce["name"] == pname), None)
            if orig_casts:
                cast_counts[pname] = orig_casts.get("total", 0)
                cast_abilities[pname] = orig_casts.get("abilities", [])

    dd_entries = new_dd_entries if new_dd_entries else dd_entries

    # 构建 player_auras (从 buffs 按 source 过滤 - 若可用)
    # buffs 端点不按玩家分组，这里按队伍级别存储
    buff_auras = buffs_data.get("auras", [])
    buff_total_time = buffs_data.get("totalTime", 1)

    # ── 从 summary 预提取 combatantInfo (属性/装备/药水/英雄天赋) ──
    _hero_talent = {}
    _potion_use = {}
    _hs_use = {}
    _player_stats = {}   # name → {strength, crit, haste, mastery, vers}
    _player_gear = {}    # name → [{slot, name, ilvl, quality, set_id, set_name}]
    
    for role in ["dps", "healers", "tanks"]:
        for pd in summary.get("playerDetails", {}).get(role, []):
            nm = pd["name"]
            _potion_use[nm] = pd.get("potionUse", 0)
            _hs_use[nm] = pd.get("healthstoneUse", 0)
            ci = pd.get("combatantInfo", {})
            if ci:
                # 属性
                stats_raw = ci.get("stats", {})
                _player_stats[nm] = {
                    "strength": stats_raw.get("Strength", {}).get("min", 0),
                    "agility": stats_raw.get("Agility", {}).get("min", 0),
                    "intellect": stats_raw.get("Intellect", {}).get("min", 0),
                    "stamina": stats_raw.get("Stamina", {}).get("min", 0),
                    "crit": stats_raw.get("Crit", {}).get("min", 0),
                    "haste": stats_raw.get("Haste", {}).get("min", 0),
                    "mastery": stats_raw.get("Mastery", {}).get("min", 0),
                    "versatility": stats_raw.get("Versatility", {}).get("min", 0),
                    "leech": stats_raw.get("Leech", {}).get("min", 0),
                }
                # 装备
                gear_list = []
                for g in ci.get("gear", []):
                    if g.get("itemLevel", 0) > 0:
                        # 宝石: 提取 id+itemLevel
                        gems_raw = g.get("gems", [])
                        gems = [{"id": gm.get("id", 0), "ilvl": gm.get("itemLevel", 0)} for gm in gems_raw] if gems_raw else []
                        gear_list.append({
                            "slot": g.get("slot", 0),
                            "name": g.get("name", ""),
                            "ilvl": g.get("itemLevel", 0),
                            "quality": g.get("quality", 1),
                            "set_id": g.get("setID", 0),
                            "set_name": g.get("setName", ""),
                            "perm_enchant_id": g.get("permanentEnchant", 0),
                            "perm_enchant_name": g.get("permanentEnchantName", ""),
                            "temp_enchant_id": g.get("temporaryEnchant", 0),
                            "temp_enchant_name": g.get("temporaryEnchantName", ""),
                            "gems": gems,
                        })
                _player_gear[nm] = gear_list
                # 英雄天赋
                tree = ci.get("talentTree", [])
                ht = detect_hero_talent("", tree)
                if ht:
                    _hero_talent[nm] = ht
    
    player_list = []
    ability_rows = []   # (player_name, ability_dict)[]
    aura_rows = []      # (player_name, aura_dict)[]

    # 构建玩家名集合 (从 friendlies)
    player_names = {f["name"] for f in friendlies.values()}

    for entry in dd_entries:
        name = entry["name"]
        # 只保留 friendlies 中的真正玩家
        if name not in player_names:
            continue

        class_name, spec_name = parse_class_spec(entry)
        # 补充 spec (从 combatantInfo)
        if not spec_name:
            for role in ["dps", "healers", "tanks"]:
                for pd in summary.get("playerDetails", {}).get(role, []):
                    if pd["name"] == name:
                        ci = pd.get("combatantInfo", {})
                        specs = ci.get("specIDs", [])
                        if specs:
                            _, spec_name = SPEC_MAP.get(specs[0], (class_name, ""))
                        break

        ilvl = entry.get("itemLevel", 0) or 0
        # 补充 ilvl: 从 healing / summary / playerDetails
        if not ilvl:
            for he in heal_entries:
                if he["name"] == name:
                    ilvl = he.get("itemLevel", 0) or 0
                    break
        if not ilvl:
            for role in ["dps", "healers", "tanks"]:
                for pd in summary.get("playerDetails", {}).get(role, []):
                    if pd["name"] == name:
                        ilvl = pd.get("maxItemLevel", pd.get("minItemLevel", 0)) or 0
                        break
        server = ""
        for f in friendlies.values():
            if f["name"] == name:
                server = f["server"]
                break

        damage_total = entry.get("total", 0)
        heal_total = heal_totals.get(name, summary_heal.get(name, 0))
        active_time = entry.get("activeTime", entry.get("activeTimeReduced", 1))
        dps = damage_total / (active_time / 1000) if active_time > 0 else 0

        player_list.append({
            "name": name,
            "class": class_name,
            "spec": spec_name,
            "ilvl": ilvl,
            "server": server,
            "damage_total": damage_total,
            "heal_total": heal_total,
            "parse_pct": cast_counts.get(name, 0),
            "dps": dps,
            "hero_talent": _hero_talent.get(name, ""),
            "potion_use": _potion_use.get(name, 0),
            "healthstone_use": _hs_use.get(name, 0),
            "stats": _player_stats.get(name, {}),
            "gear": _player_gear.get(name, []),
        })

        # Abilities: 合并 damage-done + casts
        abilities = {}
        for ab in entry.get("abilities", []):
            key = ab.get("guid", ab.get("name", ""))
            abilities[key] = {
                "name": ab.get("name", ""),
                "spell_id": ab.get("guid", 0),
                "amount": ab.get("total", 0),
                "hits": 0,
                "crits": 0,
                "miss_pct": 0.0,
            }
        # 补充 damageAbilities 的 hits/crits 数据
        for dab in entry.get("damageAbilities", []):
            key = dab.get("guid", 0)
            if key in abilities:
                abilities[key]["hits"] = dab.get("totalHits", 0)
                abilities[key]["crits"] = dab.get("totalCrits", 0)

        # 合并 casts 端点的施法次数到 ability.hits
        player_casts = cast_abilities.get(name, [])
        for cab in player_casts:
            guid = cab.get("guid", 0)
            if guid in abilities:
                abilities[guid]["hits"] = cab.get("total", 0)
            else:
                abilities[guid] = {
                    "name": cab.get("name", ""),
                    "spell_id": guid,
                    "amount": 0,
                    "hits": cab.get("total", 0),
                    "crits": 0,
                    "miss_pct": 0.0,
                }

        ability_rows.append((name, list(abilities.values())))

        # Auras: 队伍级别 buffs (buffs 端点不按玩家分组)
        # 此处为每个玩家只存储高覆盖率 buff (降低冗余)
        player_auras = []
        for au in buff_auras:
            uptime = au.get("totalUptime", 0)
            pct = (uptime / buff_total_time * 100) if buff_total_time > 0 else 0
            if pct > 30:  # 只保留 >30% 覆盖率的 buff
                player_auras.append({
                    "name": au.get("name", ""),
                    "spell_id": au.get("guid", 0),
                    "uptime_pct": round(pct, 1),
                })
        aura_rows.append((name, player_auras))

    # 补充未在 damage-done 中的治疗者 (仅限 friendlies 中的真正玩家)
    for he in heal_entries:
        name = he["name"]
        if name not in player_names:
            continue
        if any(p["name"] == name for p in player_list):
            continue
        class_name, spec_name = parse_class_spec(he)
        if not spec_name:
            for role in ["healers", "dps", "tanks"]:
                for pd in summary.get("playerDetails", {}).get(role, []):
                    if pd["name"] == name:
                        ci = pd.get("combatantInfo", {})
                        specs = ci.get("specIDs", [])
                        if specs:
                            _, spec_name = SPEC_MAP.get(specs[0], (class_name, ""))
                        break
        server = ""
        for f in friendlies.values():
            if f["name"] == name:
                server = f["server"]
                break
        player_list.append({
            "name": name, "class": class_name, "spec": spec_name,
            "ilvl": he.get("itemLevel", 0), "server": server,
            "damage_total": summary_dd.get(name, 0),
            "heal_total": he.get("total", 0),
            "parse_pct": cast_counts.get(name, 0), "dps": 0,
        })
        # Healer abilities
        habs = {}
        for ab in he.get("abilities", []):
            key = ab.get("guid", ab.get("name", ""))
            habs[key] = {
                "name": ab.get("name", ""),
                "spell_id": ab.get("guid", 0),
                "amount": ab.get("total", 0),
                "hits": 0, "crits": 0, "miss_pct": 0.0,
            }
        # 合并 casts 端点的施法次数到 healer ability.hits
        healer_casts = cast_abilities.get(name, [])
        for cab in healer_casts:
            guid = cab.get("guid", 0)
            if guid in habs:
                habs[guid]["hits"] = cab.get("total", 0)
            else:
                habs[guid] = {
                    "name": cab.get("name", ""),
                    "spell_id": guid,
                    "amount": 0,
                    "hits": cab.get("total", 0),
                    "crits": 0,
                    "miss_pct": 0.0,
                }
        ability_rows.append((name, list(habs.values())))
        aura_rows.append((name, []))

    print(f"  玩家: {len(player_list)}")

    # ── 聚合事件数据 ──────────────────────────────────────────────────
    print(f"[4/5] 聚合事件和 NPC 数据...")

    events = []
    # 死亡事件
    for de in summary.get("deathEvents", []):
        ability = de.get("ability", {})
        events.append({
            "timestamp": de.get("deathTime", 0),
            "type": "death",
            "source": de.get("name", ""),
            "target": "",
            "ability_name": ability.get("name", "") if isinstance(ability, dict) else "",
            "ability_id": ability.get("guid", 0) if isinstance(ability, dict) else 0,
            "amount": 0, "hit_type": "", "absorbed": 0, "resisted": 0,
        })

    # 打断事件
    interrupts_data = tables.get("interrupts", {})
    for ie in interrupts_data.get("entries", []):
        for entry_item in ie.get("entries", []):
            ability = entry_item.get("ability", entry_item)
            ab_name = entry_item.get("name", "")
            ab_id = entry_item.get("guid", 0)
            ts = entry_item.get("timestamp", 0)
            for detail in entry_item.get("details", []):
                source_name = detail.get("name", "")
                for actor in detail.get("actors", []):
                    target = actor.get("name", "")
                    count = actor.get("total", 0)
                    for _ in range(count):
                        events.append({
                            "timestamp": ts, "type": "interrupt",
                            "source": source_name, "target": target,
                            "ability_name": ab_name, "ability_id": ab_id,
                            "amount": 0, "hit_type": "", "absorbed": 0, "resisted": 0,
                        })

    # ── Cast 事件: 通过 Events API 拉取施法时间轴 ──
    # 为每个玩家拉取其施法事件 (含时间戳)，用于时间轴分析
    fight_start = dungeon_pulls[0]["start_time"] if dungeon_pulls else 0
    fight_end = dungeon_pulls[-1]["end_time"] if dungeon_pulls else 999999999999
    for f in friendlies.values():
        fname = f["name"]
        if fname not in player_names:
            continue
        # 找该玩家的 sourceID
        fid = None
        for fid_key, fv in friendlies.items():
            if fv["name"] == fname:
                fid = fid_key
                break
        if fid is None:
            continue
        try:
            cast_url = f"/report/events/{report_code}"
            cast_params = {
                "start": fight_start, "end": fight_end,
                "sourceid": fid, "type": "cast",
                "translate": "true",
            }
            # 分页循环: nextPageTimestamp 直到没有更多页
            page_count = 0
            max_pages = 20
            while page_count < max_pages:
                cast_data = client._get(cast_url, cast_params)
                cast_events_raw = cast_data.get("events", [])
                for ce in cast_events_raw:
                    ab = ce.get("ability", {})
                    events.append({
                        "timestamp": ce.get("timestamp", 0),
                        "type": "cast",
                        "source": fname,
                        "target": ce.get("target", {}).get("name", ""),
                        "ability_name": ab.get("name", ""),
                        "ability_id": ab.get("guid", 0),
                        "amount": 0, "hit_type": "", "absorbed": 0, "resisted": 0,
                    })
                page_count += 1
                nt = cast_data.get("nextPageTimestamp")
                if not nt:
                    break
                cast_params["start"] = nt
        except Exception:
            pass  # events API 偶尔超时，不阻塞

    print(f"  事件: {len(events)}")

    # ── 聚合 NPC 数据 ────────────────────────────────────────────────
    npc_list = []
    for eid, info in enemies.items():
        npc_list.append({
            "name": info["name"],
            "npc_id": eid,
            "type": info.get("type", "add"),
            "damage_taken": 0,
            "death_time": 0,
        })
    print(f"  NPC: {len(npc_list)}")

    # ── 写入 SQLite (幂等: 先删后写) ──────────────────────────────────
    print(f"[5/5] 写入 SQLite...")
    db_path = writer._db_path(report_code)
    writer.create_tables(db_path)

    with sqlite3.connect(db_path) as conn:
        # 清空该报告现有数据 (防止重复运行导致的数据翻倍)
        conn.execute("DELETE FROM ability WHERE player_id IN (SELECT id FROM player WHERE report_code=?)", (report_code,))
        conn.execute("DELETE FROM aura WHERE player_id IN (SELECT id FROM player WHERE report_code=?)", (report_code,))
        conn.execute("DELETE FROM player_stats WHERE player_id IN (SELECT id FROM player WHERE report_code=?)", (report_code,))
        conn.execute("DELETE FROM player_gear WHERE player_id IN (SELECT id FROM player WHERE report_code=?)", (report_code,))
        conn.execute("DELETE FROM player WHERE report_code=?", (report_code,))
        conn.execute("DELETE FROM event WHERE report_code=?", (report_code,))
        conn.execute("DELETE FROM npc WHERE report_code=?", (report_code,))
        conn.execute("DELETE FROM fight WHERE report_code=?", (report_code,))
        conn.execute("DELETE FROM report WHERE report_code=?", (report_code,))
        # 为旧 DB 补上新增列 (IF NOT EXISTS 不支持, 静默忽略错误)
        try:
            conn.execute("ALTER TABLE report ADD COLUMN dungeon_name TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass
        for col in [("hero_talent", "TEXT DEFAULT ''"), ("potion_use", "INTEGER DEFAULT 0"),
                     ("healthstone_use", "INTEGER DEFAULT 0")]:
            try:
                conn.execute(f"ALTER TABLE player ADD COLUMN {col[0]} {col[1]}")
            except sqlite3.OperationalError:
                pass
        # report
        # 副本名: --fight-id 模式下从 _dungeon_name 获取, 否则从第一个 dungeonPulls 获取
        dungeon_name = _dungeon_name if fight_id is not None else (
            next((f.get("name", "") for f in fights if f.get("dungeonPulls")), "")
        )
        conn.execute("""INSERT OR REPLACE INTO report
            (report_code, title, start_time, end_time, zone, owner, keystone_timed, dungeon_name)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (report_code, report_title, report_start, report_end,
             report_zone, report_owner, 1 if keystone_timed else 0, dungeon_name))

        # fights
        for pull in dungeon_pulls:
            is_boss = pull.get("boss", 0) > 0
            conn.execute("""INSERT OR REPLACE INTO fight
                (report_code, fight_id, name, kill, difficulty, start_time, end_time, percentage,
                 keystone_level, keystone_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (report_code, pull["id"], pull.get("name", ""),
                 1 if pull.get("kill", False) else 0,
                 "Mythic+" if is_boss else "Trash",
                 pull["start_time"], pull["end_time"],
                 100.0 if pull.get("kill", False) else 0.0,
                 keystone_level, keystone_time))

        # players + abilities + auras
        name_to_pid = {}
        for player in player_list:
            cur = conn.execute("""INSERT INTO player
                (report_code, fight_id, name, class, spec, hero_talent, ilvl, server,
                 damage_total, heal_total, parse_pct, dps, potion_use, healthstone_use)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (report_code, 1, player["name"], player["class"],
                 player["spec"], player.get("hero_talent", ""),
                 player["ilvl"], player["server"],
                 player["damage_total"], player["heal_total"],
                 player["parse_pct"], player["dps"],
                 player.get("potion_use", 0), player.get("healthstone_use", 0)))
            name_to_pid[player["name"]] = cur.lastrowid
            
            # 写入 player_stats
            stats = player.get("stats", {})
            if stats:
                conn.execute("""INSERT OR REPLACE INTO player_stats
                    (player_id, strength, agility, intellect, stamina,
                     crit, haste, mastery, versatility, leech)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (cur.lastrowid, stats.get("strength", 0), stats.get("agility", 0),
                     stats.get("intellect", 0), stats.get("stamina", 0),
                     stats.get("crit", 0), stats.get("haste", 0),
                     stats.get("mastery", 0), stats.get("versatility", 0),
                     stats.get("leech", 0)))
            
            # 写入 player_gear
            for g in player.get("gear", []):
                gems_json = json.dumps(g.get("gems", []), ensure_ascii=False)
                conn.execute("""INSERT INTO player_gear
                    (player_id, slot, item_name, item_level, quality, set_id, set_name,
                     perm_enchant_id, perm_enchant_name, temp_enchant_id, temp_enchant_name, gems)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (cur.lastrowid, g["slot"], g["name"], g["ilvl"],
                     g["quality"], g["set_id"], g["set_name"],
                     g.get("perm_enchant_id", 0), g.get("perm_enchant_name", ""),
                     g.get("temp_enchant_id", 0), g.get("temp_enchant_name", ""),
                     gems_json))

        for name, abilities in ability_rows:
            pid = name_to_pid.get(name)
            if not pid:
                continue
            for ab in abilities:
                conn.execute("""INSERT INTO ability
                    (player_id, name, spell_id, amount, hits, crits, miss_pct)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (pid, ab["name"], ab["spell_id"], ab["amount"],
                     ab["hits"], ab["crits"], ab["miss_pct"]))

        for name, auras in aura_rows:
            pid = name_to_pid.get(name)
            if not pid:
                continue
            for au in auras:
                conn.execute("""INSERT INTO aura
                    (player_id, name, spell_id, uptime_pct)
                    VALUES (?, ?, ?, ?)""",
                    (pid, au["name"], au["spell_id"], au["uptime_pct"]))

        # events
        for evt in events:
            conn.execute("""INSERT INTO event
                (report_code, fight_id, timestamp, type, source, target,
                 ability_name, ability_id, amount, hit_type, absorbed, resisted)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (report_code, 1, evt["timestamp"], evt["type"],
                 evt["source"], evt["target"], evt["ability_name"],
                 evt["ability_id"], evt["amount"], evt["hit_type"],
                 evt["absorbed"], evt["resisted"]))

        # npcs
        for npc in npc_list:
            conn.execute("""INSERT OR REPLACE INTO npc
                (report_code, fight_id, name, npc_id, type, damage_taken, death_time)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (report_code, 1, npc["name"], npc["npc_id"],
                 npc["type"], npc["damage_taken"], npc["death_time"]))

        conn.commit()

    print(f"\n写入完成: {db_path}")
    print(f"  report: 1   fight: {len(dungeon_pulls)}")
    print(f"  player: {len(player_list)}   ability: {sum(len(a[1]) for a in ability_rows)}")
    print(f"  aura: {sum(len(a[1]) for a in aura_rows)}   event: {len(events)}")
    print(f"  npc: {len(npc_list)}   API请求: {client._count}")

    return db_path


def main():
    parser = argparse.ArgumentParser(description="V1 API → SQLite 数据管道")
    parser.add_argument("report_code", help="WCL 报告代码")
    parser.add_argument("--api-key", default=None,
                        help="V1 API Key（默认读取 WCL_API_KEY 环境变量）")
    parser.add_argument("--db-dir", default="data/wcl_db",
                        help="SQLite 数据库目录")
    parser.add_argument("--fight-id", type=int, default=None,
                        help="仅处理指定 fight ID（如 23），而非整个报告")
    args = parser.parse_args()

    api_key = args.api_key
    if not api_key:
        from core.config import get_api_key
        api_key = get_api_key()
    db_path = build_pipeline(args.report_code, api_key, args.db_dir, args.fight_id)
    return db_path


if __name__ == "__main__":
    main()
