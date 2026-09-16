#!/usr/bin/env python3
"""
core/meishu_pipeline.py — 梅叔酒仙一键管线 + 硬玩复仇基准提取

从 WCL 报告代码到所有中间产物的完整流程:
  1. v1_pipeline.py → SQLite DB（含缓存检查）
  2. m2_standalone_summary.py → 4 个 txt
  3. 代码自动提取基准对比数据（含坦克特有指标）
  4. 存入进度快照

用法:
    # 提取硬玩复仇基准
    PYTHONPATH=. python3 core/meishu_pipeline.py --extract-benchmark <report_code>

    # 梅叔评测管线
    PYTHONPATH=. python3 core/meishu_pipeline.py <report_code>

    # 指定 fight_id
    PYTHONPATH=. python3 core/meishu_pipeline.py <report_code> --fight-id 5
"""

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

# ── 路径 ──
PROJECT_DIR = Path(__file__).resolve().parent.parent
WCL_DB_DIR = PROJECT_DIR / "data" / "wcl_db"
CACHE_DIR = PROJECT_DIR / "data" / "cache"
MEISHU_DIR = PROJECT_DIR / "data" / "meishu"
BENCHMARK_PATH = MEISHU_DIR / "yingwan_benchmark_profile.json"
V1_PIPELINE = PROJECT_DIR / "core" / "v1_pipeline.py"
M2_SUMMARY = PROJECT_DIR / "core" / "m2_standalone_summary.py"

from core.config import get_api_key as _get_api_key


def _db_exists(report_code: str) -> bool:
    db_path = WCL_DB_DIR / f"{report_code}.db"
    return db_path.exists() and db_path.stat().st_size > 1000


def _cache_files_exist(report_code: str) -> bool:
    files = [
        CACHE_DIR / f"m2_meta_{report_code}.txt",
        CACHE_DIR / f"m2_group_a_{report_code}.txt",
        CACHE_DIR / f"m2_group_b_{report_code}.txt",
        CACHE_DIR / f"m2_group_c_{report_code}.txt",
    ]
    return all(f.exists() and f.stat().st_size > 10 for f in files)


def run_v1_pipeline(report_code: str, fight_id: int | None = None):
    """确保 DB 存在。"""
    if _db_exists(report_code):
        print(f"[meishu] DB 已存在: {report_code}.db")
        return
    cmd = [sys.executable, str(V1_PIPELINE), report_code]
    if fight_id:
        cmd += ["--fight-id", str(fight_id)]
    env = os.environ.copy()
    env["WCL_API_KEY"] = _get_api_key()
    env["PYTHONPATH"] = str(PROJECT_DIR)
    subprocess.run(cmd, cwd=str(PROJECT_DIR), env=env, check=True)


def run_m2_summary(report_code: str):
    """确保 m2_standalone_summary 缓存存在。"""
    if _cache_files_exist(report_code):
        print(f"[meishu] 缓存已存在: {report_code}")
        return
    db_path = WCL_DB_DIR / f"{report_code}.db"
    cmd = [sys.executable, str(M2_SUMMARY), str(db_path.resolve()), report_code]
    env = os.environ.copy()
    env["WCL_API_KEY"] = _get_api_key()
    env["PYTHONPATH"] = str(PROJECT_DIR)
    subprocess.run(cmd, cwd=str(PROJECT_DIR), env=env, check=True)


# ═══ 基准提取 ═══

BREWMASTER_BENCHMARK_SKILLS = {
    # 核心输出
    "醉酿投": {"spell_id": 121253},
    "火焰之息": {"spell_id": 123725},
    "幻灭踢": {"spell_id": 100784},
    "猛虎掌": {"spell_id": 100780},
    "神鹤引项踢": {"spell_id": 101546},
    "龙焰酒": {"spell_id": 123730},
    # 爆发
    "玄牛下凡": {"spell_id": 386285},
    "天神灌注": {"spell_id": 395403},
    "淬火神酿": {"spell_id": 443006},
    "风暴烈酒的珍藏酒桶": {"spell_id": 443011},
    "再来一桶": {"spell_id": 457953},
    # 减伤/酒池
    "活血酒": {"spell_id": 115399},
    "壮胆酒": {"spell_id": 115203},
    "禅悟状态": {"spell_id": 449642},
    "散魔功": {"spell_id": 122783},
    "明志灵药": {"spell_id": 388369},
    # 自疗
    "玄牛之赐": {"spell_id": 124503},
    # 功能
    "切喉手": {"spell_id": 116705},
}


def extract_benchmark(report_code: str, fight_id: int | None):
    """从教练 DB 提取基准数据，写入 yingwan_benchmark_profile.json。"""
    run_v1_pipeline(report_code, fight_id)

    db_path = WCL_DB_DIR / f"{report_code}.db"
    db = sqlite3.connect(str(db_path.resolve()))
    db.row_factory = sqlite3.Row

    # 获取 fight 元数据
    if fight_id:
        fight = db.execute(
            "SELECT * FROM fight WHERE fight_id=?", (fight_id,)
        ).fetchone()
    else:
        fight = db.execute("SELECT * FROM fight LIMIT 1").fetchone()
    if not fight:
        print(f"[meishu] ❌ 未找到 fight")
        return

    fd = dict(fight)
    # 使用 keystone_time（全本时长ms）而非单波 fight 的 start_time/end_time
    total_time_ms = fd.get("keystone_time", 0)
    if total_time_ms <= 0:
        # fallback: 单波时长
        total_time_ms = fd["end_time"] - fd["start_time"]
    duration_s = total_time_ms / 1000

    # 获取玩家数据
    player = db.execute(
        "SELECT * FROM player WHERE spec LIKE '%酒仙%' OR class LIKE '%Monk%'"
    ).fetchone()
    if not player:
        player = db.execute("SELECT * FROM player ORDER BY id ASC LIMIT 1").fetchone()
    if not player:
        print(f"[meishu] ❌ 未找到玩家")
        return

    pd = dict(player)
    total_damage = pd.get("damage_total", 0) or 0
    total_heal = pd.get("heal_total", 0) or 0
    # 优先使用 DB 中预计算的 DPS/HPS
    dps = pd.get("dps", 0) or int(total_damage / duration_s) if duration_s > 0 else 0
    hps = int(total_heal / duration_s) if duration_s > 0 else 0

    # 获取报告元数据
    report = db.execute("SELECT * FROM report LIMIT 1").fetchone()
    report_dict = dict(report) if report else {}
    dungeon_name = report_dict.get("dungeon_name", "?")
    fd = dict(fight)
    keystone_level = fd.get("keystone_level", 0)
    keystone_timed = fd.get("kill", 0)
    # 使用之前已计算的 total_time_ms（keystone_time 优先）
    # 已在上面定义，此处复用

    # 提取技能组成（hits = 施法次数）
    player_id = player["id"]
    abilities = db.execute("""
        SELECT a.name as ability_name, SUM(a.hits) as total_hits, SUM(a.amount) as total_dmg
        FROM ability a
        WHERE a.player_id=?
        GROUP BY a.name
        ORDER BY total_dmg DESC
    """, (player_id,)).fetchall()

    skill_composition = {}
    total_dmg_all = sum(a["total_dmg"] or 0 for a in abilities)

    for a in abilities:
        name = a["ability_name"]
        if not name:
            continue
        hits = a["total_hits"] or 0
        dmg = a["total_dmg"] or 0
        pct = round(dmg / total_dmg_all * 100, 1) if total_dmg_all > 0 else 0
        skill_data = BREWMASTER_BENCHMARK_SKILLS.get(name, {})
        skill_composition[name] = {
            "spell_id": skill_data.get("spell_id", 0),
            "pct": pct,
            "hits": hits,
        }

    # 坦克特有指标：从 DB 推算
    # 尝试从 ability 表获取伤害承受量（WCL V1 API 支持有限）
    # V1 table 端点的 damage-taken 需通过 damage-done end 点的 target 推断
    # 无法直接获取，留作 stage-2 增强

    benchmark = {
        "name": "硬玩复仇绿色",
        "spec": "酒仙",
        "generated_at": "2026-05-14",
        "source_report": {
            "code": report_code,
            "dungeon": dungeon_name,
            "level": keystone_level,
            "keystone_time_ms": total_time_ms,
            "total_damage": total_damage,
            "total_heal": total_heal,
        },
        "dps": dps,
        "hps": hps,
        "skill_composition": skill_composition,
        "mitigation_metrics": {
            "stagger_total": 0,
            "stagger_pct": 0,
            "purify_count": 0,
            "purify_pct": 0,
            "self_heal": total_heal,
            "damage_taken": 0,
        },
    }

    MEISHU_DIR.mkdir(parents=True, exist_ok=True)
    BENCHMARK_PATH.write_text(json.dumps(benchmark, ensure_ascii=False, indent=2))
    print(f"[meishu] ✅ 基准已提取: {BENCHMARK_PATH}")
    print(f"    {dungeon_name} +{keystone_level} | DPS={dps} | HPS={hps}")
    print(f"    技能数: {len(skill_composition)}")

    db.close()


# ═══ CLI ═══

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="梅叔酒仙管线")
    parser.add_argument("report_code", help="WCL 报告代码")
    parser.add_argument("--fight-id", type=int, help="指定战斗 ID")
    parser.add_argument("--extract-benchmark", action="store_true",
                        help="提取硬玩复仇基准")
    return parser.parse_args(argv)


def main():
    args = parse_args()
    if args.extract_benchmark:
        extract_benchmark(args.report_code, args.fight_id)
        return

    code = args.report_code
    fight_id = args.fight_id

    print(f"[meishu] 🚀 启动: {code}")

    # Phase 1: v1_pipeline
    run_v1_pipeline(code, fight_id)

    # Phase 2: m2_standalone_summary
    run_m2_summary(code)

    # 复制缓存文件（加 code 后缀）
    for base in ["m2_meta", "m2_group_a", "m2_group_b", "m2_group_c"]:
        src = CACHE_DIR / f"{base}.txt"
        dst = CACHE_DIR / f"{base}_{code}.txt"
        if src.exists():
            import shutil
            shutil.copy2(src, dst)

    print(f"[meishu] ✅ 管线完成: {code}")


if __name__ == "__main__":
    main()
