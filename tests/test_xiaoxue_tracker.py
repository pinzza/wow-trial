"""Tests for core/xiaoxue_tracker.py."""
import json
import sqlite3
from pathlib import Path

import pytest


class TestInitDB:
    """确保 init_db() 正确创建表和目录。"""

    def test_creates_db_file(self, temp_dir):
        from core.xiaoxue_tracker import init_db

        db_path = temp_dir / "test_progress.db"
        init_db(db_path)
        assert db_path.exists()

    def test_creates_snapshots_table(self, temp_dir):
        from core.xiaoxue_tracker import init_db

        db_path = temp_dir / "test_progress.db"
        init_db(db_path)
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='snapshots'"
        )
        assert cursor.fetchone() is not None
        conn.close()

    def test_creates_tasks_table(self, temp_dir):
        from core.xiaoxue_tracker import init_db

        db_path = temp_dir / "test_progress.db"
        init_db(db_path)
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'"
        )
        assert cursor.fetchone() is not None
        conn.close()

    def test_idempotent(self, temp_dir):
        """重复初始化不报错。"""
        from core.xiaoxue_tracker import init_db

        db_path = temp_dir / "test_progress.db"
        init_db(db_path)
        init_db(db_path)


class TestWriteSnapshot:
    def test_writes_and_reads(self, temp_dir):
        from core.xiaoxue_tracker import init_db, write_snapshot

        db_path = temp_dir / "test_progress.db"
        init_db(db_path)
        data = {
            "date": "2026-05-08",
            "report_code": "testCODE",
            "dungeon": "风行者之塔",
            "level": 12,
            "timed": 1,
            "dps": 95000,
            "vs_benchmark_pct": 72.5,
            "deaths": 1,
            "interrupts": 8,
            "duration_sec": 1547.0,
            "ability_pcts": {"冰枪术": {"pct": 28.5, "hits": 82}},
            "ability_casts": {"冰冷血脉": 3},
            "survival_skills": {"闪烁": 28, "冰箱": 1},
        }
        write_snapshot(db_path, data)
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM snapshots").fetchone()
        assert row["dungeon"] == "风行者之塔"
        assert row["dps"] == 95000
        pcts = json.loads(row["ability_pcts"])
        assert pcts["冰枪术"]["pct"] == 28.5
        conn.close()

    def test_ability_pcts_empty_default(self, temp_dir):
        from core.xiaoxue_tracker import init_db, write_snapshot

        db_path = temp_dir / "test_progress.db"
        init_db(db_path)
        write_snapshot(db_path, {
            "date": "2026-05-08",
            "report_code": "test2",
            "dungeon": "test",
            "level": 5,
            "timed": 1,
            "dps": 50000,
            "deaths": 0,
            "interrupts": 0,
            "duration_sec": 1200.0,
        })
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT ability_pcts FROM snapshots").fetchone()
        assert row["ability_pcts"] == "{}"
        conn.close()


class TestGetLatest:
    def test_returns_empty_for_new_db(self, temp_dir):
        from core.xiaoxue_tracker import init_db, get_latest

        db_path = temp_dir / "test_progress.db"
        init_db(db_path)
        results = get_latest(db_path, count=6)
        assert results == []

    def test_returns_ordered(self, temp_dir):
        from core.xiaoxue_tracker import init_db, write_snapshot, get_latest

        db_path = temp_dir / "test_progress.db"
        init_db(db_path)
        for i, date_str in enumerate(["2026-05-01", "2026-05-08", "2026-05-15"]):
            write_snapshot(db_path, {
                "date": date_str,
                "report_code": f"code{i}",
                "dungeon": "test",
                "level": 10 + i,
                "timed": 1,
                "dps": 90000 + i * 5000,
                "deaths": i,
                "interrupts": 5,
                "duration_sec": 1500.0,
            })
        results = get_latest(db_path, count=2)
        assert len(results) == 2
        assert results[0]["date"] == "2026-05-15"

    def test_json_columns_parsed(self, temp_dir):
        """确保 JSON 列被正确反序列化为 dict。"""
        from core.xiaoxue_tracker import init_db, write_snapshot, get_latest

        db_path = temp_dir / "test_progress.db"
        init_db(db_path)
        write_snapshot(db_path, {
            "date": "2026-05-08",
            "report_code": "c1",
            "dungeon": "test",
            "level": 10,
            "timed": 1,
            "dps": 80000,
            "deaths": 0,
            "interrupts": 0,
            "duration_sec": 1500.0,
            "ability_pcts": {"寒冰箭": {"pct": 20, "hits": 50}},
        })
        results = get_latest(db_path, count=1)
        assert isinstance(results[0]["ability_pcts"], dict)
        assert results[0]["ability_pcts"]["寒冰箭"]["pct"] == 20


class TestGetWeeklyDiff:
    def test_returns_diff(self, temp_dir):
        from core.xiaoxue_tracker import init_db, write_snapshot, get_weekly_diff

        db_path = temp_dir / "test_progress.db"
        init_db(db_path)
        write_snapshot(db_path, {
            "date": "2026-05-01", "report_code": "c1", "dungeon": "test",
            "level": 10, "timed": 1, "dps": 80000, "deaths": 2, "interrupts": 5,
            "duration_sec": 1500.0,
        })
        write_snapshot(db_path, {
            "date": "2026-05-08", "report_code": "c2", "dungeon": "test",
            "level": 12, "timed": 1, "dps": 95000, "deaths": 1, "interrupts": 8,
            "duration_sec": 1547.0,
        })
        diff = get_weekly_diff(db_path)
        assert diff["dps_change"] == 15000
        assert diff["deaths_change"] == -1
        assert diff["interrupts_change"] == 3

    def test_insufficient_data(self, temp_dir):
        from core.xiaoxue_tracker import init_db, write_snapshot, get_weekly_diff

        db_path = temp_dir / "test_progress.db"
        init_db(db_path)
        write_snapshot(db_path, {
            "date": "2026-05-01", "report_code": "c1", "dungeon": "test",
            "level": 10, "timed": 1, "dps": 80000, "deaths": 2, "interrupts": 5,
            "duration_sec": 1500.0,
        })
        diff = get_weekly_diff(db_path)
        assert diff == {}


class TestCheckMilestones:
    def test_newbie_achieved(self, temp_dir):
        from core.xiaoxue_tracker import check_milestones

        snap = {"level": 2, "vs_benchmark_pct": 50}
        ms = check_milestones(snap)
        assert ms["萌新出村"] is True
        assert ms["蓝分入门"] is False

    def test_blue_achieved(self, temp_dir):
        from core.xiaoxue_tracker import check_milestones

        snap = {"level": 5, "vs_benchmark_pct": 72}
        ms = check_milestones(snap)
        assert ms["萌新出村"] is True
        assert ms["蓝分入门"] is True
        assert ms["紫分进阶"] is False

    def test_orange_achieved(self, temp_dir):
        from core.xiaoxue_tracker import check_milestones

        snap = {"level": 19, "vs_benchmark_pct": 96}
        ms = check_milestones(snap)
        assert all(ms.values())


class TestGetBestEver:
    def test_finds_max(self, temp_dir):
        from core.xiaoxue_tracker import init_db, write_snapshot, get_best_ever

        db_path = temp_dir / "test_progress.db"
        init_db(db_path)
        for dps in [80000, 95000, 88000]:
            write_snapshot(db_path, {
                "date": "2026-05-01", "report_code": f"c{dps}", "dungeon": "test",
                "level": 10, "timed": 1, "dps": dps, "deaths": 0, "interrupts": 0,
                "duration_sec": 1500.0,
            })
        best = get_best_ever(db_path, metric="dps")
        assert best["value"] == 95000


class TestUpdateTaskStatus:
    def test_waiting_to_improving(self, temp_dir):
        from core.xiaoxue_tracker import (
            init_db, write_snapshot, update_task_status, add_task,
        )

        db_path = temp_dir / "test_progress.db"
        init_db(db_path)
        write_snapshot(db_path, {
            "date": "2026-05-01", "report_code": "c1", "dungeon": "test",
            "level": 10, "timed": 1, "dps": 80000, "deaths": 2, "interrupts": 5,
            "duration_sec": 1500.0,
            "ability_pcts": {"冰枪术": {"pct": 25, "hits": 80}},
            "ability_casts": {"冰冷血脉": 3},
        })
        task_id = add_task(db_path, {
            "date_created": "2026-05-01",
            "content": "提高冰枪术 hits 到 115",
            "category": "rotation",
            "target_value": json.dumps({
                "metric": "ability_pcts.冰枪术.hits", "from": 80, "to": 115
            }),
        })
        write_snapshot(db_path, {
            "date": "2026-05-08", "report_code": "c2", "dungeon": "test",
            "level": 12, "timed": 1, "dps": 90000, "deaths": 1, "interrupts": 5,
            "duration_sec": 1500.0,
            "ability_pcts": {"冰枪术": {"pct": 28, "hits": 95}},
            "ability_casts": {"冰冷血脉": 4},
        })
        new_status = update_task_status(db_path, task_id)
        assert new_status == "改善中"

    def test_improving_to_achieved(self, temp_dir):
        from core.xiaoxue_tracker import (
            init_db, write_snapshot, update_task_status, add_task,
        )

        db_path = temp_dir / "test_progress.db"
        init_db(db_path)
        write_snapshot(db_path, {
            "date": "2026-05-01", "report_code": "c1", "dungeon": "test",
            "level": 10, "timed": 1, "dps": 80000, "deaths": 2, "interrupts": 5,
            "duration_sec": 1500.0,
            "ability_pcts": {"冰枪术": {"pct": 25, "hits": 80}},
        })
        task_id = add_task(db_path, {
            "date_created": "2026-05-01",
            "content": "提高冰枪术 hits 到 115",
            "category": "rotation",
            "target_value": json.dumps({
                "metric": "ability_pcts.冰枪术.hits", "from": 80, "to": 115
            }),
        })
        write_snapshot(db_path, {
            "date": "2026-05-08", "report_code": "c2", "dungeon": "test",
            "level": 12, "timed": 1, "dps": 90000, "deaths": 1, "interrupts": 5,
            "duration_sec": 1500.0,
            "ability_pcts": {"冰枪术": {"pct": 32, "hits": 120}},
        })
        new_status = update_task_status(db_path, task_id)
        assert new_status == "已达成"

    def test_not_improved(self, temp_dir):
        from core.xiaoxue_tracker import (
            init_db, write_snapshot, update_task_status, add_task,
        )

        db_path = temp_dir / "test_progress.db"
        init_db(db_path)
        write_snapshot(db_path, {
            "date": "2026-05-01", "report_code": "c1", "dungeon": "test",
            "level": 10, "timed": 1, "dps": 80000, "deaths": 2, "interrupts": 5,
            "duration_sec": 1500.0,
            "ability_pcts": {"冰枪术": {"pct": 25, "hits": 80}},
        })
        task_id = add_task(db_path, {
            "date_created": "2026-05-01",
            "content": "提高冰枪术 hits 到 115",
            "category": "rotation",
            "target_value": json.dumps({
                "metric": "ability_pcts.冰枪术.hits", "from": 80, "to": 115
            }),
        })
        write_snapshot(db_path, {
            "date": "2026-05-08", "report_code": "c2", "dungeon": "test",
            "level": 12, "timed": 1, "dps": 90000, "deaths": 1, "interrupts": 5,
            "duration_sec": 1500.0,
            "ability_pcts": {"冰枪术": {"pct": 24, "hits": 78}},
        })
        new_status = update_task_status(db_path, task_id)
        assert new_status == "未改善"
