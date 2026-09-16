#!/usr/bin/env python3
"""
mplus_pipeline.py 验收测试

基于 SKILL 文件中的需求编写测试用例。
三个 mode 各有明确的输出文件清单。

用法:
  PYTHONPATH=. python3 tests/test_mplus_pipeline.py
  PYTHONPATH=. python3 tests/test_mplus_pipeline.py -v
  PYTHONPATH=. python3 tests/test_mplus_pipeline.py TestModeM  # 只跑 M mode
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 已知测试数据
TEST_META = {
    "m_mode": {
        "report_code": "gkNF6VHnWY3tLamT",
        "fight_id": 4,
        "description": "已知 M2 测试数据（三头议会 +14）",
    },
    "x_mode": {
        "report_code": "CBmb7jL812rhaXQp",
        "fight_id": 4,
        "benchmark_char": "qingxingood",
        "benchmark_report": "xChHgJR6XBr9mYtN",
        "benchmark_fight": 3,
        "description": "已知 X 系列测试数据（示例学员+10 风行塔 vs 清心+19 风行塔）",
    },
    "t_mode": {
        "report_code": "aWZMQbFRAd4nKY7c",
        "fight_id": 1,
        "benchmark_char": "绿绿月光",
        "benchmark_report": "DLQHbFkqyX14dvgr",
        "benchmark_fight": 92,
        "description": "已知 T 系列测试数据（示例学员风行者+7 vs 绿绿月光艾杰斯亚+21）",
    },
}

# ── 测试数据目录 ──
DATA_DIR = PROJECT_ROOT / "data"
WCL_DB_DIR = DATA_DIR / "wcl_db"
CACHE_DIR = DATA_DIR / "cache"
XIAOXUE_DIR = DATA_DIR / "xiaoxue"

WCL_API_KEY = os.environ.get("WCL_API_KEY", "")
REQUIRES_API = bool(WCL_API_KEY)


@unittest.skipUnless(os.environ.get("WCL_API_KEY"), "需 WCL_API_KEY（联网集成测试）")
class TestModeM(unittest.TestCase):
    """M2 全队混合分析 — m mode 验收测试（需 WCL_API_KEY）"""

    @classmethod
    def setUpClass(cls):
        """跑一次管线，共享结果"""
        cls.code = TEST_META["m_mode"]["report_code"]
        cls.fight_id = TEST_META["m_mode"]["fight_id"]
        cls.output_dir = Path(tempfile.mkdtemp(prefix="mplus_test_m_"))

        from core import mplus_pipeline
        args = mplus_pipeline.parse_args([
            "m", "--report-code", cls.code,
            "--fight-id", str(cls.fight_id),
            "--output-dir", str(cls.output_dir),
        ])
        mplus_pipeline.run_m_mode(args)
        cls.manifest_path = cls.output_dir / "manifest.json"
        cls.manifest = json.loads(cls.manifest_path.read_text()) if cls.manifest_path.exists() else {}

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.output_dir, ignore_errors=True)

    # ── 测试用例 1: manifest 完整性 ──
    def test_01_manifest_exists(self):
        """M1: 管线完成后 manifest.json 必须存在"""
        self.assertTrue(self.manifest_path.exists(), "manifest.json 不存在")

    def test_02_manifest_contains_required_fields(self):
        """M2: manifest 必须包含 required 字段"""
        required_keys = {"pipeline_version", "mode", "report_code", "timestamp", "files", "errors"}
        self.assertTrue(required_keys.issubset(self.manifest.keys()),
                        f"manifest 缺少字段: {required_keys - set(self.manifest.keys())}")
        self.assertEqual(self.manifest["mode"], "m")
        self.assertEqual(self.manifest["report_code"], self.code)

    def test_03_manifest_has_no_critical_errors(self):
        """M3: manifest.errors 应为空"""
        self.assertEqual(len(self.manifest.get("errors", [])), 0,
                         f"manifest 包含非预期 errors: {self.manifest.get('errors')}")

    def test_04_required_output_files_m_mode(self):
        """M4: m mode 必须产出全部 4 个 group 文件"""
        file_paths = {f["path"] for f in self.manifest.get("files", [])}
        required_files = {
            f"m2_meta_{self.code}.txt",
            f"m2_group_a_{self.code}.txt",
            f"m2_group_b_{self.code}.txt",
            f"m2_group_c_{self.code}.txt",
        }
        missing = required_files - file_paths
        self.assertEqual(len(missing), 0, f"缺少必输文件: {missing}")

    def test_05_output_files_not_empty(self):
        """M5: 所有产出文件大小 > 0"""
        for f in self.manifest.get("files", []):
            self.assertGreater(f["size"], 0, f"文件 {f['path']} 大小为 0")
            self.assertNotEqual(f["sha256"], "0", f"文件 {f['path']} sha256 未计算")

    def test_06_has_benchmark_data(self):
        """M6: 应产出 per_spec_benchmarks.json（标杆对比数据）"""
        file_paths = {f["path"] for f in self.manifest.get("files", [])}
        self.assertIn("per_spec_benchmarks.json", file_paths,
                      "m mode 应包含标杆对比数据")


@unittest.skipUnless(os.environ.get("WCL_API_KEY"), "需 WCL_API_KEY（联网集成测试）")
class TestModeX(unittest.TestCase):
    """X 系列教练分析 — x mode 验收测试"""

    @classmethod
    def setUpClass(cls):
        cls.code = TEST_META["x_mode"]["report_code"]
        cls.fight_id = TEST_META["x_mode"]["fight_id"]
        cls.bm_char = TEST_META["x_mode"]["benchmark_char"]
        cls.bm_report = TEST_META["x_mode"]["benchmark_report"]
        cls.bm_fight = TEST_META["x_mode"]["benchmark_fight"]
        cls.output_dir = Path(tempfile.mkdtemp(prefix="mplus_test_x_"))

        from core import mplus_pipeline
        args = mplus_pipeline.parse_args([
            "x", "--report-code", cls.code,
            "--fight-id", str(cls.fight_id),
            "--output-dir", str(cls.output_dir),
            "--benchmark-char", cls.bm_char,
            "--benchmark-report", cls.bm_report,
            "--benchmark-fight", str(cls.bm_fight),
        ])
        mplus_pipeline.run_x_mode(args)
        cls.manifest_path = cls.output_dir / "manifest.json"
        cls.manifest = json.loads(cls.manifest_path.read_text()) if cls.manifest_path.exists() else {}

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.output_dir, ignore_errors=True)

    def test_01_manifest_exists(self):
        """X1: manifest.json 必须存在"""
        self.assertTrue(self.manifest_path.exists(), "manifest.json 不存在")

    def test_02_manifest_mode_x(self):
        """X2: manifest.mode == x"""
        self.assertEqual(self.manifest.get("mode"), "x")

    def test_03_manifest_has_learner_info(self):
        """X3: manifest 记录学习者信息"""
        learner = self.manifest.get("learner")
        self.assertIsNotNone(learner, "manifest 缺少 learner 字段")
        self.assertIn("name", learner)
        self.assertIn("spec", learner)

    def test_04_manifest_has_benchmark_info(self):
        """X4: manifest 记录教练基准信息"""
        bm = self.manifest.get("benchmark")
        self.assertIsNotNone(bm, "manifest 缺少 benchmark 字段")
        self.assertIn("report_code", bm)
        self.assertIn("fight_id", bm)

    def test_05_required_output_files_x_mode(self):
        """X5: x mode 必须产出骨架和 group 文件"""
        file_paths = {f["path"] for f in self.manifest.get("files", [])}

        # 骨架文件
        has_skeleton = any("skeleton" in p for p in file_paths)
        self.assertTrue(has_skeleton, "x mode 应产出骨架文件")

        # 基准档案
        has_benchmark = any("benchmark" in p.lower() or "qingxin" in p.lower() for p in file_paths)
        self.assertTrue(has_benchmark, "x mode 应产出教练基准档案")

        # group 文件（用于报告）
        for suffix in ["group_a", "group_b", "group_c"]:
            has = any(suffix in p for p in file_paths)
            self.assertTrue(has, f"x mode 应产出 m2_{suffix}")

    def test_06_no_critical_errors(self):
        """X6: manifest.errors 应为空"""
        self.assertEqual(len(self.manifest.get("errors", [])), 0,
                         f"manifest 包含 errors: {self.manifest.get('errors')}")

    def test_07_output_files_not_empty(self):
        """X7: 所有产出文件大小 > 0"""
        for f in self.manifest.get("files", []):
            self.assertGreater(f["size"], 0, f"文件 {f['path']} 大小为 0")
            self.assertNotEqual(f["sha256"], "0", f"文件 {f['path']} sha256 未计算")

    def test_08_skeleton_contains_placeholders(self):
        """X8: 骨架文件应包含报告占位符"""
        skeleton_paths = [
            p for p in self.manifest.get("files", [])
            if "skeleton" in p["path"]
        ]
        if skeleton_paths:
            skel_path = skeleton_paths[0]
            content = (self.output_dir / skel_path["path"]).read_text()
            # 应有总览表、技能评估表等章节标记
            self.assertIn("总览", content, "骨架缺少总览表")
            self.assertIn("技能", content, "骨架缺少技能评估表")
            # 应有占位符（或已填充的内容）
            has_placeholder = "{{" in content or "DIAGNOSIS" in content
            self.assertTrue(has_placeholder, "骨架应包含模型填充标记")

    def test_09_benchmark_profile_has_metrics(self):
        """X9: 教练基准档案应含治疗/伤害指标"""
        bm_file = Path(PROJECT_ROOT) / "data" / "xiaoxue" / "qingxin_benchmark_profile.json"
        if bm_file.exists():
            bm = json.loads(bm_file.read_text())
            # 应有 DPS
            self.assertIn("dps", bm, "基准档案缺少 dps")
            # 应有关键字段
            self.assertIn("source_report", bm, "基准档案缺少 source_report")
            self.assertIn("skill_composition", bm, "基准档案缺少 skill_composition")
            self.assertGreater(len(bm["skill_composition"]), 0, "基准档案技能表为空")


class TestModeXEvents(TestModeX):
    """X 系列 events API 验收测试（继承 TestModeX 的 setUpClass）"""

    def test_10_x_comparison_json_exists(self):
        """X10: events API 必须产出 x_comparison.json"""
        comparison_path = self.output_dir / "x_comparison.json"
        self.assertTrue(comparison_path.exists(), "x_comparison.json 不存在")

    def test_11_x_comparison_has_wave_data(self):
        """X11: x_comparison 包含逐波次数据"""
        comparison_path = self.output_dir / "x_comparison.json"
        if not comparison_path.exists():
            self.skipTest("x_comparison.json 未生成")
        comp = json.loads(comparison_path.read_text())

        self.assertGreater(len(comp.get("waves_learner", [])), 0,
                           "缺少学习者波次数据")
        self.assertGreater(len(comp.get("waves_benchmark", [])), 0,
                           "缺少清心波次数据")

        # 每个波次应有核心字段
        first_wave = comp["waves_learner"][0]
        self.assertIn("name", first_wave)
        self.assertIn("total_casts", first_wave)
        self.assertIn("density", first_wave)
        self.assertGreater(first_wave["total_casts"], 0, "波次施法数为0")
        self.assertGreater(first_wave["density"], 0, "波次密度为0")

    def test_12_x_comparison_has_death_healing(self):
        """X12: x_comparison 含死亡前治疗数据"""
        comparison_path = self.output_dir / "x_comparison.json"
        if not comparison_path.exists():
            self.skipTest("x_comparison.json 未生成")
        comp = json.loads(comparison_path.read_text())

        death_healing = comp.get("death_healing", [])
        self.assertGreater(len(death_healing), 0, "缺少死亡治疗数据")
        first_dh = death_healing[0]
        self.assertIn("total_healing", first_dh, "死亡治疗缺少治疗量")
        self.assertIn("death_ability", first_dh, "死亡治疗缺少致死技能")

    def test_13_x_comparison_summary_has_metrics(self):
        """X13: x_comparison 汇总含平均密度和总施法"""
        comparison_path = self.output_dir / "x_comparison.json"
        if not comparison_path.exists():
            self.skipTest("x_comparison.json 未生成")
        comp = json.loads(comparison_path.read_text())

        summary = comp.get("summary", {})
        self.assertIn("learner_total_casts", summary)
        self.assertIn("benchmark_total_casts", summary)
        self.assertIn("learner_avg_density", summary)
        self.assertGreater(summary["learner_total_casts"], 0)
        self.assertGreater(summary["benchmark_total_casts"], 0)



@unittest.skipUnless(os.environ.get("WCL_API_KEY"), "需 WCL_API_KEY（联网集成测试）")
class TestModeT(unittest.TestCase):
    """T 系列教练分析 — t mode 验收测试"""

    @classmethod
    def setUpClass(cls):
        cls.code = TEST_META["t_mode"]["report_code"]
        cls.fight_id = TEST_META["t_mode"]["fight_id"]
        cls.bm_char = TEST_META["t_mode"]["benchmark_char"]
        cls.bm_report = TEST_META["t_mode"]["benchmark_report"]
        cls.bm_fight = TEST_META["t_mode"]["benchmark_fight"]
        cls.output_dir = Path(tempfile.mkdtemp(prefix="mplus_test_t_"))

        from core import mplus_pipeline
        args = mplus_pipeline.parse_args([
            "t", "--report-code", cls.code,
            "--fight-id", str(cls.fight_id),
            "--output-dir", str(cls.output_dir),
            "--benchmark-char", cls.bm_char,
            "--benchmark-report", cls.bm_report,
            "--benchmark-fight", str(cls.bm_fight),
        ])
        mplus_pipeline.run_t_mode(args)
        cls.manifest_path = cls.output_dir / "manifest.json"
        cls.manifest = json.loads(cls.manifest_path.read_text()) if cls.manifest_path.exists() else {}

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.output_dir, ignore_errors=True)

    def test_01_manifest_exists(self):
        """T1: manifest.json 必须存在"""
        self.assertTrue(self.manifest_path.exists(), "manifest.json 不存在 (t mode)")

    def test_02_mode_is_t(self):
        """T2: manifest.mode == t"""
        self.assertEqual(self.manifest.get("mode"), "t")

    def test_03_manifest_has_learner_info(self):
        """T3: manifest 记录学习者信息"""
        learner = self.manifest.get("learner")
        self.assertIsNotNone(learner, "manifest 缺少 learner 字段")

    def test_04_manifest_has_benchmark_info(self):
        """T4: manifest 记录教练基准信息"""
        bm = self.manifest.get("benchmark")
        self.assertIsNotNone(bm, "manifest 缺少 benchmark 字段")
        self.assertIn("report_code", bm)
        self.assertIn("fight_id", bm)

    def test_05_no_critical_errors(self):
        """T5: manifest.errors 应为空"""
        self.assertEqual(len(self.manifest.get("errors", [])), 0,
                         f"manifest 包含 errors: {self.manifest.get('errors')}")

    def test_06_required_output_files(self):
        """T6: t mode 必须产出骨架和 group 文件"""
        file_paths = {f["path"] for f in self.manifest.get("files", [])}

        # 骨架文件
        has_skeleton = any("skeleton" in p for p in file_paths)
        self.assertTrue(has_skeleton, "t mode 应产出骨架文件")

        # group 文件
        for suffix in ["group_a", "group_b", "group_c"]:
            has = any(suffix in p for p in file_paths)
            self.assertTrue(has, f"t mode 应产出 m2_{suffix}")

    def test_07_output_files_not_empty(self):
        """T7: 所有产出文件大小 > 0"""
        for f in self.manifest.get("files", []):
            self.assertGreater(f["size"], 0, f"文件 {f['path']} 大小为 0")
            self.assertNotEqual(f["sha256"], "0", f"文件 {f['path']} sha256 未计算")

    def test_08_skeleton_is_healing_oriented(self):
        """T8: 骨架文件应包含治疗向章节（HPS 指标）"""
        skeleton_paths = [
            p for p in self.manifest.get("files", [])
            if "skeleton" in p["path"]
        ]
        if skeleton_paths:
            skel_path = skeleton_paths[0]
            content = (self.output_dir / skel_path["path"]).read_text()
            # 治疗指标标签
            has_hps = "HPS" in content
            self.assertTrue(has_hps, "治疗向骨架应包含 HPS 指标")
            # 孙青云口吻
            has_coach = "孙青云" in content
            self.assertTrue(has_coach, "治疗向骨架应引用孙青云")

    def test_09_benchmark_profile_healing_metrics(self):
        """T9: 教练基准档案应含治疗指标"""
        bm_file = Path(PROJECT_ROOT) / "data" / "taozhi" / "lvlyue_benchmark_profile.json"
        if bm_file.exists():
            bm = json.loads(bm_file.read_text())
            self.assertIn("source_report", bm, "基准档案缺少 source_report")
            self.assertIn("skill_composition", bm, "基准档案缺少 skill_composition")
            self.assertGreater(len(bm["skill_composition"]), 0, "基准档案技能表为空")


class TestCLI(unittest.TestCase):
    """CLI 参数解析测试（不依赖 API）"""

    def test_01_m_mode_requires_fight_id(self):
        """C1: m mode 缺少 --fight-id 应报错"""
        from core.mplus_pipeline import parse_args
        with self.assertRaises(SystemExit):
            parse_args(["m", "--report-code", "ABC"])

    def test_02_requires_report_code(self):
        """C2: 缺少 --report-code 应报错"""
        from core.mplus_pipeline import parse_args
        with self.assertRaises(SystemExit):
            parse_args(["m", "--fight-id", "4"])

    def test_03_invalid_mode_rejected(self):
        """C3: 非法 mode 应报错"""
        from core.mplus_pipeline import parse_args
        with self.assertRaises(SystemExit):
            parse_args(["z", "--report-code", "ABC", "--fight-id", "4"])


class TestManifestFormat(unittest.TestCase):
    """manifest.json 格式测试（不依赖 API）"""

    def test_01_manifest_structure(self):
        """MF1: manifest 结构必须符合标准"""
        from core.mplus_pipeline import write_manifest
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            # 创建伪文件
            (out / "test.txt").write_text("hello")

            meta = {"mode": "m", "report_code": "TEST", "errors": [], "warnings": []}
            files = [{"path": "test.txt", "description": "测试文件"}]

            manifest = write_manifest(out, files, meta)
            self.assertIn("pipeline_version", manifest)
            self.assertIn("files", manifest)
            self.assertEqual(len(manifest["files"]), 1)
            self.assertEqual(manifest["files"][0]["path"], "test.txt")
            self.assertGreater(manifest["files"][0]["size"], 0)

    def test_02_error_and_warning_fields(self):
        """MF2: manifest 必须记录 errors 和 warnings"""
        from core.mplus_pipeline import write_manifest
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "test.txt").write_text("data")

            meta = {
                "mode": "x", "report_code": "TEST",
                "errors": ["API超时"],
                "warnings": ["fetch_top_benchmarks跳过"],
            }
            manifest = write_manifest(out, [{"path": "test.txt", "description": ""}], meta)
            self.assertEqual(len(manifest["errors"]), 1)
            self.assertEqual(len(manifest["warnings"]), 1)


if __name__ == "__main__":
    unittest.main()
