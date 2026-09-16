#!/usr/bin/env python3
"""
core/xiaoxue_pipeline.py — 小雪评测一键管线

从 WCL 报告代码到所有中间产物的完整流程:
  1. v1_pipeline.py → SQLite DB（含缓存检查）
  2. m2_standalone_summary.py → 4 个 txt
  3. 代码自动提取基准对比数据
  4. 存入 progress.db 快照

用法:
    # 提取清心基准
    PYTHONPATH=. python3 core/xiaoxue_pipeline.py --extract-benchmark <qingxin_report_code>

    # 小雪评测管线
    PYTHONPATH=. python3 core/xiaoxue_pipeline.py <xiaoxue_report_code>

    # 指定 fight_id
    PYTHONPATH=. python3 core/xiaoxue_pipeline.py <report_code> --fight-id 5
"""

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

# ── 路径 ──────────────────────────────────────────────────────────
PROJECT_DIR = Path(__file__).resolve().parent.parent
WCL_DB_DIR = PROJECT_DIR / "data" / "wcl_db"
CACHE_DIR = PROJECT_DIR / "data" / "cache"
XIAOXUE_DIR = PROJECT_DIR / "data" / "xiaoxue"
BENCHMARK_PATH = XIAOXUE_DIR / "qingxin_benchmark_profile.json"
BASELINE_PATH = XIAOXUE_DIR / "baseline_snapshot.json"
V1_PIPELINE = PROJECT_DIR / "core" / "v1_pipeline.py"
M2_SUMMARY = PROJECT_DIR / "core" / "m2_standalone_summary.py"

from core.config import get_api_key as _get_api_key


def _db_exists(report_code: str, db_dir: str | None = None) -> bool:
    """检查 DB 是否已存在且有效。"""
    db_path = Path(db_dir or str(WCL_DB_DIR)) / f"{report_code}.db"
    return db_path.exists() and db_path.stat().st_size > 1000


def _cache_files_exist(report_code: str, cache_dir: str | None = None) -> bool:
    """检查 m2_standalone_summary 的缓存文件是否存在。"""
    cd = Path(cache_dir or str(CACHE_DIR))
    files = [
        cd / f"m2_meta_{report_code}.txt",
        cd / f"m2_group_a_{report_code}.txt",
        cd / f"m2_group_b_{report_code}.txt",
        cd / f"m2_group_c_{report_code}.txt",
    ]
    return all(f.exists() and f.stat().st_size > 10 for f in files)


def _run_v1(report_code: str, db_dir: str | None = None, fight_id: int | None = None) -> str:
    """调用 v1_pipeline.py，返回 db_path。"""
    if db_dir is None:
        db_dir = str(WCL_DB_DIR)

    cmd = [
        sys.executable, str(V1_PIPELINE), report_code,
        "--db-dir", db_dir,
        "--api-key", _get_api_key(),
    ]
    if fight_id is not None:
        cmd.extend(["--fight-id", str(fight_id)])

    subprocess.run(
        cmd, check=True, cwd=str(PROJECT_DIR),
        env={**os.environ, "PYTHONPATH": str(PROJECT_DIR)},
    )
    return str(Path(db_dir) / f"{report_code}.db")


def _run_m2_summary(db_path: str, report_code: str, output_dir: str | None = None):
    """调用 m2_standalone_summary.py。"""
    if output_dir is None:
        output_dir = str(CACHE_DIR)

    cmd = [
        sys.executable, str(M2_SUMMARY), db_path, report_code,
        "--output-dir", output_dir,
    ]
    subprocess.run(
        cmd, check=True, cwd=str(PROJECT_DIR),
        env={**os.environ, "PYTHONPATH": str(PROJECT_DIR)},
    )


# ═══════════════════════════════════════════════════════════════════
# 基准提取
# ═══════════════════════════════════════════════════════════════════


def extract_benchmark(report_code: str, db_dir: str | None = None,
                      fight_id: int | None = None) -> dict:
    """从清心 WCL 日志提取基准 JSON。

    流程: v1_pipeline → DB → SQL 提取 → JSON
    """
    if db_dir is None:
        db_dir = str(WCL_DB_DIR)

    print(f"[extract_benchmark] 抓取清心报告: {report_code}")
    db_path = _run_v1(report_code, db_dir, fight_id)

    # 从 DB 提取技能占比
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    player = conn.execute(
        "SELECT id, name, class, spec, damage_total FROM player "
        "WHERE class='Mage' AND spec='Frost' LIMIT 1"
    ).fetchone()
    if player is None:
        conn.close()
        raise RuntimeError("未找到清心(冰法)的玩家记录")

    pid = player["id"]
    player_damage_total = player["damage_total"]

    # ability表没有pct列，需要从 amount / damage_total 计算
    abilities = conn.execute(
        "SELECT spell_id, name, amount, hits FROM ability WHERE player_id=? ORDER BY amount DESC",
        (pid,),
    ).fetchall()

    # 用 spell_cn_map 解析中文名
    from core.spell_cn_map import resolve as spell_cn

    skill_composition = {}
    for a in abilities:
        cn_name = spell_cn(a["spell_id"], a["name"])
        pct = round(a["amount"] / player_damage_total * 100, 1) if player_damage_total > 0 else 0.0
        if cn_name in skill_composition:
            # [修复] 合并同名技能（如暴风雪有190356/190357两个spell_id）
            existing = skill_composition[cn_name]
            existing["pct"] = round(existing["pct"] + pct, 1)
            existing["hits"] += a["hits"]
        else:
            skill_composition[cn_name] = {
                "spell_id": a["spell_id"],
                "pct": pct,
                "hits": a["hits"],
            }

    meta_row = conn.execute(
        "SELECT r.dungeon_name, f.keystone_level, f.keystone_time FROM report r "
        "JOIN fight f ON r.report_code = f.report_code WHERE r.report_code=? LIMIT 1",
        (report_code,),
    ).fetchone()

    dungeon = meta_row["dungeon_name"] if meta_row else "未知"
    level = meta_row["keystone_level"] if meta_row else 0
    keystone_time = meta_row["keystone_time"] if meta_row else 0

    # event 表用 type='death', source 是玩家名字符串
    death_count = conn.execute(
        "SELECT COUNT(*) as cnt FROM event WHERE source=? AND type='death'",
        (player["name"],),
    ).fetchone()["cnt"]

    conn.close()

    # 清心的真实 DPS
    qingxin_db = sqlite3.connect(db_path)
    qingxin_db.row_factory = sqlite3.Row
    dps_row = qingxin_db.execute(
        "SELECT dps FROM player WHERE id=?", (pid,)
    ).fetchone()
    benchmark_dps = int(dps_row["dps"]) if dps_row and dps_row["dps"] else 0
    qingxin_db.close()

    result = {
        "mage": "清心",
        "spec": "冰霜",
        "generated_at": date.today().isoformat(),
        "source_report": {"code": report_code, "dungeon": dungeon, "level": level,
                          "keystone_time_ms": keystone_time,
                          "total_damage": player_damage_total},
        "dps": benchmark_dps,
        "skill_composition": skill_composition,
        "deaths": death_count,
    }

    XIAOXUE_DIR.mkdir(parents=True, exist_ok=True)
    with open(BENCHMARK_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"[extract_benchmark] 基准已保存: {BENCHMARK_PATH}")
    print(f"  技能数: {len(skill_composition)}, 副本: {dungeon} +{level}")
    return result


# ═══════════════════════════════════════════════════════════════════
# 小雪评测管线
# ═══════════════════════════════════════════════════════════════════


def run_pipeline(report_code: str, fight_id: int | None = None,
                 is_baseline: bool = False,
                 skip_cache: bool = False) -> str:
    """小雪评测管线: 抓取 → 摘要 → 快照。

    Args:
        report_code: WCL 报告码
        fight_id: 可选，指定战斗
        is_baseline: 是否为初始评估（写入 baseline_snapshot.json）
        skip_cache: 跳过缓存强制重新拉取

    Returns:
        db_path
    """
    from core.xiaoxue_tracker import init_db, write_snapshot

    # Step 1: v1_pipeline
    db_exists = _db_exists(report_code)
    if not skip_cache and db_exists:
        print(f"[pipeline] Step 1/3: 使用缓存 DB: {report_code}")
        db_path = str(Path(WCL_DB_DIR) / f"{report_code}.db")
    else:
        print(f"[pipeline] Step 1/3: 抓取数据 {report_code}")
        db_path = _run_v1(report_code, str(WCL_DB_DIR), fight_id)

    # Step 2: m2_standalone_summary
    cache_ok = _cache_files_exist(report_code)
    if not skip_cache and cache_ok:
        print(f"[pipeline] Step 2/3: 使用缓存摘要")
    else:
        print(f"[pipeline] Step 2/3: 生成分析摘要")
        _run_m2_summary(db_path, report_code)

    # Step 3: 提取快照数据并写入 progress.db
    print(f"[pipeline] Step 3/3: 写入快照")
    snapshot = _extract_snapshot(db_path, report_code)

    progress_db = XIAOXUE_DIR / "progress.db"
    init_db(progress_db)
    write_snapshot(progress_db, snapshot)

    if is_baseline:
        XIAOXUE_DIR.mkdir(parents=True, exist_ok=True)
        with open(BASELINE_PATH, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2, default=str)
        print(f"[pipeline] 初始评估已保存: {BASELINE_PATH}")

    print(f"[pipeline] 完成: DPS={snapshot.get('dps')}, "
          f"死亡={snapshot.get('deaths')}, 打断={snapshot.get('interrupts')}")
    return db_path


def _extract_snapshot(db_path: str, report_code: str) -> dict:
    """从 DB + 缓存文件提取关键指标为快照 dict。"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # 找冰法玩家
    player = conn.execute(
        "SELECT id, name, dps, damage_total FROM player WHERE class='Mage' AND spec='Frost' LIMIT 1"
    ).fetchone()
    if player is None:
        conn.close()
        raise RuntimeError("未找到冰法玩家记录")

    pid = player["id"]
    pname = player["name"]
    dps = player["dps"] or 0  # 占位，下方用全程DPS覆盖

    meta = conn.execute(
        "SELECT r.dungeon_name, f.keystone_level, f.kill, f.keystone_time "
        "FROM report r JOIN fight f ON r.report_code=f.report_code "
        "WHERE r.report_code=? AND f.fight_id>0 ORDER BY f.fight_id LIMIT 1",
        (report_code,),
    ).fetchone()

    dungeon = meta["dungeon_name"] if meta else "未知"
    level = meta["keystone_level"] if meta else 0
    timed = int(meta["kill"]) if meta and meta["kill"] is not None else 0
    duration_sec = (meta["keystone_time"] / 1000) if meta and meta["keystone_time"] else 0.0

    # 修正为全程DPS（WCL显示风格）：总伤 / keystone_time
    if player["damage_total"] and duration_sec > 0:
        dps = int(player["damage_total"] / duration_sec)

    # 死亡
    deaths = conn.execute(
        "SELECT COUNT(*) as cnt FROM event WHERE source=? AND type='death'",
        (pname,),
    ).fetchone()["cnt"]

    # 打断
    interrupts = conn.execute(
        "SELECT COUNT(*) as cnt FROM event WHERE source=? AND type='interrupt'",
        (pname,),
    ).fetchone()["cnt"]

    # 技能占比
    player_total = player["damage_total"] if "damage_total" in player.keys() else 0
    if not player_total:
        player_total = conn.execute(
            "SELECT damage_total FROM player WHERE id=?", (pid,)
        ).fetchone()[0] or 0

    abilities = conn.execute(
        "SELECT spell_id, name, amount, hits FROM ability WHERE player_id=? ORDER BY amount DESC",
        (pid,),
    ).fetchall()

    from core.spell_cn_map import resolve as spell_cn

    ability_pcts = {}
    for a in abilities:
        cn_name = spell_cn(a["spell_id"], a["name"])
        pct = round(a["amount"] / player_total * 100, 1) if player_total > 0 else 0
        if cn_name in ability_pcts:
            # [修复] 合并同名技能（如暴风雪有190356/190357两个spell_id）
            existing = ability_pcts[cn_name]
            ability_pcts[cn_name] = {
                "pct": round(existing["pct"] + pct, 1),
                "hits": existing["hits"] + a["hits"],
            }
        else:
            ability_pcts[cn_name] = {
                "pct": pct,
                "hits": a["hits"],
            }

    conn.close()

    vs_pct = _calc_vs_benchmark(dps, dungeon, level)

    return {
        "date": date.today().isoformat(),
        "report_code": report_code,
        "dungeon": dungeon,
        "level": level,
        "timed": timed,
        "dps": int(dps),
        "vs_benchmark_pct": round(vs_pct, 1),
        "deaths": deaths,
        "interrupts": interrupts,
        "duration_sec": duration_sec,
        "ability_pcts": ability_pcts,
        "ability_casts": {},
        "survival_skills": {},
    }


def _calc_vs_benchmark(dps: float, dungeon: str, level: int) -> float:
    """计算 vs 清心同层基准的百分比。

    简化实现: 用清心基准中的 DPS 信息。由于基准中只有技能占比没有 DPS，
    此处做近似估算。精确值在 report_builder 中做详细对比。
    """
    if not BENCHMARK_PATH.exists():
        return 0.0

    with open(BENCHMARK_PATH, encoding="utf-8") as f:
        bm = json.load(f)

    bm_level = bm.get("source_report", {}).get("level", 0)
    if bm_level == 0:
        return 0.0

    # 近似：按层数缩放。假设每层 DPS 增长约 5%
    level_factor = 1.05 ** (bm_level - level)
    # 假定清心 DPS 在 120k-200k 之间（常见值）
    bm_dps_est = 150000
    est_ratio = dps / (bm_dps_est / level_factor) if dps > 0 else 0
    return min(est_ratio * 100, 100)


# ═══════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(description="小雪评测一键管线")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("report_code", nargs="?", help="小雪 WCL 报告代码")
    group.add_argument("--extract-benchmark", metavar="CODE", help="从清心报告提取基准 JSON")
    parser.add_argument("--fight-id", type=int, help="指定 fight ID")
    parser.add_argument("--baseline", action="store_true", help="标记为初始评估")
    parser.add_argument("--db-dir", default=str(WCL_DB_DIR), help="DB 存放目录")
    parser.add_argument("--skip-cache", action="store_true", help="跳过缓存强制重新拉取")
    args = parser.parse_args()

    if args.extract_benchmark:
        extract_benchmark(args.extract_benchmark, args.db_dir, args.fight_id)
    else:
        run_pipeline(
            args.report_code,
            fight_id=args.fight_id,
            is_baseline=args.baseline,
            skip_cache=args.skip_cache,
        )


if __name__ == "__main__":
    main()
