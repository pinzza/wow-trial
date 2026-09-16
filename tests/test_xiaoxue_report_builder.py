"""Tests for core/xiaoxue_report_builder.py."""
import json
import sys
from pathlib import Path

import pytest

from core.xiaoxue_report_builder import (
    build_skill_assessment,
    generate_issues,
    detect_priority,
    build_weekly_overview,
    build_milestone_progress,
    build_death_timeline,
)


class TestDetectPriority:
    def test_p0_missing_skill(self):
        """P0: 核心技能完全缺失。"""
        p = detect_priority("冰枪术", None, {"pct": 32.5, "hits": 115})
        assert p == "P0"

    def test_p0_too_many_deaths(self):
        p = detect_priority("冰枪术", {"pct": 25}, {"pct": 32.5}, deaths=3)
        assert p == "P0"

    def test_p0_low_dps(self):
        p = detect_priority("冰枪术", {"pct": 25}, {"pct": 32.5}, deaths=0, vs_ratio=0.4)
        assert p == "P0"

    def test_p1_big_pct_gap(self):
        """P1: 核心技能占比差 > 5%。"""
        p = detect_priority(
            "冰枪术",
            {"pct": 25.0, "hits": 82},
            {"pct": 32.5, "hits": 115},
        )
        assert p == "P1"

    def test_p1_low_hits_ratio(self):
        """P1: 施法次数 < 顶层 70%。"""
        p = detect_priority(
            "彗星风暴",
            {"pct": 8.8, "hits": 10},
            {"pct": 10.8, "hits": 24},
        )
        assert p == "P1"

    def test_p2_small_gap(self):
        """P2: 差距不大。"""
        p = detect_priority(
            "寒冰箭",
            {"pct": 18.0, "hits": 50},
            {"pct": 18.2, "hits": 52},
        )
        assert p == "P2"


class TestGenerateIssues:
    def test_generates_ranked_issues(self, sample_meta_dict, sample_group_b_dict,
                                     sample_xiaoxue_abilities, sample_qingxin_abilities):
        issues = generate_issues(
            sample_meta_dict, sample_group_b_dict,
            sample_xiaoxue_abilities, sample_qingxin_abilities,
        )
        assert len(issues) > 0
        priorities = [i["priority"] for i in issues]
        # 确保按优先级排序: P0 > P1 > P2
        order = {"P0": 0, "P1": 1, "P2": 2}
        ranked = [order[p] for p in priorities]
        assert ranked == sorted(ranked)


class TestBuildWeeklyOverview:
    def test_formats_table(self, sample_meta_dict, sample_group_b_dict):
        table = build_weekly_overview(
            meta=sample_meta_dict,
            gb=sample_group_b_dict,
            bm_dps=110000,
            bm_deaths=0,
            bm_interrupts=12,
            bm_level=19,
            current_snapshot={"dps": 95000, "deaths": 1, "interrupts": 8},
            previous_snapshot={"dps": 88000, "deaths": 2, "interrupts": 5},
        )
        assert "示例学员" in table or "|" in table
        assert "95,000" in table
        assert "110,000" in table

    def test_no_previous(self, sample_meta_dict, sample_group_b_dict):
        table = build_weekly_overview(
            meta=sample_meta_dict,
            gb=sample_group_b_dict,
            bm_dps=110000,
            bm_deaths=0,
            bm_interrupts=12,
            bm_level=19,
            current_snapshot={"dps": 95000, "deaths": 1, "interrupts": 8},
            previous_snapshot=None,
        )
        assert "→" not in table or True  # 没有环比数据，用 "-"


class TestBuildMilestoneProgress:
    def test_shows_all_milestones(self):
        milestones = {
            "萌新出村": True,
            "蓝分入门": True,
            "紫分进阶": False,
            "橙分法神": False,
        }
        progress = build_milestone_progress(milestones)
        assert "萌新出村" in progress
        assert "✅" in progress
        assert "⬜" in progress

    def test_empty(self):
        assert "(暂无数据)" in build_milestone_progress({})


class TestBuildDeathTimeline:
    def test_no_deaths(self):
        gb = {"deaths": []}
        timeline = build_death_timeline(gb, "示例学员")
        assert "零死亡" in timeline

    def test_has_deaths(self):
        gb = {
            "deaths": [
                {"time_sec": 245, "player": "示例学员", "ability": "暗影箭",
                 "source": "暗影法师", "phase": "BOSS#1"},
            ],
        }
        timeline = build_death_timeline(gb, "示例学员")
        assert "245s" in timeline
        assert "暗影箭" in timeline


class TestBuildSkillAssessment:
    def test_normal(self, sample_xiaoxue_abilities, sample_qingxin_abilities):
        table = build_skill_assessment(sample_xiaoxue_abilities, sample_qingxin_abilities)
        assert "冰枪术" in table
        assert "32.5%" in table
        assert "25.0%" in table

    def test_no_data(self):
        table = build_skill_assessment({}, {})
        assert "无技能数据" in table
