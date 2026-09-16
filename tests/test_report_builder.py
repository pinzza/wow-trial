#!/usr/bin/env python3
"""P4 ReportBuilder 单元测试"""

import tempfile
import unittest
from pathlib import Path

from core.profile_loader import Profile
from core.report_builder import ReportBuilder


def _make_profile(role: str = "dps", **overrides) -> Profile:
    """创建测试用 Profile"""
    p = Profile(
        id="test",
        name="测试玩家",
        server="测试服",
        display_name="测试",
        role=role,
        spec="冰法",
        function="coaching",
        comparison="benchmark",
        benchmark_char="对标选手",
        benchmark_report="TEST",
        benchmark_fight=1,
        wiki_prefix="test",
    )
    for k, v in overrides.items():
        if hasattr(p, k):
            setattr(p, k, v)
    return p


class TestReportBuilder(unittest.TestCase):
    """ReportBuilder 功能测试"""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())

    def test_build_header_contains_profile_name(self):
        """标题包含 profile.name"""
        profile = _make_profile()
        builder = ReportBuilder(profile, self.temp_dir)
        header = builder.build_header({"report_code": "TEST", "fight_id": 1})
        self.assertIn("测试", header)
        self.assertIn("DPS", header.upper())

    def test_build_header_uses_display_name(self):
        """标题使用 display_name"""
        profile = _make_profile(display_name="测试玩家昵称")
        builder = ReportBuilder(profile, self.temp_dir)
        header = builder.build_header({})
        self.assertIn("测试玩家昵称", header)

    def test_build_overview_dps_rows(self):
        """DPS 总览表含 DPS 行，不含 HPS/DTPS"""
        profile = _make_profile(role="dps")
        builder = ReportBuilder(profile, self.temp_dir)
        table = builder.build_overview_table({"DPS": "150k", "总伤害": "100M"}, {"DPS": "180k", "总伤害": "120M"})
        self.assertIn("DPS", table)
        self.assertIn("总伤害", table)
        self.assertNotIn("HPS", table)
        self.assertNotIn("DTPS", table)

    def test_build_overview_healer_rows(self):
        """治疗总览表含 HPS 行"""
        profile = _make_profile(role="healer")
        builder = ReportBuilder(profile, self.temp_dir)
        table = builder.build_overview_table({"HPS": "80k", "总治疗": "50M", "过量%": "20%"}, {"HPS": "100k", "总治疗": "60M", "过量%": "15%"})
        self.assertIn("HPS", table)
        self.assertIn("总治疗", table)
        self.assertIn("过量%", table)

    def test_build_overview_tank_rows(self):
        """坦克总览表含 DTPS + 自疗HPS"""
        profile = _make_profile(role="tank")
        builder = ReportBuilder(profile, self.temp_dir)
        table = builder.build_overview_table(
            {"DPS": "80k", "DTPS": "30k", "自疗HPS": "15k", "死亡次数": "2", "总伤害": "50M"},
            {"DPS": "90k", "DTPS": "25k", "自疗HPS": "20k", "死亡次数": "0", "总伤害": "60M"},
        )
        self.assertIn("DTPS", table)
        self.assertIn("自疗HPS", table)
        self.assertIn("死亡次数", table)

    def test_skill_assessment_has_correct_structure(self):
        """技能评估表结构完整"""
        profile = _make_profile()
        builder = ReportBuilder(profile, self.temp_dir)
        skill_data = {
            "skills": {
                "寒冰箭": {"learner_count": 100, "benchmark_count": 120, "gap": "-20", "rating": "🟡", "analysis": "次数偏低"},
                "冰枪术": {"learner_count": 50, "benchmark_count": 55, "gap": "-5", "rating": "🟢", "analysis": "差距不大"},
            }
        }
        table = builder.build_skill_assessment(skill_data)
        self.assertIn("技能", table)
        self.assertIn("寒冰箭", table)
        self.assertIn("冰枪术", table)
        self.assertIn("🟡", table)
        self.assertIn("🟢", table)

    def test_coach_note_uses_persona_style(self):
        """师傅的话根据 persona_style 切换"""
        profile = _make_profile(persona_style="qingxin", persona_greeting="示例学员")
        builder = ReportBuilder(profile, self.temp_dir)
        note = builder.build_coach_note({"highlights": ["高活跃度"], "issues": []})
        self.assertIn("清心", note)
        self.assertIn("示例学员", note)

    def test_coach_note_default_style(self):
        """默认风格使用 '教练'"""
        profile = _make_profile(persona_style="default")
        builder = ReportBuilder(profile, self.temp_dir)
        note = builder.build_coach_note({"highlights": [], "issues": ["打断不足"]})
        self.assertIn("教练", note)

    def test_report_builder_accepts_profile(self):
        """接收 Profile 对象作为构造参数"""
        profile = _make_profile(role="healer", spec="织雾")
        builder = ReportBuilder(profile, self.temp_dir)
        self.assertEqual(builder.profile.spec, "织雾")
        self.assertEqual(builder.profile.role, "healer")

    def test_build_death_analysis(self):
        """死亡分析方法正常"""
        profile = _make_profile()
        builder = ReportBuilder(profile, self.temp_dir)
        deaths = [
            {"time": 120, "name": "测试玩家", "killing_blow": "虚空顺劈"},
            {"time": 240, "name": "测试玩家", "killing_blow": "过载"},
        ]
        result = builder.build_death_analysis(deaths)
        self.assertIn("2 次死亡", result)
        self.assertIn("虚空顺劈", result)
        self.assertIn("过载", result)

    def test_build_death_analysis_no_deaths(self):
        """零死亡时的分析"""
        profile = _make_profile()
        builder = ReportBuilder(profile, self.temp_dir)
        result = builder.build_death_analysis([])
        self.assertIn("零死亡", result)

    def test_build_death_analysis_tank_full_depth(self):
        """坦克死亡分析含深度分析"""
        profile = _make_profile(role="tank")
        builder = ReportBuilder(profile, self.temp_dir)
        result = builder.build_death_analysis([{"time": 60, "name": "测试", "killing_blow": "过载"}])
        self.assertIn("深度分析", result)

    def test_build_improvement_plan_structure(self):
        """改进计划结构完整"""
        profile = _make_profile()
        builder = ReportBuilder(profile, self.temp_dir)
        plan = builder.build_improvement_plan()
        self.assertIn("改进计划", plan)
        # 6 行结构
        rows = [l for l in plan.split("\n") if l.startswith("|")]
        self.assertGreaterEqual(len(rows), 6)

    def test_build_skeleton_integration(self):
        """build_skeleton 完整流程"""
        profile = _make_profile(role="dps")
        builder = ReportBuilder(profile, self.temp_dir)
        meta = {"report_code": "TEST", "fight_id": 1}
        skill_data = {"skills": {}}
        benchmark_data = {}
        death_data = []
        analysis_data = {"highlights": [], "issues": []}
        skeleton = builder.build_skeleton(meta, skill_data, benchmark_data, death_data, analysis_data)
        self.assertIn("教练报告", skeleton)
        self.assertIn("总览", skeleton)
        self.assertIn("{{DO_WELL_FINAL}}", skeleton)
        self.assertIn("{{IMPROVE_FINAL}}", skeleton)

    def test_build_report_from_profile_function(self):
        """build_report_from_profile 便捷函数"""
        from core.report_builder import build_report_from_profile
        profile = _make_profile()
        result = build_report_from_profile(
            profile=profile,
            output_dir=self.temp_dir,
            meta={},
            skill_data={"skills": {}},
            benchmark_data={},
            death_data=[],
            analysis_data={"highlights": [], "issues": []},
        )
        self.assertIn("教练报告", result)


if __name__ == "__main__":
    unittest.main()
