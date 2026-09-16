#!/usr/bin/env python3
"""
|M+ 通用管线脚本 — mplus_pipeline.py
|
|单次调用产出某个产品的全部数据文件，输出 manifest.json 供模型验证。
|
|Mode:
|  team — Team 全队混合分析（v1_pipeline + m2_standalone + fetch_top_benchmarks + report_skeleton）
|  x    — X 系列教练分析（v1_pipeline ×2 + events API + report_builder + tracker）
|  t    — T 系列教练分析（v1_pipeline ×2 + healing events API + report_builder + tracker）
|  m    — M 系列酒仙教练分析（v1_pipeline ×2 + events API + report_builder + tracker）
|
|用法:
|  WCL_API_KEY=xxx PYTHONPATH=. python3 core/mplus_pipeline.py team \\\
|    --report-code <CODE> --fight-id <N>
|
  WCL_API_KEY=xxx PYTHONPATH=. python3 core/mplus_pipeline.py x \\
    --report-code <CODE> --fight-id <N> \\
    --benchmark-char qingxingood --benchmark-server 冰风岗 --benchmark-encounter 12805

  WCL_API_KEY=xxx PYTHONPATH=. python3 core/mplus_pipeline.py t \\
    --report-code <CODE> --fight-id <N> \\
    --benchmark-char 绿绿月光 --benchmark-server 伊森利恩 --benchmark-encounter 12805
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

# 新模块
from core.config import get_api_key
from core.profile_loader import load_profile
from core.pipeline_strategies import CoachingStrategy, ROLE_CONFIGS

VERSION = "5.1.0"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
WCL_DB_DIR = DATA_DIR / "wcl_db"
CACHE_DIR = DATA_DIR / "cache"

# ── helpers ──────────────────────────────────────────────────────────

def log(msg: str):
    print(f"[mplus_pipeline] {msg}", flush=True)


def run_script(script_name: str, args: list[str], timeout: int = 600) -> str:
    """运行 core/{script_name} 并返回 stdout"""
    cmd = [
        sys.executable, "-m", f"core.{script_name.replace('.py', '')}"
    ] + args
    env = os.environ.copy()
    env["WCL_API_KEY"] = get_api_key()
    env["PYTHONPATH"] = str(PROJECT_ROOT)

    log(f"运行: {' '.join(cmd)}")
    start = time.time()
    result = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    elapsed = time.time() - start
    if result.returncode != 0:
        stderr = result.stderr.strip() or "(no stderr)"
        log(f"❌ {script_name} 失败 (exit={result.returncode}, {elapsed:.1f}s)")
        log(f"stderr: {stderr[:500]}")
        raise RuntimeError(f"{script_name} 失败: {stderr[:300]}")
    log(f"✅ {script_name} 完成 ({elapsed:.1f}s)")
    return result.stdout


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def write_manifest(output_dir: Path, files: list[dict], meta: dict):
    """写入 manifest.json"""
    manifest = {
        "pipeline_version": VERSION,
        "mode": meta.get("mode", "m"),
        "report_code": meta.get("report_code", ""),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "learner": meta.get("learner"),
        "benchmark": meta.get("benchmark"),
        "files": [],
        "errors": meta.get("errors", []),
        "warnings": meta.get("warnings", []),
    }
    for f in files:
        fpath = output_dir / f["path"]
        entry = {
            "path": f["path"],
            "size": fpath.stat().st_size if fpath.exists() else 0,
            "sha256": file_sha256(fpath) if fpath.exists() else "0",
            "description": f.get("description", ""),
        }
        manifest["files"].append(entry)

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    log(f"📄 manifest.json 已写入 ({len(manifest['files'])} files)")
    return manifest


def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


def clean_pycache():
    """清理 __pycache__"""
    subprocess.run(
        ["find", str(PROJECT_ROOT), "-name", "__pycache__", "-type", "d",
         "-exec", "rm", "-rf", "{}", "+"],
        capture_output=True, cwd=str(PROJECT_ROOT)
    )


# ── Team mode ────────────────────────────────────────────────────────

def run_team_mode(args):
    """Team 全队混合分析"""
    code = args.report_code
    fight_id = args.fight_id
    output_dir = Path(args.output_dir) if args.output_dir else (CACHE_DIR / code)
    ensure_dir(output_dir)

    meta = {"mode": "m", "report_code": code, "errors": [], "warnings": []}

    # Phase 1: v1_pipeline
    db_path = WCL_DB_DIR / f"{code}.db"
    if db_path.exists() and db_path.stat().st_size > 1024:
        log(f"📦 DB 缓存命中: {db_path}")
    else:
        run_script("v1_pipeline.py", [code, "--fight-id", str(fight_id)])

    db_path = str(db_path.resolve())

    # Phase 2: m2_standalone_summary
    run_script("m2_standalone_summary.py", [db_path, code])

    # 修复缓存文件名（添加 code 后缀）
    for base in ["m2_meta", "m2_group_a", "m2_group_b", "m2_group_c"]:
        src = CACHE_DIR / f"{base}.txt"
        dst = CACHE_DIR / f"{base}_{code}.txt"
        if src.exists():
            shutil.copy2(src, dst)
            log(f"  cp {base}.txt → {base}_{code}.txt")
        elif dst.exists():
            log(f"  ✅ {base}_{code}.txt 已存在")
        else:
            log(f"  ⚠️ {base}.txt 不存在")

    # Phase 3: fetch_top_benchmarks
    try:
        run_script("fetch_top_benchmarks.py", [db_path, code])
    except RuntimeError as e:
        meta["errors"].append(f"fetch_top_benchmarks 失败: {e}")
        meta["warnings"].append("使用无标杆对比的独立分析")

    # Phase 4 (optional): report_skeleton
    if args.include_skeleton:
        try:
            run_script("report_skeleton.py", [code])
        except RuntimeError as e:
            meta["warnings"].append(f"report_skeleton 跳过: {e}")

    # 收集产出文件
    files = [
        {"path": f"m2_meta_{code}.txt", "description": "M2 报告元数据"},
        {"path": f"m2_group_a_{code}.txt", "description": "M2 伤害构成 + 施法活跃度"},
        {"path": f"m2_group_b_{code}.txt", "description": "M2 死亡分析 + 路线时间轴"},
        {"path": f"m2_group_c_{code}.txt", "description": "M2 Buff覆盖 + 资源流转"},
    ]
    bm_json = CACHE_DIR / "per_spec_benchmarks.json"
    if bm_json.exists():
        files.append({"path": "per_spec_benchmarks.json", "description": "逐专精 1v1 顶层对比"})
    skel = CACHE_DIR / "m2_skeleton.md"
    if skel.exists():
        files.append({"path": "m2_skeleton.md", "description": "M2 报告骨架"})

    # copy files to output_dir
    for f in files:
        src = CACHE_DIR / f["path"]
        if src.exists():
            shutil.copy2(src, output_dir / f["path"])
            log(f"  📋 {f['path']} → {output_dir}")

    write_manifest(output_dir, files, meta)
    return output_dir


# ── X mode ───────────────────────────────────────────────────────────

def run_x_mode(args):
    """X 系列教练分析"""
    code = args.report_code
    fight_id = args.fight_id
    output_dir = Path(args.output_dir) if args.output_dir else (CACHE_DIR / code)
    ensure_dir(output_dir)

    meta = {
        "mode": "x",
        "report_code": code,
        "errors": [],
        "warnings": [],
        "learner": {"name": "冬柔", "spec": "冰法"},
    }

    # 如果用户提供了 benchmark 报告代码，直接使用；否则未来实现自动搜索
    if args.benchmark_report and args.benchmark_fight:
        meta["benchmark"] = {
            "name": args.benchmark_char,
            "report_code": args.benchmark_report,
            "fight_id": args.benchmark_fight,
        }
    else:
        meta["warnings"].append("未提供 benchmark-report/fight，跳过教练基准提取")

    # Phase 1: v1_pipeline for learner
    db_path = WCL_DB_DIR / f"{code}.db"
    if db_path.exists() and db_path.stat().st_size > 1024:
        log(f"📦 DB 缓存命中: {db_path}")
    else:
        run_script("v1_pipeline.py", [code, "--fight-id", str(fight_id)])

    # Phase 2: 教练基准提取
    if meta.get("benchmark"):
        bm_code = meta["benchmark"]["report_code"]
        bm_fight = meta["benchmark"]["fight_id"]
        bm_db = WCL_DB_DIR / f"{bm_code}.db"
        if bm_db.exists() and bm_db.stat().st_size > 1024:
            log(f"📦 教练 DB 缓存命中: {bm_db}")
        else:
            run_script("v1_pipeline.py", [bm_code, "--fight-id", str(bm_fight)])

        try:
            run_script("xiaoxue_pipeline.py", [
                bm_code, "--extract-benchmark", "--fight-id", str(bm_fight)
            ])
        except RuntimeError as e:
            meta["errors"].append(f"基准提取失败: {e}")

    # Phase 3: 学习者的 m2_standalone_summary（xiaoxue_pipeline 内部使用）
    db_path_str = str(db_path.resolve())
    run_script("m2_standalone_summary.py", [db_path_str, code])

    # 修复缓存文件名
    for base in ["m2_meta", "m2_group_a", "m2_group_b", "m2_group_c"]:
        src = CACHE_DIR / f"{base}.txt"
        dst = CACHE_DIR / f"{base}_{code}.txt"
        if src.exists():
            shutil.copy2(src, dst)
        elif not dst.exists():
            meta["warnings"].append(f"{base}.txt 未生成")

    # Phase 4: 报告骨架
    try:
        run_script("xiaoxue_report_builder.py", [code])
    except RuntimeError as e:
        meta["warnings"].append(f"report_builder 跳过: {e}")

    # 收集产出文件
    files = [
        {"path": f"m2_meta_{code}.txt", "description": "X 报告元数据"},
        {"path": f"m2_group_a_{code}.txt", "description": "X 伤害构成 + 施法活跃度"},
        {"path": f"m2_group_b_{code}.txt", "description": "X 死亡分析 + 路线时间轴"},
        {"path": f"m2_group_c_{code}.txt", "description": "X Buff覆盖 + 资源流转"},
    ]

    bm_profile = PROJECT_ROOT / "data" / "xiaoxue" / "qingxin_benchmark_profile.json"
    if bm_profile.exists():
        files.append({"path": "qingxin_benchmark_profile.json", "description": "清心基准档案"})

    skeleton = CACHE_DIR / f"m2_xiaoxue_skeleton_{code}.md"
    if skeleton.exists():
        files.append({"path": f"m2_xiaoxue_skeleton_{code}.md", "description": "X 报告骨架"})

    # copy files to output_dir
    for f in files:
        src = CACHE_DIR / f["path"]
        extra_srcs = {
            "qingxin_benchmark_profile.json": bm_profile,
        }
        if src.exists():
            shutil.copy2(src, output_dir / f["path"])
        elif f["path"] in extra_srcs and extra_srcs[f["path"]].exists():
            shutil.copy2(extra_srcs[f["path"]], output_dir / f["path"])
        else:
            meta["warnings"].append(f"{f['path']} 未找到")

    write_manifest(output_dir, files, meta)
    return output_dir


# ── events API 子管线 ────────────────────────────────────────────────

def _run_events_pipeline(code: str, db_path_str: str, args, meta: dict):
    """Phase 4: 拉取 events API 数据 → x_comparison.json"""
    log("🌊 Phase 4: events API 输出轴数据")

    bm = meta["benchmark"]
    if not bm:
        return

    # 1. 获取清心 source ID（使用战斗时间窗口避免多fight顶N截断）
    try:
        # 先获取教练 fight 时间窗口
        bm_fight_start, bm_fight_end = _get_fight_window(
            bm["report_code"], bm["fight_id"])
        bm_sourceid = _find_benchmark_sourceid(
            bm["report_code"], bm["name"],
            bm_fight_start, bm_fight_end)
        log(f"  清心 sourceID: {bm_sourceid}")
    except Exception as e:
        meta["warnings"].append(f"无法获取清心 sourceID: {e}")
        return

    # 2. 从 DB 读取死亡事件（毫秒时间戳）
    learner_name = meta.get("learner", {}).get("name", "")
    death_events = _read_death_events(db_path_str, learner_name) if learner_name else []

    # 3. 运行 events API 管线
    mode = meta.get("mode", "x")
    from core.events_pipeline import build_x_comparison

    output_path = CACHE_DIR / f"{mode}_comparison_{code}.json"
    result = build_x_comparison(
        learner_code=code,
        learner_fight_id=args.fight_id,
        learner_sourceid=args.learner_source,
        benchmark_code=bm["report_code"],
        benchmark_fight_id=bm["fight_id"],
        benchmark_sourceid=bm_sourceid,
        death_events=death_events,
        output_path=str(output_path),
        mode=mode,
    )
    if result.get("error"):
        meta["warnings"].append(f"x_comparison 生成失败: {result['error']}")
        return

    log(f"  ✅ 逐波次: 学习者={len(result['waves_learner'])}波, "
         f"清心={len(result['waves_benchmark'])}波")
    if result.get("death_healing"):
        log(f"  ✅ 死亡治疗分析: {len(result['death_healing'])}条")


def _get_fight_window(report_code: str, fight_id: int) -> tuple[int, int]:
    """获取指定战斗的 start_time / end_time（毫秒）"""
    import json, urllib.request
    key = get_api_key()
    url = f"https://www.warcraftlogs.com/v1/report/fights/{report_code}?api_key={key}"
    data = json.loads(urllib.request.urlopen(url).read().decode())
    for f in data.get("fights", []):
        if f.get("id") == fight_id:
            return f["start_time"], f["end_time"]
    raise ValueError(f"fight_id={fight_id} 在 {report_code} 中未找到")


def _find_benchmark_sourceid(report_code: str, char_name: str,
                              fight_start: int = 0, fight_end: int = 99999999) -> int:
    """从 damage-done/healing-done table 查找教练角色 ID（忽略大小写）

    先查 damage-done（最通用），查不到则查 healing-done（治疗职业）。
    使用具体战斗时间窗口避免多战斗报告顶 N 截断。
    """
    import json, urllib.request
    key = get_api_key()
    name_lower = char_name.lower()

    for table_name in ("damage-done", "healing"):
        url = (f"https://www.warcraftlogs.com/v1/report/tables/"
               f"{table_name}/{report_code}?start={fight_start}&end={fight_end}&api_key={key}")
        try:
            data = json.loads(urllib.request.urlopen(url).read().decode())
            for e in data.get("entries", []):
                if e.get("name", "").lower() == name_lower:
                    return e["id"]
        except Exception:
            continue

    raise ValueError(f"角色 {char_name} 在 {report_code} (fight) 中未找到")


def _read_death_events(db_path_str: str, learner_name: str) -> list[dict]:
    """从 SQLite DB 读取死亡事件（毫秒时间戳）"""
    import sqlite3
    db = sqlite3.connect(db_path_str)
    rows = db.execute(
        "SELECT timestamp, ability_name FROM event WHERE type='death' AND source=?",
        (learner_name,)
    ).fetchall()
    db.close()
    log(f"  DB死亡查询: {learner_name} → {len(rows)} 条")
    return [{"timestamp": r[0], "ability_name": r[1] or "?"} for r in rows]


def _run_coaching_pipeline(args, meta_override: dict | None = None):
    """X / T 共享的核心管线

    参数:
      args: CLI 参数
      meta_override: 覆盖 manifest 字段（如 mode、learner、spec）
                     用于区分 X 和 T 分支
    """
    code = args.report_code
    fight_id = args.fight_id
    output_dir = Path(args.output_dir) if args.output_dir else (CACHE_DIR / code)
    ensure_dir(output_dir)

    meta = {
        "mode": "x",
        "report_code": code,
        "errors": [],
        "warnings": [],
        "learner": {"name": "冬柔", "spec": "冰法"},
    }
    if meta_override:
        meta.update(meta_override)

    # 教练基准信息
    if args.benchmark_report and args.benchmark_fight:
        meta["benchmark"] = {
            "name": args.benchmark_char,
            "report_code": args.benchmark_report,
            "fight_id": args.benchmark_fight,
        }
    else:
        meta["warnings"].append("未提供 benchmark-report/fight，跳过基准提取")

    # Phase 1: v1_pipeline for learner
    db_path = WCL_DB_DIR / f"{code}.db"
    if db_path.exists() and db_path.stat().st_size > 1024:
        log(f"📦 DB 缓存命中: {db_path}")
    else:
        run_script("v1_pipeline.py", [code, "--fight-id", str(fight_id)])

    mode = meta.get("mode", "x")
    is_healing = mode == "t"
    is_brewmaster = mode == "b"

    # Phase 2: 教练基准提取
    if meta.get("benchmark"):
        bm_code = meta["benchmark"]["report_code"]
        bm_fight = meta["benchmark"]["fight_id"]
        bm_db = WCL_DB_DIR / f"{bm_code}.db"
        if bm_db.exists() and bm_db.stat().st_size > 1024:
            log(f"📦 教练 DB 缓存命中: {bm_db}")
        else:
            run_script("v1_pipeline.py", [bm_code, "--fight-id", str(bm_fight)])

        if is_brewmaster:
            extract_script = "meishu_pipeline.py"
            bm_profile_name = "yingwan_benchmark_profile.json"
            bm_dir = "meishu"
        elif is_healing:
            extract_script = "taozhi_pipeline.py"
            bm_profile_name = "lvlyue_benchmark_profile.json"
            bm_dir = "taozhi"
        else:
            extract_script = "xiaoxue_pipeline.py"
            bm_profile_name = "qingxin_benchmark_profile.json"
            bm_dir = "xiaoxue"
        extract_bin = Path(PROJECT_ROOT) / "core" / extract_script
        if extract_bin.exists():
            try:
                run_script(extract_script, ["--extract-benchmark", bm_code, "--fight-id", str(bm_fight)])
                if is_brewmaster:
                    bm_profile_name = "yingwan_benchmark_profile.json"
                    bm_dir = "meishu"
                elif is_healing:
                    bm_profile_name = "lvlyue_benchmark_profile.json"
                    bm_dir = "taozhi"
                else:
                    bm_profile_name = "qingxin_benchmark_profile.json"
                    bm_dir = "xiaoxue"
                bm_profile = PROJECT_ROOT / "data" / bm_dir / bm_profile_name
                if bm_profile.exists():
                    log(f"✅ 教练基准已提取: {bm_profile}")
            except RuntimeError as e:
                meta["warnings"].append(f"基准提取失败({extract_script}): {e}")
        else:
            meta["warnings"].append(f"{extract_script} 未实现，使用 DB 直查")

    # Phase 3: m2_standalone_summary（通用）
    db_path_str = str(db_path.resolve())
    run_script("m2_standalone_summary.py", [db_path_str, code])

    for base in ["m2_meta", "m2_group_a", "m2_group_b", "m2_group_c"]:
        src = CACHE_DIR / f"{base}.txt"
        dst = CACHE_DIR / f"{base}_{code}.txt"
        if src.exists():
            shutil.copy2(src, dst)
        elif not dst.exists():
            meta["warnings"].append(f"{base}.txt 未生成")

    # Phase 4: events API 输出轴数据（X/T/M 系列专有）
    if meta.get("benchmark") and meta.get("mode") in ("x", "t", "b"):
        try:
            _run_events_pipeline(code, str(db_path.resolve()), args, meta)
        except Exception as e:
            meta["warnings"].append(f"events API 管线跳过: {e}")
            log(f"⚠️ events API 跳过: {e}")

    # Phase 5: 报告骨架
    mode = meta.get("mode", "x")
    is_healing = mode == "t"
    is_brewmaster = mode == "b"

    if is_brewmaster:
        builder_script = "meishu_report_builder.py"
        skeleton_name = f"m2_meishu_skeleton_{code}.md"
    elif is_healing:
        builder_script = "taozhi_report_builder.py"
        skeleton_name = f"m2_taozhi_skeleton_{code}.md"
    else:
        builder_script = "xiaoxue_report_builder.py"
        skeleton_name = f"m2_xiaoxue_skeleton_{code}.md"
    builder_bin = Path(PROJECT_ROOT) / "core" / builder_script

    # 计算基准配置文件路径（用于填充总览表技能次数）
    bm_profile_path = None
    if meta.get("benchmark"):
        if is_brewmaster:
            bm_name = "yingwan_benchmark_profile.json"
            bm_dir = "meishu"
        elif is_healing:
            bm_name = "lvlyue_benchmark_profile.json"
            bm_dir = "taozhi"
        else:
            bm_name = "qingxin_benchmark_profile.json"
            bm_dir = "xiaoxue"
        bm_candidate = PROJECT_ROOT / "data" / bm_dir / bm_name
        if bm_candidate.exists():
            bm_profile_path = bm_candidate

    # 计算 comparison JSON 路径（用于自动生成施法时间轴对比）
    comparison_path = None
    events_mode = meta.get("mode", "x")
    comp_candidate = CACHE_DIR / f"{events_mode}_comparison_{code}.json"
    if comp_candidate.exists():
        comparison_path = comp_candidate
        log(f"📊 发现 events API 对比数据: {comparison_path.name}")

    if builder_bin.exists():
        try:
            run_script(builder_script, [code])
        except RuntimeError as e:
            meta["warnings"].append(f"{builder_script} 失败，直写骨架: {e}")
            _write_placeholder_skeleton(code, skeleton_name, is_healing,
                                         is_brewmaster=is_brewmaster,
                                         bm_profile_path=bm_profile_path, comparison_path=comparison_path)
    else:
        _write_placeholder_skeleton(code, skeleton_name, is_healing,
                                     is_brewmaster=is_brewmaster,
                                     bm_profile_path=bm_profile_path, comparison_path=comparison_path)

    # 收集产出文件
    mode_label = "X"
    if is_healing:
        mode_label = "T"
    elif is_brewmaster:
        mode_label = "M"
    files = [
        {"path": f"m2_meta_{code}.txt", "description": f"{mode_label} 报告元数据"},
        {"path": f"m2_group_a_{code}.txt", "description": "伤害/治疗构成"},
        {"path": f"m2_group_b_{code}.txt", "description": "死亡分析 + 路线"},
        {"path": f"m2_group_c_{code}.txt", "description": "Buff覆盖"},
    ]

    if is_brewmaster:
        bm_dir = "meishu"
        bm_name = "yingwan_benchmark_profile.json"
    elif is_healing:
        bm_dir = "taozhi"
        bm_name = "lvlyue_benchmark_profile.json"
    else:
        bm_dir = "xiaoxue"
        bm_name = "qingxin_benchmark_profile.json"
    bm_profile = PROJECT_ROOT / "data" / bm_dir / bm_name
    if bm_profile.exists():
        files.append({"path": bm_name, "description": "教练基准档案"})

    skeleton = CACHE_DIR / skeleton_name
    if skeleton.exists():
        files.append({"path": skeleton_name, "description": f"{mode_label} 报告骨架"})

    # events API 输出轴数据
    events_mode = meta.get("mode", "x")
    comparison_json = CACHE_DIR / f"{events_mode}_comparison_{code}.json"
    if comparison_json.exists():
        files.append({"path": f"{events_mode}_comparison_{code}.json", "description": "events API 逐波次对比"})

    for f in files:
        src = CACHE_DIR / f["path"]
        alt_map = {bm_name: bm_profile}
        if src.exists():
            shutil.copy2(src, output_dir / f["path"])
        elif f["path"] in alt_map and alt_map[f["path"]].exists():
            shutil.copy2(alt_map[f["path"]], output_dir / f["path"])
        else:
            meta["warnings"].append(f"{f['path']} 未找到")

    write_manifest(output_dir, files, meta)
    return output_dir


def run_x_mode(args):
    """X 系列教练分析 — 冰法输出向"""
    return _run_coaching_pipeline(args)


def run_t_mode(args):
    """T 系列教练分析 — 治疗向，共享 X 的核心管线"""
    learner_name = args.learner_name or "学习者"
    override = {
        "mode": "t",
        "learner": {"name": learner_name, "spec": "织雾武僧"},
    }
    return _run_coaching_pipeline(args, meta_override=override)


def run_m_mode(args):
    """M 系列酒仙教练分析 — 坦克向，共享 X 的核心管线"""
    learner_name = args.learner_name or "梅叔"
    override = {
        "mode": "b",
        "learner": {"name": learner_name, "spec": "酒仙"},
    }
    return _run_coaching_pipeline(args, meta_override=override)


def _build_wave_comparison_tables(comparison_path: Path, is_healing: bool = False, is_brewmaster: bool = False) -> list[str]:
    """从 t_comparison.json / x_comparison.json 读取逐波次数据，
    自动生成施法时间轴对比表格。

    Args:
        comparison_path: comparison JSON 路径
        is_healing: 是否治疗模式（影响自动诊断逻辑）

    Returns:
        markdown 行列表（可 append 到骨架）
    """
    lines = []
    try:
        raw = comparison_path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except Exception as e:
        log(f"⚠️ 读取 comparison JSON 失败: {e}")
        return ["> ⚠️ 施法时间轴数据读取失败，请检查 t_comparison.json"]

    waves_l = data.get("waves_learner", [])
    waves_b = data.get("waves_benchmark", [])
    if not waves_l:
        return ["> ⚠️ comparison JSON 中无逐波次数据"]

    # --- 波次总览表 ---
    lines.append("### 📋 波次总览")
    lines.append("")
    lines.append("| # | 名称 | 类型 | 时长 | 学习者施法 | 教练施法 | 密度差 |")
    lines.append("|---|---|---|---|---|---|---|")
    for wl in waves_l:
        wid = wl.get("wave_id", "?")
        name = wl.get("name", "?")
        is_boss = wl.get("is_boss", 0)
        dtype = "BOSS" if is_boss else "小怪"
        dur = wl.get("duration_s", 0)
        lc = wl.get("total_casts", 0)
        ld = wl.get("density", 0)
        # 找教练对应波次（按相同 wave_id）
        wb = next((w for w in waves_b if w.get("wave_id") == wid), None)
        bc = wb.get("total_casts", "—") if wb else "—"
        bd = wb.get("density", 0) if wb else 0
        density_gap = f"{ld - bd:+.2f}/s" if isinstance(bd, (int, float)) else "—"
        lines.append(f"| {wid} | {name} | {dtype} | {dur}s | {lc} | {bc} | {density_gap} |")
    lines.append("")

    # --- 选取高压波次做详细序列对比 ---
    # 优先级：BOSS > 高密度 > 高施法数，最多 4 波
    scored = []
    for wl in waves_l:
        is_boss = wl.get("is_boss", 0)
        density = wl.get("density", 0)
        casts = wl.get("total_casts", 0)
        score = (5 if is_boss else 0) + density * 10 + casts * 0.01
        scored.append((score, wl))
    scored.sort(key=lambda x: -x[0])

    lines.append("### 🎯 关键波次施法序列对比")
    lines.append("")
    lines.append(f"选取 {min(len(scored), 4)} 个高压波次（分数加权：BOSS+5 / 密度×10 / 施法数×0.01）：")
    lines.append("")

    for rank, (score, wl) in enumerate(scored[:4]):
        wid = wl.get("wave_id", "?")
        name = wl.get("name", "?")
        dtype = "BOSS" if wl.get("is_boss", 0) else "小怪"
        dur = wl.get("duration_s", 0)
        casts_l = wl.get("casts_simple", [])
        top_l = wl.get("top_skills", [])
        wb = next((w for w in waves_b if w.get("wave_id") == wid), None)
        casts_b = wb.get("casts_simple", []) if wb else []
        top_b = wb.get("top_skills", []) if wb else []

        lines.append(f"#### 波次 {wid}：{name}（{dtype}，{dur}s，密度 {wl.get('density', 0):.2f}/s）")
        lines.append("")

        # 学习者 Top 技能
        top_l_str = "、".join(f"{s['name']}×{s['count']}" for s in top_l[:5])
        top_b_str = "、".join(f"{s['name']}×{s['count']}" for s in top_b[:5]) if top_b else "（无教练对比）"
        lines.append(f"- **学习者高频技能**: {top_l_str}")
        lines.append(f"- **教练高频技能**: {top_b_str}")
        lines.append("")

        # 施法序列对比表（取前 12 个施法做对比样本）
        lines.append("| # | 学习者施法 | 教练施法（同窗口） |")
        lines.append("|---|---|---|")
        max_seq = max(len(casts_l), len(casts_b))
        sample_n = min(max_seq, 12)
        for i in range(sample_n):
            l_cast = casts_l[i] if i < len(casts_l) else ""
            l_name = l_cast.get("s", "") if isinstance(l_cast, dict) else ""
            b_cast = casts_b[i] if i < len(casts_b) else ""
            b_name = b_cast.get("s", "") if isinstance(b_cast, dict) else ""
            lines.append(f"| {i+1} | {l_name or '—'} | {b_name or '—'} |")
        if max_seq > 12:
            lines.append(f"| ... | *共 {len(casts_l)} 次施法* | *共 {len(casts_b)} 次施法* |")
        lines.append("")

        # 诊断标记（自动识别常见问题模式）
        l_names = [c.get("s", "") for c in casts_l if isinstance(c, dict)]
        issues = []
        if is_healing:
            foam_count = sum(1 for n in l_names if n in ("复苏之雾", "抚慰之雾"))
            if foam_count >= 2:
                issues.append(f"读条/铺雾技能出现 {foam_count} 次，浪费 GCD")
        if is_brewmaster:
            has_fortbrew = any(n in ("壮胆酒", "禅悟状态") for n in l_names)
            has_kegsmash = any(n == "醉酿投" for n in l_names)
            has_firebreath = any(n == "火焰之息" for n in l_names)
            if not has_kegsmash:
                issues.append("波次中未使用醉酿投，循环缺失")
            if not has_firebreath:
                issues.append("波次中未使用火焰之息，AOE/减伤丢失")
            if not has_fortbrew and is_boss:
                issues.append("BOSS波次未使用壮胆酒/禅悟状态，注意减伤链")
            first3 = l_names[:3] if len(l_names) >= 3 else l_names
            if first3 and first3[0] not in ("醉酿投",):
                issues.append("接怪起手首技能非醉酿投，可能丢失初始仇恨")
        diag_text = '；'.join(issues) if issues else '—'
        lines.append(f"**诊断**：{diag_text}")
        lines.append("")

    # --- 施法节奏总结 ---
    lines.append("### 📊 施法节奏总结")
    lines.append("")
    l_total = sum(w.get("total_casts", 0) for w in waves_l)
    b_total = sum(w.get("total_casts", 0) for w in waves_b)
    l_avg_density = data.get("summary", {}).get("learner_avg_density", 0)
    b_avg_density = data.get("summary", {}).get("benchmark_avg_density", 0)
    lines.append(f"| 维度 | 学习者 | 教练 | 差距 |")
    lines.append(f"|---|---|---|---|")
    lines.append(f"| 总施法次数 | {l_total} | {b_total} | {l_total - b_total:+d} |")
    lines.append(f"| 平均施法密度 | {l_avg_density:.2f}/s | {b_avg_density:.2f}/s | {l_avg_density - b_avg_density:+.2f}/s |")
    lines.append(f"| 波次数 | {len(waves_l)} | {len(waves_b)} | — |")
    lines.append("")

    log(f"📊 施法时间轴对比表已生成（{len(waves_l)}波，{min(len(scored),4)}波详细对比）")
    return lines


def _write_placeholder_skeleton(code: str, skeleton_name: str, is_healing: bool,
                                   is_brewmaster: bool = False,
                                   bm_profile_path: Path | None = None,
                                   comparison_path: Path | None = None):
    """直写占位骨架（当 report_builder 不存在时）

    如提供 bm_profile_path，从基准配置中读取技能次数并填入总览表。
    如提供 comparison_path，从 events API JSON 中自动生成逐波次施法对比表。

    Args:
        code: WCL 报告代码
        skeleton_name: 骨架文件名（不含路径，写在 CACHE_DIR）
        is_healing: 是否为治疗模式（T 系列）
        bm_profile_path: 基准配置文件路径，如存在则自动填充技能次数行
        comparison_path: events API 对比 JSON 路径，如存在则自动生成施法时间轴对比
    """
    series_label = "M 系列" if is_brewmaster else ("T 系列" if is_healing else "X 系列")
    metric_label = "DTPS"
    benchmark_label = "硬玩复仇"
    metric_label_col = "DTPS"
    metric_label2 = "自疗HPS"
    if is_healing:
        metric_label = "HPS"
        metric_label_col = "HPS"
        metric_label2 = ""
        benchmark_label = "绿绿月光"
    elif not is_brewmaster:
        metric_label = "DPS"
        metric_label_col = "DPS"
        metric_label2 = ""
        benchmark_label = "清心"

    bm_skill_rows = []
    if bm_profile_path and bm_profile_path.exists():
        try:
            raw = bm_profile_path.read_text(encoding="utf-8")
            profile = json.loads(raw)
            skills = profile.get("skill_composition", {})
            overview_skills = {
                "t": ["作茧缚命", "壮胆酒", "复苏之雾", "神龙之赐", "氤氲之雾", "天神御身"],
                "x": ["操控时间", "法术反制", "鲁莽药水", "镜像", "寒冰护体"],
                "b": ["壮胆酒", "活血酒", "禅悟状态", "玄牛下凡", "玄牛之赐", "淬火神酿", "醉酿投", "火焰之息"],
            }
            key = "b" if is_brewmaster else ("t" if is_healing else "x")
            for sk_name in overview_skills.get(key, []):
                if sk_name in skills:
                    bm_hits = skills[sk_name].get("hits", 0)
                    bm_skill_rows.append(
                        f"| {sk_name} | {{{{LEARNER_{sk_name}}}}} | **{bm_hits}次** | {{{{GAP_{sk_name}}}}} |"
                    )
                else:
                    bm_skill_rows.append(
                        f"| {sk_name} | {{{{LEARNER_{sk_name}}}}} | — | {{{{GAP_{sk_name}}}}} |"
                    )
            log(f"📊 基准配置已填充 {len(bm_skill_rows)} 技能次数行")
        except Exception as e:
            log(f"⚠️ 读取基准配置填充技能次数失败: {e}")

    # 从 comparison JSON 读取逐波次数据 → 自动生成施法时间轴对比
    wave_comparison_lines = []
    if comparison_path and comparison_path.exists():
        wave_comparison_lines = _build_wave_comparison_tables(comparison_path, is_healing, is_brewmaster)

    coach_name = "硬玩复仇" if is_brewmaster else ("孙青云" if is_healing else "清心")
    icon = "🍺" if is_brewmaster else ("🪷" if is_healing else "🧊")

    lines = [
        f"# {icon} {series_label} 报告骨架（自动生成）",
        "",
        "## 📈 总览",
        f"| 指标 | 学习者 | {benchmark_label} | 差距 |",
        "|---|---|---|---|",
        f"| {metric_label_col} | {{{{{metric_label_col}}}}} | {{{{{benchmark_label}_{metric_label_col}}}}} | {{{{{metric_label_col}_GAP}}}} |",
        f"{'| 自疗HPS | {{SELF_HPS}} | {{BENCHMARK_SELF_HPS}} | {{SELF_HPS_GAP}} |' if is_brewmaster else ''}",
        "| 死亡 | {{DEATHS}} | 0 | |",
        "| 打断 | {{INTERRUPTS}} | {{BENCHMARK_INTERRUPTS}} | |",
        *bm_skill_rows,  # 如无基准数据则为空列表 → 不输出额外行
        "",
        "## 🔧 技能使用评估",
        "| 技能 | 学习者次数 | 教练次数 | 差距 | 评级 | 分析 |",
        "|---|---|---|---|---|---|",
        "| {{SKILL_1}} | {{N1}} | {{B1}} | {{G1}} | 🟡 | {{A1}} |",
        "",
        "## ✅ 做得好",
        "{{DO_WELL_FINAL}}",
        "",
        "## ❌ 需要改进",
        "{{IMPROVE_FINAL}}",
        "",
        "## 💀 死亡分析",
        "{{DEATH_ROOT_CAUSE}}",
        "",
        "## 📅 改进计划",
        "{{TRAINING_TASKS}}",
        "",
        "## 💬 " + coach_name + "的话",
        "{{COACH_NOTE}}",
        "",
        "---",
        "",
        "## 🎯 施法时间轴对比（逐波次）",
        "",
        *wave_comparison_lines,  # 自动生成的对比表，空列表则输出说明
        "",
    ]
    if not wave_comparison_lines:
        lines.insert(-1, "> ⚠️ 未找到 comparison JSON，无法生成逐波次施法时间轴对比。")
        lines.insert(-1, "> 请确认 events API 管线是否已执行。")

    (CACHE_DIR / skeleton_name).write_text("\n".join(lines))
    log(f"📝 {'治疗' if is_healing else '输出'}向占位骨架已生成: {skeleton_name}")


# ── CLI ──────────────────────────────────────────────────────────────

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析 CLI 参数（可被测试导入）"""
    parser = argparse.ArgumentParser(
        description="M+ 通用管线脚本 — 一次调用产出全部数据文件",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # --profile 模式（个人教练）
  mplus_pipeline.py --profile dongrou --report-code CBmb7jL812rhaXQp --fight-id 4

  # --mode team 模式（团队分析）
  mplus_pipeline.py --mode team --report-code gkNF6VHnWY3tLamT --fight-id 4

  # 旧 x/t/m 模式（已废弃，输出 warning）
  mplus_pipeline.py x --report-code CBmb7jL812rhaXQp --fight-id 4
        """
    )

    # ── 新入口（一等公民） ──
    parser.add_argument("--profile", required=False,
                        help="用户档案 ID（如 dongrou/taozi/meishu，个人教练模式）")
    parser.add_argument("--mode", choices=["team"], required=False, dest="mode_flag",
                        help="团队分析模式（独立入口，不等价于 --profile）")

    # ── 旧入口（已废弃，v6.0 删除） ──
    parser.add_argument("mode", nargs="?",
                        choices=["team", "x", "t", "m"], default=None,
                        help="[DEPRECATED] x/t/m 已废弃，使用 --profile 代替")

    # ── 通用参数 ──
    parser.add_argument("--report-code", required=True, help="WCL 报告代码")
    parser.add_argument("--fight-id", required=True, type=int,
                        help="WCL 链接中的战斗 ID")
    parser.add_argument("--output-dir", help="输出目录（默认 data/cache/{code}/）")
    parser.add_argument("--include-skeleton", action="store_true",
                        help="同时生成报告骨架")
    parser.add_argument("--learner-source", type=int, default=3,
                        help="学习者角色 sourceID（默认 3）")

    # ── --profile 覆盖参数 ──
    parser.add_argument("--benchmark-report", help="覆盖档案中的基准报告代码")
    parser.add_argument("--benchmark-fight", type=int, help="覆盖档案中的基准 fight_id")

    # ── 旧参数（兼容保留，实际被忽略） ──
    parser.add_argument("--benchmark-char", help="[DEPRECATED] 教练角色名")
    parser.add_argument("--benchmark-server", help="[DEPRECATED] 教练服务器")
    parser.add_argument("--benchmark-encounter", type=int, help="[DEPRECATED] 副本 encounter_id")
    parser.add_argument("--learner-name", default="",
                        help="[DEPRECATED] 学习者角色名")

    return parser.parse_args(argv)


def main():
    args = parse_args()

    # 清理缓存
    clean_pycache()

    # 检查: --profile 和旧 mode 不可同时为 team
    if args.profile and (args.mode == "team" or args.mode_flag == "team"):
        log("⚠️ --profile 和 --mode team 互斥，--profile 优先生效")
        args.mode = None; args.mode_flag = None

    log(f"🚀 启动: --profile={args.profile}, --mode={args.mode or args.mode_flag}, "
         f"报告={args.report_code}, fight={args.fight_id}")

    try:
        # ── 优先：--profile 模式（个人教练） ──
        if args.profile:
            profile = load_profile(args.profile)
            # CLI 覆盖
            profile.apply_cli_overrides(
                benchmark_report=args.benchmark_report,
                benchmark_fight=args.benchmark_fight,
            )
            strategy = CoachingStrategy(
                profile=profile,
                report_code=args.report_code,
                fight_id=args.fight_id,
                learner_source=args.learner_source,
                output_dir=Path(args.output_dir) if args.output_dir else None,
            )
            out = strategy.run()

        # ── 第二优先：--mode team（团队分析） ──
        elif args.mode == "team" or args.mode_flag == "team":
            out = run_team_mode(args)

        # ── 第三：旧 x/t/m 模式（deprecated） ──
        elif args.mode in ("x", "t", "m"):
            profile_map = {"x": "dongrou", "t": "taozi", "m": "meishu"}
            profile_id = profile_map[args.mode]
            print(f"[WARNING] --mode {args.mode} is deprecated, "
                  f"use --profile {profile_id} instead", file=sys.stderr)
            profile = load_profile(profile_id)
            profile.apply_cli_overrides(
                benchmark_report=args.benchmark_report,
                benchmark_fight=args.benchmark_fight,
            )
            strategy = CoachingStrategy(
                profile=profile,
                report_code=args.report_code,
                fight_id=args.fight_id,
                learner_source=args.learner_source,
                output_dir=Path(args.output_dir) if args.output_dir else None,
            )
            out = strategy.run()

        log(f"🎉 管线完成！输出目录: {out}")
        log(f"📋 manifest: {out / 'manifest.json'}")
        print(json.dumps({"status": "ok", "output_dir": str(out), "manifest": str(out / "manifest.json")}))

    except Exception as e:
        log(f"💥 管线失败: {e}")
        print(json.dumps({"status": "error", "error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
