#!/usr/bin/env python3
"""P2 CLI 正交化单元测试"""

import sys
import tempfile
import unittest
from pathlib import Path

from core.mplus_pipeline import parse_args


class TestCLIOrthogonal(unittest.TestCase):
    """CLI 参数解析测试"""

    def setUp(self):
        # Mock sys.argv for main() calls if needed
        self.old_argv = sys.argv

    def tearDown(self):
        sys.argv = self.old_argv

    def _parse(self, argv: list[str]):
        """辅助：解析参数"""
        return parse_args(argv)

    def test_profile_param_accepted(self):
        """--profile dongrou --report-code TEST --fight-id 1 正常解析"""
        args = self._parse([
            "--profile", "dongrou",
            "--report-code", "TEST",
            "--fight-id", "1",
        ])
        self.assertEqual(args.profile, "dongrou")
        self.assertEqual(args.report_code, "TEST")
        self.assertEqual(args.fight_id, 1)

    def test_profile_with_benchmark_override(self):
        """--profile + --benchmark-report CLI 覆盖"""
        args = self._parse([
            "--profile", "dongrou",
            "--report-code", "TEST",
            "--fight-id", "1",
            "--benchmark-report", "CUSTOM",
            "--benchmark-fight", "99",
        ])
        self.assertEqual(args.profile, "dongrou")
        self.assertEqual(args.benchmark_report, "CUSTOM")
        self.assertEqual(args.benchmark_fight, 99)

    def test_old_mode_still_accepted(self):
        """旧 x 参数仍可解析（兼容期）"""
        args = self._parse(["x", "--report-code", "TEST", "--fight-id", "1"])
        self.assertEqual(args.mode, "x")
        self.assertEqual(args.report_code, "TEST")

    def test_old_mode_t_still_accepted(self):
        """旧 t 参数仍可解析"""
        args = self._parse(["t", "--report-code", "TEST", "--fight-id", "1"])
        self.assertEqual(args.mode, "t")

    def test_old_mode_m_still_accepted(self):
        """旧 m 参数仍可解析"""
        args = self._parse(["m", "--report-code", "TEST", "--fight-id", "1"])
        self.assertEqual(args.mode, "m")

    def test_mode_team_accepted(self):
        """--mode team --report-code TEST --fight-id 1 正常解析"""
        args = self._parse([
            "--mode", "team",
            "--report-code", "TEST",
            "--fight-id", "1",
        ])
        self.assertEqual(args.mode_flag, "team")

    def test_profile_and_team_are_distinct(self):
        """--profile 和 --mode team 是两条互斥路径"""
        args = self._parse([
            "--profile", "dongrou",
            "--mode", "team",
            "--report-code", "TEST",
            "--fight-id", "1",
        ])
        # 两者都可解析，但 main() 会优先处理 --profile
        self.assertEqual(args.profile, "dongrou")
        self.assertEqual(args.mode_flag, "team")

    def test_positional_and_flag_mode_both_accept(self):
        """位置参数 mode=team 和 --mode team 等价"""
        args_old = self._parse(["team", "--report-code", "TEST", "--fight-id", "1"])
        args_new = self._parse(["--mode", "team", "--report-code", "TEST", "--fight-id", "1"])
        self.assertEqual(args_old.mode, "team")
        self.assertEqual(args_new.mode_flag, "team")

    def test_profile_needs_no_positional_mode(self):
        """--profile 不需要位置 mode 参数"""
        args = self._parse([
            "--profile", "dongrou",
            "--report-code", "TEST",
            "--fight-id", "1",
        ])
        self.assertEqual(args.profile, "dongrou")
        # 没传位置参数，mode 应为 None
        self.assertIsNone(args.mode)

    def test_learner_source_default(self):
        """--profile 模式 learner_source 默认 3"""
        args = self._parse([
            "--profile", "dongrou",
            "--report-code", "TEST",
            "--fight-id", "1",
        ])
        self.assertEqual(args.learner_source, 3)

    def test_learner_source_override(self):
        """--profile + --learner-source 覆盖默认值"""
        args = self._parse([
            "--profile", "dongrou",
            "--report-code", "TEST",
            "--fight-id", "1",
            "--learner-source", "1",
        ])
        self.assertEqual(args.learner_source, 1)

    def test_output_dir_default(self):
        """--profile 模式 output_dir 默认 None"""
        args = self._parse([
            "--profile", "dongrou",
            "--report-code", "TEST",
            "--fight-id", "1",
        ])
        self.assertIsNone(args.output_dir)

    def test_output_dir_override(self):
        """--output-dir 可设置"""
        args = self._parse([
            "--profile", "dongrou",
            "--report-code", "TEST",
            "--fight-id", "1",
            "--output-dir", "/tmp/test_out",
        ])
        self.assertEqual(args.output_dir, "/tmp/test_out")


if __name__ == "__main__":
    unittest.main()
