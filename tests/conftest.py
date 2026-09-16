"""pytest fixtures for xiaoxue tests."""
import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def temp_dir():
    """临时目录，测试结束自动清理。"""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def sample_meta_dict():
    """模拟 load_meta() 返回值。"""
    return {
        "code": "testCODE123",
        "fight_id": 1,
        "dungeon_cn": "风行者之塔",
        "level": 12,
        "timed": True,
        "duration_sec": 1547,
        "complete_time": "26:30",
        "players": [
            {"name": "示例学员", "class": "Mage", "spec": "Frost", "spec_cn": "冰法", "role": "dps", "ilvl": 275, "dps": 95000},
            {"name": "队友A", "class": "Warrior", "spec": "Protection", "spec_cn": "防战", "role": "tank", "ilvl": 278, "dps": 45000},
            {"name": "队友B", "class": "Shaman", "spec": "Restoration", "spec_cn": "恢复萨", "role": "healer", "ilvl": 276, "dps": 12000},
            {"name": "队友C", "class": "Rogue", "spec": "Assassination", "spec_cn": "奇袭贼", "role": "dps", "ilvl": 277, "dps": 102000},
            {"name": "队友D", "class": "Druid", "spec": "Balance", "spec_cn": "鸟德", "role": "dps", "ilvl": 274, "dps": 98000},
        ],
        "total_damage": 350_000_000,
        "total_healing": 120_000_000,
        "sx_count": 2,
        "sx_source": "示例学员:2次",
    }


@pytest.fixture
def sample_group_b_dict():
    """模拟 load_group_b() 返回值。"""
    return {
        "deaths": [
            {"time_sec": 245, "player": "示例学员", "ability": "暗影箭", "source": "暗影法师", "phase": "BOSS#1"},
            {"time_sec": 890, "player": "队友C", "ability": "碾压", "source": "石像鬼", "phase": "小怪#3"},
        ],
        "death_clusters": [],
        "interrupts": {"示例学员": 8, "队友A": 15, "队友C": 12},
        "fights": [
            {"id": 1, "name": "暗影法师", "type": "boss", "start": "0:00", "duration": "3:15", "kill": True, "percentage": 0},
            {"id": 2, "name": "石像鬼群", "type": "trash", "start": "3:45", "duration": "1:20", "kill": True, "percentage": 0},
            {"id": 3, "name": "风行者", "type": "boss", "start": "5:30", "duration": "4:10", "kill": True, "percentage": 0},
        ],
    }


@pytest.fixture
def sample_qingxin_benchmark():
    """模拟清心基准 JSON。"""
    return {
        "mage": "清心",
        "spec": "冰霜",
        "generated_at": "2026-05-08T12:00:00Z",
        "source_report": {"code": "qxABC123", "dungeon": "风行者之塔", "level": 19},
        "skill_composition": {
            "冰枪术": {"spell_id": 30455, "pct": 32.5, "hits": 115},
            "寒冰箭": {"spell_id": 116, "pct": 18.2, "hits": 52},
            "彗星风暴": {"spell_id": 153595, "pct": 10.8, "hits": 24},
            "冰冷血脉": {"spell_id": 12472, "pct": 0, "hits": 0},
        },
        "cooldown_usage": {
            "冰冷血脉": {"spell_id": 12472, "casts": 5},
            "时间扭曲": {"spell_id": 80353, "casts": 1},
        },
        "survival": {
            "deaths": 0,
            "冰箱使用": {"spell_id": 45438, "casts": 2},
            "闪烁次数": {"spell_id": 1953, "casts": 45},
        },
    }


@pytest.fixture
def sample_xiaoxue_abilities():
    """小雪冰法技能占比数据。"""
    return {
        "冰枪术": {"spell_id": 30455, "pct": 25.0, "hits": 82},
        "寒冰箭": {"spell_id": 116, "pct": 20.0, "hits": 50},
        "彗星风暴": {"spell_id": 153595, "pct": 8.8, "hits": 18},
        "暴风雪": {"spell_id": 190356, "pct": 12.0, "hits": 15},
        "冰锥术": {"spell_id": 120, "pct": 5.0, "hits": 3},
    }


@pytest.fixture
def sample_qingxin_abilities():
    """清心冰法技能占比数据（做对比用）。"""
    return {
        "冰枪术": {"spell_id": 30455, "pct": 32.5, "hits": 115},
        "寒冰箭": {"spell_id": 116, "pct": 18.2, "hits": 52},
        "彗星风暴": {"spell_id": 153595, "pct": 10.8, "hits": 24},
        "暴风雪": {"spell_id": 190356, "pct": 10.5, "hits": 12},
        "冰锥术": {"spell_id": 120, "pct": 3.0, "hits": 2},
    }


@pytest.fixture
def sample_db(temp_dir):
    """创建含 snapshots 和 tasks 表的测试用 SQLite。"""
    db_path = temp_dir / "test_progress.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            report_code TEXT NOT NULL,
            dungeon TEXT NOT NULL,
            level INTEGER NOT NULL,
            timed INTEGER DEFAULT 0,
            dps INTEGER,
            vs_benchmark_pct REAL,
            deaths INTEGER,
            interrupts INTEGER,
            duration_sec REAL,
            ability_pcts TEXT DEFAULT '{}',
            ability_casts TEXT DEFAULT '{}',
            survival_skills TEXT DEFAULT '{}',
            report_path TEXT,
            summary_path TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date_created TEXT NOT NULL,
            date_closed TEXT,
            content TEXT NOT NULL,
            category TEXT,
            target_value TEXT,
            source_week TEXT,
            status TEXT DEFAULT '等待中'
        )
    """)
    conn.commit()
    conn.close()
    return db_path
