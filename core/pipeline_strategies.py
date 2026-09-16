#!/usr/bin/env python3
"""
管线策略模块 (pipeline_strategies.py)

参数化单 CoachingStrategy 类，ROLE_CONFIGS 驱动三个角色的职责差异。
不创建 ABC 子类，所有差异通过配置 + override hooks 处理。

Usage:
    from core.pipeline_strategies import CoachingStrategy, ROLE_CONFIGS, dispatch_strategy
    strategy = CoachingStrategy(profile, report_code, fight_id)
    output_dir = strategy.run()
"""

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Optional

from core.config import get_api_key as _get_api_key
from core.profile_loader import Profile


# ── 项目路径常量 ──

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WCL_DB_DIR = PROJECT_ROOT / "data" / "wcl_db"
CACHE_DIR = PROJECT_ROOT / "data" / "cache"
KNOWLEDGE_BASE_DIR = PROJECT_ROOT / "data" / "knowledge_base"
WIKI_CONCEPTS_DIR = Path("/mnt/c/Viewintech/0_GCKJ/代码/PineCone/concepts")


# ── 角色配置 ──

ROLE_CONFIGS: dict[str, dict[str, Any]] = {
    "dps": {
        "overview_rows": ["总伤害", "DPS"],
        "cast_whitelist": [],
        "death_depth": "normal",
        "extra_events_source": None,
    },
    "healer": {
        "overview_rows": ["总治疗", "HPS", "过量%", "总伤害", "DPS"],
        "cast_whitelist": [],
        "death_depth": "normal",
        "extra_events_source": "healing",
    },
    "tank": {
        "overview_rows": ["总伤害", "DPS", "DTPS", "自疗HPS", "死亡次数"],
        "cast_whitelist": [],
        "death_depth": "full",
        "extra_events_source": None,
    },
}


# ── Helpers ──────────────────────────────────────────────────────────


def _log(msg: str):
    print(f"[pipeline_strategies] {msg}", flush=True)


def _run_script(script_name: str, args: list[str], timeout: int = 600) -> str:
    """运行 core/{script_name} 并返回 stdout"""
    module_name = f"core.{script_name.replace('.py', '')}"
    cmd = [sys.executable, "-m", module_name] + args
    env = os.environ.copy()
    env["WCL_API_KEY"] = _get_api_key()
    env["PYTHONPATH"] = str(PROJECT_ROOT)

    _log(f"运行: {' '.join(cmd)}")
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
        _log(f"\u274c {script_name} \u5931\u8d25 (exit={result.returncode}, {elapsed:.1f}s)")
        _log(f"stderr: {stderr[:500]}")
        raise RuntimeError(f"{script_name} \u5931\u8d25: {stderr[:300]}")
    _log(f"\u2705 {script_name} \u5b8c\u6210 ({elapsed:.1f}s)")
    return result.stdout


# ── CoachingStrategy ──

class CoachingStrategy:
    """参数化单策略类，ROLE_CONFIGS 驱动职责差异。

    模板方法：固定执行顺序 Phase 0–5，每个 Phase 可被 profile.role 的配置驱动。
    """

    def __init__(
        self,
        profile: Profile,
        report_code: str,
        fight_id: int,
        learner_source: int = 3,
        output_dir: Optional[Path] = None,
        benchmark_report: Optional[str] = None,
        benchmark_fight: Optional[int] = None,
        **kwargs,
    ):
        self.profile = profile
        self.role_config = ROLE_CONFIGS[profile.role].copy()
        self.report_code = report_code
        self.fight_id = fight_id
        self.learner_source = learner_source
        self.output_dir = output_dir or Path(
            f"data/reports/{profile.id}_{report_code}"
        )
        self.benchmark_report = benchmark_report or profile.benchmark_report
        self.benchmark_fight = benchmark_fight or profile.benchmark_fight
        self.manifest: dict[str, Any] = {}
        self.errors: list[str] = []
        self.warnings: list[str] = []

        # Extra keyword args for future flexibility
        for key, value in kwargs.items():
            setattr(self, key, value)

    def run(self) -> Path:
        """模板方法：固定执行顺序 Phase 0–5"""
        self._start_time = time.time()
        self.phase0_knowledge_gate()
        self.phase1_wcl_gate()
        self.phase2_fetch_data()
        self.phase3_aggregate()
        self.phase4_events_pipeline()
        self.phase5_skeleton_and_report()
        self.write_manifest()
        return self.output_dir

    # ── 内部辅助 ───────────────────────────────────────────────────

    def _ensure_dir(self, path: Path):
        path.mkdir(parents=True, exist_ok=True)

    def _get_db_path(self, report_code: str) -> Path:
        return WCL_DB_DIR / f"{report_code}.db"

    def _ensure_cache_file(self, base_name: str, code: str):
        """确保 {base_name}_{code}.txt 存在（从无后缀复制）"""
        src = CACHE_DIR / f"{base_name}.txt"
        dst = CACHE_DIR / f"{base_name}_{code}.txt"
        if src.exists() and not dst.exists():
            shutil.copy2(src, dst)

    def _get_events_mode(self) -> str:
        """根据 role 返回 events_pipeline mode 参数"""
        role = self.profile.role
        if role == "healer":
            return "t"
        elif role == "tank":
            return "b"
        return "x"

    # ── Phase 0: 知识卡片校验 ──

    def phase0_knowledge_gate(self):
        """校验知识卡片存在：wiki_prefix 来自 profile"""
        prefix = self.profile.wiki_prefix
        if not prefix:
            self.warnings.append("profile.wiki_prefix 为空，跳过知识卡片校验")
            return

        pattern = f"{prefix}-*.md"
        card_dir = WIKI_CONCEPTS_DIR

        if not card_dir.exists():
            self.warnings.append(f"知识卡片目录不存在: {card_dir}")
            return

        cards = list(card_dir.glob(pattern))
        if not cards:
            self.warnings.append(
                f"未找到知识卡片: {card_dir / pattern}"
            )
            return

        _log(f"知识卡片校验通过: {len(cards)} 张 ({prefix})")

    # ── Phase 1: WCL 可达性校验 ──

    def phase1_wcl_gate(self):
        """校验 WCL 报告可达性"""
        key = _get_api_key()
        code = self.report_code

        # 1. 校验报告可达性
        try:
            url = f"https://www.warcraftlogs.com/v1/report/fights/{code}?api_key={key}"
            data = json.loads(
                urllib.request.urlopen(url, timeout=30).read().decode()
            )
        except Exception as e:
            self.warnings.append(f"WCL 报告不可达 ({code}): {e}")
            self.errors.append(f"phase1: 报告不可达: {e}")
            return

        # 2. 确认 fight_id 存在于报告中
        fights = data.get("fights", [])
        fight = next((f for f in fights if f.get("id") == self.fight_id), None)
        if not fight:
            self.errors.append(
                f"phase1: fight_id={self.fight_id} 在报告中未找到"
            )
            return
        _log(f"fight_id={self.fight_id} 存在")

        # 3. 确认 learner_source 对应的玩家在 damage-done 表中存在
        fight_start = fight.get("start_time", 0)
        fight_end = fight.get("end_time", 0)
        try:
            url = (
                f"https://www.warcraftlogs.com/v1/report/tables/"
                f"damage-done/{code}?start={fight_start}&end={fight_end}&api_key={key}"
            )
            dd_data = json.loads(
                urllib.request.urlopen(url, timeout=30).read().decode()
            )
            entries = dd_data.get("entries", [])
            source_found = any(
                e.get("id") == self.learner_source for e in entries
            )
            if not source_found:
                self.warnings.append(
                    f"learner_source (sourceid={self.learner_source}) "
                    f"在 damage-done 表中未找到"
                )
            else:
                _log(f"learner_source (id={self.learner_source}) 存在")
        except Exception as e:
            self.warnings.append(f"无法校验 learner_source: {e}")

    # ── Phase 2: 数据拉取 ──

    def phase2_fetch_data(self):
        """v1_pipeline ×2（学习者 + 基准）"""
        self._ensure_dir(WCL_DB_DIR)

        # 学习者
        code = self.report_code
        db_path = self._get_db_path(code)
        if db_path.exists() and db_path.stat().st_size > 1024:
            _log(f"学习者 DB 缓存命中: {db_path}")
        else:
            try:
                _run_script("v1_pipeline.py", [code, "--fight-id", str(self.fight_id)])
            except RuntimeError as e:
                self.warnings.append(f"v1_pipeline (学习者) 失败: {e}")

        # 基准
        bm_report = self.benchmark_report or self.profile.benchmark_report
        if bm_report:
            bm_fight = self.benchmark_fight or self.profile.benchmark_fight
            bm_db = self._get_db_path(bm_report)
            if bm_db.exists() and bm_db.stat().st_size > 1024:
                _log(f"基准 DB 缓存命中: {bm_db}")
            else:
                try:
                    _run_script(
                        "v1_pipeline.py",
                        [bm_report, "--fight-id", str(bm_fight)],
                    )
                except RuntimeError as e:
                    self.warnings.append(f"v1_pipeline (基准) 失败: {e}")

        # 如果 extra_events_source 为 truthy，记录以供 phase4 使用
        extra = self.role_config.get("extra_events_source")
        if extra:
            _log(f"extra_events_source={extra} — phase4 将使用对应模式拉取")

    # ── Phase 3: 聚合分析 ──

    def phase3_aggregate(self):
        """comparison_engine + m2_standalone_summary"""
        self._ensure_dir(CACHE_DIR)

        code = self.report_code
        db_path = str(self._get_db_path(code).resolve())

        # m2_standalone_summary for learner
        try:
            _run_script("m2_standalone_summary.py", [db_path, code])
        except RuntimeError as e:
            self.warnings.append(f"m2_standalone_summary 跳过: {e}")

        # Rename cache files with code suffix for output collection
        for base in ["m2_meta", "m2_group_a", "m2_group_b", "m2_group_c"]:
            self._ensure_cache_file(base, code)

        # comparison_engine (requires benchmark DB)
        bm_report = self.benchmark_report or self.profile.benchmark_report
        if bm_report:
            bm_code = bm_report
            bm_db_path = str(self._get_db_path(bm_code).resolve())
            output_path = str(CACHE_DIR / f"comparison_{code}.json")
            try:
                _run_script("comparison_engine.py", [
                    "--our-db", db_path, "--our-code", code,
                    "--top-db", bm_db_path, "--top-code", bm_code,
                    "--output", output_path,
                ])
            except RuntimeError as e:
                self.warnings.append(f"comparison_engine 跳过: {e}")

    # ── Phase 4: Events API 提取 ──

    def phase4_events_pipeline(self):
        """events API 提取施法序列"""
        bm_report = self.benchmark_report or self.profile.benchmark_report
        if not bm_report:
            self.warnings.append("phase4: 无基准报告，跳过 events_pipeline")
            return

        bm_fight = self.benchmark_fight or self.profile.benchmark_fight
        if not bm_fight:
            self.warnings.append("phase4: 无基准 fight_id，跳过 events_pipeline")
            return

        try:
            # 1. 获取基准 fight 时间窗口
            key = _get_api_key()
            url = f"https://www.warcraftlogs.com/v1/report/fights/{bm_report}?api_key={key}"
            bm_data = json.loads(
                urllib.request.urlopen(url, timeout=30).read().decode()
            )
            bm_fights = bm_data.get("fights", [])
            bm_fight_obj = next(
                (f for f in bm_fights if f.get("id") == bm_fight), None
            )
            if not bm_fight_obj:
                self.warnings.append(
                    f"phase4: 基准 fight_id={bm_fight} 未找到"
                )
                return
            bm_start = bm_fight_obj.get("start_time", 0)
            bm_end = bm_fight_obj.get("end_time", 0)

            # 2. 获取基准 source ID（通过 damage-done / healing 表）
            bm_char = self.profile.benchmark_char
            if not bm_char:
                self.warnings.append("phase4: benchmark_char 为空")
                return

            bm_sourceid = self._find_source_id(
                bm_report, bm_char, bm_start, bm_end
            )
            if bm_sourceid is None:
                self.warnings.append(
                    f"phase4: 无法找到基准角色 {bm_char} 的 source ID"
                )
                return
            _log(f"基准 sourceID: {bm_sourceid}")

            # 3. 从 DB 读取死亡事件
            death_events = self._read_death_events()

            # 4. 调用 events_pipeline 的 build_x_comparison
            from core.events_pipeline import build_x_comparison

            mode = self._get_events_mode()
            output_path = str(
                CACHE_DIR / f"{mode}_comparison_{self.report_code}.json"
            )

            result = build_x_comparison(
                learner_code=self.report_code,
                learner_fight_id=self.fight_id,
                learner_sourceid=self.learner_source,
                benchmark_code=bm_report,
                benchmark_fight_id=bm_fight,
                benchmark_sourceid=bm_sourceid,
                death_events=death_events,
                output_path=output_path,
                mode=mode,
            )
            if result.get("error"):
                self.warnings.append(
                    f"events_pipeline 失败: {result['error']}"
                )
            else:
                _log("events_pipeline 完成")

        except Exception as e:
            self.warnings.append(f"phase4 events_pipeline 跳过: {e}")

    def _find_source_id(
        self,
        report_code: str,
        char_name: str,
        fight_start: int = 0,
        fight_end: int = 99999999,
    ) -> Optional[int]:
        """从 damage-done / healing 表查找角色 ID（忽略大小写）"""
        key = _get_api_key()
        name_lower = char_name.lower()

        for table_name in ("damage-done", "healing"):
            url = (
                f"https://www.warcraftlogs.com/v1/report/tables/"
                f"{table_name}/{report_code}?start={fight_start}&end={fight_end}&api_key={key}"
            )
            try:
                data = json.loads(
                    urllib.request.urlopen(url, timeout=30).read().decode()
                )
                for e in data.get("entries", []):
                    if e.get("name", "").lower() == name_lower:
                        return e["id"]
            except Exception:
                continue
        return None

    def _read_death_events(self) -> list[dict]:
        """从 SQLite DB 读取死亡事件（毫秒时间戳）"""
        db_path = str(self._get_db_path(self.report_code).resolve())
        try:
            conn = sqlite3.connect(db_path)
            rows = conn.execute(
                "SELECT timestamp, ability_name FROM event "
                "WHERE type='death' AND source=?",
                (self.profile.name,),
            ).fetchall()
            conn.close()
            return [
                {"timestamp": r[0], "ability_name": r[1] or "?"}
                for r in rows
            ]
        except Exception:
            return []

    # ── Phase 5: 报告骨架构建 ──

    def phase5_skeleton_and_report(self):
        """report_skeleton 生成骨架"""
        code = self.report_code

        # 确保 cache 文件一致性（后缀版本供输出收集用）
        self._ensure_cache_file("m2_meta", code)
        self._ensure_cache_file("m2_group_a", code)
        self._ensure_cache_file("m2_group_b", code)
        self._ensure_cache_file("m2_group_c", code)

        # 调用 report_skeleton（读取无后缀的 cache 文件）
        try:
            _run_script("report_skeleton.py", [code])
            _log("report_skeleton 完成")
        except RuntimeError as e:
            self.warnings.append(f"report_skeleton 跳过: {e}")

    # ── Manifest 写入 ──

    def write_manifest(self):
        """将执行元数据写入 self.output_dir / manifest.json"""
        self._ensure_dir(self.output_dir)

        # 收集产出文件
        collected: list[dict[str, Any]] = []

        # code-suffixed cache files
        if CACHE_DIR.exists():
            for suffix in ("txt", "json", "md"):
                for f in sorted(CACHE_DIR.glob(f"*_{self.report_code}.{suffix}")):
                    dst = self.output_dir / f.name
                    if not dst.exists():
                        shutil.copy2(f, dst)
                    collected.append({
                        "path": f.name,
                        "size": dst.stat().st_size if dst.exists() else 0,
                        "sha256": (
                            hashlib.sha256(dst.read_bytes()).hexdigest()[:16]
                            if dst.exists() else "0"
                        ),
                    })

        # comparison JSON (mode-specific)
        mode = self._get_events_mode()
        comp = CACHE_DIR / f"{mode}_comparison_{self.report_code}.json"
        if comp.exists():
            found = any(c["path"] == comp.name for c in collected)
            if not found:
                dst = self.output_dir / comp.name
                if not dst.exists():
                    shutil.copy2(comp, dst)
                collected.append({
                    "path": comp.name,
                    "size": dst.stat().st_size if dst.exists() else 0,
                    "sha256": (
                        hashlib.sha256(dst.read_bytes()).hexdigest()[:16]
                        if dst.exists() else "0"
                    ),
                })

        # skeleton
        skel = CACHE_DIR / "m2_skeleton.md"
        if skel.exists():
            found = any(c["path"] == skel.name for c in collected)
            if not found:
                dst = self.output_dir / skel.name
                if not dst.exists():
                    shutil.copy2(skel, dst)
                collected.append({
                    "path": skel.name,
                    "size": dst.stat().st_size if dst.exists() else 0,
                    "sha256": (
                        hashlib.sha256(dst.read_bytes()).hexdigest()[:16]
                        if dst.exists() else "0"
                    ),
                })

        manifest = {
            "pipeline_version": "6.0.0",
            "profile_id": self.profile.id,
            "report_code": self.report_code,
            "fight_id": self.fight_id,
            "role": self.profile.role,
            "files": collected,
            "errors": self.errors,
            "warnings": self.warnings,
            "execution_time_sec": round(
                time.time() - getattr(self, "_start_time", time.time()), 1
            ),
        }

        manifest_path = self.output_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2)
        )
        _log(f"manifest.json 已写入 ({len(collected)} files)")


# ── Dispatch ────────────────────────────────────────────────────────


def dispatch_strategy(
    profile: Profile,
    report_code: str,
    fight_id: int,
    **kwargs,
) -> CoachingStrategy:
    """根据 profile 分派到对应的策略实例。

    当前返回 CoachingStrategy（单类方案），未来可扩展为不同策略类。
    """
    return CoachingStrategy(
        profile=profile,
        report_code=report_code,
        fight_id=fight_id,
        **kwargs,
    )
