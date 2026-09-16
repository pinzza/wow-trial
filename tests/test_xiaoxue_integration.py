"""Integration tests: tracker + report_builder end-to-end."""
import json
import sqlite3
from pathlib import Path

import pytest

from core.xiaoxue_tracker import (
    init_db, write_snapshot, get_latest, add_task, update_task_status,
    check_milestones, get_weekly_diff, get_best_ever, ascii_trend_chart,
    get_task_completion,
)


class TestEndToEnd:
    """模拟完整流程: 初始评估 → 周报 → 任务追踪。"""

    def test_full_flow(self, temp_dir):
        db_path = temp_dir / "test_progress.db"
        init_db(db_path)

        # Week 1: 初始评估
        write_snapshot(db_path, {
            "date": "2026-05-01", "report_code": "wk1CODE",
            "dungeon": "风行者之塔", "level": 5, "timed": 1,
            "dps": 70000, "vs_benchmark_pct": 55.0,
            "deaths": 3, "interrupts": 4, "duration_sec": 1800.0,
            "ability_pcts": {"冰枪术": {"pct": 22.0, "hits": 65}},
        })

        # Week 2: 第二周
        write_snapshot(db_path, {
            "date": "2026-05-08", "report_code": "wk2CODE",
            "dungeon": "风行者之塔", "level": 7, "timed": 1,
            "dps": 82000, "vs_benchmark_pct": 65.0,
            "deaths": 2, "interrupts": 7, "duration_sec": 1750.0,
            "ability_pcts": {"冰枪术": {"pct": 25.0, "hits": 78}},
        })

        # Week 3: 第三周
        write_snapshot(db_path, {
            "date": "2026-05-15", "report_code": "wk3CODE",
            "dungeon": "风行者之塔", "level": 10, "timed": 1,
            "dps": 95000, "vs_benchmark_pct": 72.0,
            "deaths": 1, "interrupts": 8, "duration_sec": 1600.0,
            "ability_pcts": {"冰枪术": {"pct": 28.0, "hits": 90}},
        })

        # 验证查询
        latest = get_latest(db_path, count=3)
        assert len(latest) == 3
        assert latest[0]["dps"] == 95000

        # 环比
        diff = get_weekly_diff(db_path)
        assert diff["dps_change"] == 13000
        assert diff["deaths_change"] == -1

        # 里程碑
        ms = check_milestones(latest[0])
        assert ms["蓝分入门"] is True

        # 最佳
        best = get_best_ever(db_path, metric="dps")
        assert best["value"] == 95000

        # 趋势图
        chart = ascii_trend_chart(db_path, metric="dps", count=3)
        assert "趋势" in chart

        # 任务追踪
        task_id = add_task(db_path, {
            "date_created": "2026-05-08",
            "content": "提高冰枪术 hits 到 100",
            "category": "rotation",
            "target_value": json.dumps({
                "metric": "ability_pcts.冰枪术.hits", "to": 100
            }),
        })

        # 写入一个新快照让 update_task_status 有数据判断
        write_snapshot(db_path, {
            "date": "2026-05-22", "report_code": "wk4CODE",
            "dungeon": "风行者之塔", "level": 12, "timed": 1,
            "dps": 98000, "vs_benchmark_pct": 74.0,
            "deaths": 0, "interrupts": 10, "duration_sec": 1550.0,
            "ability_pcts": {"冰枪术": {"pct": 30.0, "hits": 95}},
        })

        new_status = update_task_status(db_path, task_id)
        # 95 < 100, 但 95 > 78 → 改善中
        assert new_status == "改善中"

        # 任务统计
        stats = get_task_completion(db_path)
        assert "改善中" in stats
        assert stats["改善中"] >= 1

    def test_no_data(self, temp_dir):
        """空数据库不报错。"""
        chart = ascii_trend_chart(temp_dir / "empty.db", count=6)
        assert "数据不足" in chart

        best = get_best_ever(temp_dir / "empty.db")
        assert best == {}

        diff = get_weekly_diff(temp_dir / "empty.db")
        assert diff == {}
