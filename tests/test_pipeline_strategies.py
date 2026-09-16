#!/usr/bin/env python3
"""P3 管线策略单元测试 — 使用 MockProfile，不调用 WCL API"""

import unittest
from pathlib import Path
from unittest.mock import patch

from core.pipeline_strategies import (
    CoachingStrategy,
    ROLE_CONFIGS,
    dispatch_strategy,
)
from core.profile_loader import Profile


def _make_profile(
    profile_id: str = "test",
    role: str = "dps",
    spec: str = "冰法",
    **overrides,
) -> Profile:
    """创建最小化 Profile，仅设置必要字段。"""
    base = Profile(
        id=profile_id,
        name=f"{profile_id}_name",
        role=role,
        spec=spec,
        function="coaching",
        comparison="benchmark",
        benchmark_char="bench_player",
        benchmark_report="bench_code",
        benchmark_fight=1,
        wiki_prefix="test_prefix",
    )
    for k, v in overrides.items():
        if hasattr(base, k):
            setattr(base, k, v)
    return base


class TestDispatchStrategy(unittest.TestCase):
    """dispatch_strategy 分派逻辑测试"""

    def test_dispatch_coaching_dps(self):
        """role=dps → CoachingStrategy, role_config 匹配 dps"""
        profile = _make_profile(role="dps", spec="冰法")
        strategy = dispatch_strategy(profile, "ABC123", 5)
        self.assertIsInstance(strategy, CoachingStrategy)
        self.assertDictEqual(strategy.role_config, ROLE_CONFIGS["dps"])

        # role_config fields specific to dps
        self.assertEqual(strategy.role_config["death_depth"], "normal")
        self.assertIsNone(strategy.role_config["extra_events_source"])
        self.assertEqual(
            strategy.role_config["overview_rows"],
            ["总伤害", "DPS"],
        )

    def test_dispatch_healer_coaching(self):
        """role=healer → CoachingStrategy, role_config 匹配 healer"""
        profile = _make_profile(role="healer", spec="织雾")
        strategy = dispatch_strategy(profile, "DEF456", 3)
        self.assertIsInstance(strategy, CoachingStrategy)
        self.assertDictEqual(strategy.role_config, ROLE_CONFIGS["healer"])

        # role_config fields specific to healers
        self.assertEqual(strategy.role_config["death_depth"], "normal")
        self.assertEqual(strategy.role_config["extra_events_source"], "healing")
        overview = strategy.role_config["overview_rows"]
        self.assertIn("总治疗", overview)
        self.assertIn("HPS", overview)
        self.assertIn("过量%", overview)

    def test_dispatch_tank_coaching(self):
        """role=tank → CoachingStrategy, role_config 匹配 tank"""
        profile = _make_profile(role="tank", spec="酒仙")
        strategy = dispatch_strategy(profile, "GHI789", 1)
        self.assertIsInstance(strategy, CoachingStrategy)
        self.assertDictEqual(strategy.role_config, ROLE_CONFIGS["tank"])

        # role_config fields specific to tanks
        self.assertEqual(strategy.role_config["death_depth"], "full")
        self.assertIsNone(strategy.role_config["extra_events_source"])
        overview = strategy.role_config["overview_rows"]
        self.assertIn("DTPS", overview)
        self.assertIn("自疗HPS", overview)


class TestCoachingStrategyStructure(unittest.TestCase):
    """CoachingStrategy 结构完整性测试"""

    def test_strategy_has_run_method(self):
        """run() 方法存在并返回 Path"""
        profile = _make_profile()
        strategy = CoachingStrategy(profile, "CODE", 1)
        self.assertTrue(hasattr(strategy, "run"))
        self.assertTrue(callable(strategy.run))

    def test_strategy_has_all_phases(self):
        """所有 Phase 0–5 方法存在"""
        profile = _make_profile()
        strategy = CoachingStrategy(profile, "CODE", 1)

        phase_methods = [
            "phase0_knowledge_gate",
            "phase1_wcl_gate",
            "phase2_fetch_data",
            "phase3_aggregate",
            "phase4_events_pipeline",
            "phase5_skeleton_and_report",
        ]
        for method_name in phase_methods:
            with self.subTest(phase=method_name):
                self.assertTrue(
                    hasattr(strategy, method_name),
                    f"缺少方法: {method_name}",
                )
                self.assertTrue(
                    callable(getattr(strategy, method_name)),
                    f"{method_name} 不可调用",
                )

    def test_strategy_has_write_manifest(self):
        """write_manifest 方法存在"""
        profile = _make_profile()
        strategy = CoachingStrategy(profile, "CODE", 1)
        self.assertTrue(hasattr(strategy, "write_manifest"))
        self.assertTrue(callable(strategy.write_manifest))


class TestRoleConfigs(unittest.TestCase):
    """ROLE_CONFIGS 结构与覆盖测试"""

    def test_role_configs_cover_all_profiles(self):
        """ROLE_CONFIGS 包含全部 3 个角色"""
        self.assertIn("dps", ROLE_CONFIGS)
        self.assertIn("healer", ROLE_CONFIGS)
        self.assertIn("tank", ROLE_CONFIGS)
        self.assertEqual(len(ROLE_CONFIGS), 3)

    def test_extra_events_source_logic(self):
        """healer 有 extra_events_source, dps/tank 为 None"""
        self.assertIsNone(ROLE_CONFIGS["dps"]["extra_events_source"])
        self.assertIsNone(ROLE_CONFIGS["tank"]["extra_events_source"])
        self.assertEqual(
            ROLE_CONFIGS["healer"]["extra_events_source"], "healing"
        )

    def test_death_depth_logic(self):
        """tank death_depth=full, dps/healer=normal"""
        self.assertEqual(ROLE_CONFIGS["tank"]["death_depth"], "full")
        self.assertEqual(ROLE_CONFIGS["dps"]["death_depth"], "normal")
        self.assertEqual(ROLE_CONFIGS["healer"]["death_depth"], "normal")

    def test_role_config_override_extensibility(self):
        """可增加新 key 不破坏已有逻辑"""
        # 验证所有角色配置有统一的 key 集
        required_keys = {
            "overview_rows", "cast_whitelist", "death_depth",
            "extra_events_source",
        }
        for role, config in ROLE_CONFIGS.items():
            with self.subTest(role=role):
                config_keys = set(config.keys())
                self.assertTrue(
                    required_keys.issubset(config_keys),
                    f"{role} 缺少 key: {required_keys - config_keys}",
                )

        # 验证可扩展性：在副本上添加新 key 不应影响原配置
        original = ROLE_CONFIGS["dps"].copy()
        extended = {**original, "new_feature": True, "custom_value": 42}
        self.assertNotIn("new_feature", ROLE_CONFIGS["dps"])
        self.assertEqual(ROLE_CONFIGS["dps"], original)

        # 验证 dispatch 使用原版配置（而非被污染）
        profile = _make_profile(role="dps")
        strategy = dispatch_strategy(profile, "CODE", 1)
        self.assertNotIn("new_feature", strategy.role_config)
        self.assertNotIn("custom_value", strategy.role_config)


class TestCoachingStrategyInit(unittest.TestCase):
    """CoachingStrategy 初始化参数测试"""

    def test_benchmark_fallback_from_profile(self):
        """benchmark_report/fight 从 profile 回退"""
        profile = _make_profile(
            benchmark_report="from_profile_code",
            benchmark_fight=42,
        )
        strategy = CoachingStrategy(profile, "CODE", 1)
        self.assertEqual(strategy.benchmark_report, "from_profile_code")
        self.assertEqual(strategy.benchmark_fight, 42)

    def test_benchmark_override(self):
        """benchmark_report/fight 覆盖 profile"""
        profile = _make_profile(
            benchmark_report="from_profile",
            benchmark_fight=10,
        )
        strategy = CoachingStrategy(
            profile, "CODE", 1,
            benchmark_report="override_report",
            benchmark_fight=99,
        )
        self.assertEqual(strategy.benchmark_report, "override_report")
        self.assertEqual(strategy.benchmark_fight, 99)

    def test_output_dir_default(self):
        """output_dir 默认值为 data/reports/{profile.id}_{code}"""
        profile = _make_profile(profile_id="test_user")
        strategy = CoachingStrategy(profile, "CODE123", 1)
        expected = Path("data/reports/test_user_CODE123")
        self.assertEqual(strategy.output_dir, expected)

    def test_output_dir_custom(self):
        """output_dir 可自定义"""
        profile = _make_profile()
        custom = Path("/tmp/test_output")
        strategy = CoachingStrategy(profile, "CODE", 1, output_dir=custom)
        self.assertEqual(strategy.output_dir, custom)

    def test_extra_kwargs(self):
        """额外 kwargs 写入实例"""
        profile = _make_profile()
        strategy = CoachingStrategy(
            profile, "CODE", 1,
            custom_param="hello",
            verbose=True,
            max_retries=3,
        )
        self.assertEqual(strategy.custom_param, "hello")
        self.assertTrue(strategy.verbose)
        self.assertEqual(strategy.max_retries, 3)


class TestPhaseKnowledgeGate(unittest.TestCase):
    """phase0_knowledge_gate 在不同条件下的行为"""

    def test_empty_wiki_prefix(self):
        """wiki_prefix 为空时输出 warning，不抛异常"""
        profile = _make_profile(wiki_prefix="")
        strategy = CoachingStrategy(profile, "CODE", 1)
        strategy.phase0_knowledge_gate()
        self.assertGreaterEqual(len(strategy.warnings), 1)
        self.assertTrue(
            any("wiki_prefix" in w for w in strategy.warnings)
        )

    def test_no_knowledge_base_dir(self):
        """知识卡片目录不存在时输出 warning"""
        profile = _make_profile(wiki_prefix="nonexistent")
        strategy = CoachingStrategy(profile, "CODE", 1)
        strategy.phase0_knowledge_gate()
        self.assertGreaterEqual(len(strategy.warnings), 1)

    def test_knowledge_gate_no_error_on_missing(self):
        """知识卡片校验失败不产生 errors"""
        profile = _make_profile(wiki_prefix="no_such_prefix")
        strategy = CoachingStrategy(profile, "CODE", 1)
        strategy.phase0_knowledge_gate()
        # should only generate warnings, never errors
        self.assertEqual(len(strategy.errors), 0)


class TestRunMethod(unittest.TestCase):
    """run() 模板方法行为（不实际调用外部 API）"""

    def setUp(self):
        # 用 dummy key 让流程走到网络层再优雅失败；patch 不污染进程 env，
        # 避免影响 test_regression 等模块的 skipUnless(WCL_API_KEY) 判断。
        self._key_patch = patch(
            "core.pipeline_strategies._get_api_key", return_value="test-dummy-key"
        )
        self._key_patch.start()

    def tearDown(self):
        self._key_patch.stop()

    def test_run_returns_path(self):
        """run() 返回 Path"""
        profile = _make_profile(wiki_prefix="")
        strategy = CoachingStrategy(profile, "CODE", 1)
        # Phase 1 will fail silently (no actual API), so errors won't stop flow
        result = strategy.run()
        self.assertIsInstance(result, Path)
        self.assertEqual(result, strategy.output_dir)

    def test_run_collects_errors_and_warnings(self):
        """run() 过程中累积 errors/warnings"""
        profile = _make_profile(wiki_prefix="")
        strategy = CoachingStrategy(profile, "NO_SUCH_CODE", 999)
        strategy.run()
        # At minimum phase0 may generate warnings (empty wiki prefix handled),
        # and run always returns a Path even if phases fail
        self.assertIsInstance(strategy.errors, list)
        self.assertIsInstance(strategy.warnings, list)

    def test_run_writes_manifest(self):
        """run() 后 manifest.json 写入 output_dir"""
        profile = _make_profile(wiki_prefix="")
        strategy = CoachingStrategy(profile, "CODE", 1)
        strategy.run()
        manifest_path = strategy.output_dir / "manifest.json"
        self.assertTrue(manifest_path.exists())
        import json
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["profile_id"], "test")
        self.assertEqual(manifest["report_code"], "CODE")
        self.assertEqual(manifest["fight_id"], 1)
        self.assertEqual(manifest["role"], "dps")
        self.assertIn("execution_time_sec", manifest)
        # Clean up
        import shutil
        if strategy.output_dir.exists():
            shutil.rmtree(strategy.output_dir, ignore_errors=True)


class TestGetEventsMode(unittest.TestCase):
    """_get_events_mode 根据 role 返回正确 mode"""

    def test_dps_mode_x(self):
        profile = _make_profile(role="dps")
        strategy = CoachingStrategy(profile, "CODE", 1)
        self.assertEqual(strategy._get_events_mode(), "x")

    def test_healer_mode_t(self):
        profile = _make_profile(role="healer")
        strategy = CoachingStrategy(profile, "CODE", 1)
        self.assertEqual(strategy._get_events_mode(), "t")

    def test_tank_mode_b(self):
        profile = _make_profile(role="tank")
        strategy = CoachingStrategy(profile, "CODE", 1)
        self.assertEqual(strategy._get_events_mode(), "b")


if __name__ == "__main__":
    unittest.main()
