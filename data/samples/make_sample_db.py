#!/usr/bin/env python3
"""构建合成示例 DB（无真人信息、无需联网）。

用法:
    PYTHONPATH=. python3 data/samples/make_sample_db.py [--out data/samples/sample.db]

产出最小可用的 report/fight/player/ability 四表数据，供
comparison_engine / m2_standalone_summary 本地冒烟使用。
人物与技能均为虚构（示例法师/示例榜样）。
"""

import argparse
import sqlite3
from pathlib import Path

DDL = """
CREATE TABLE IF NOT EXISTS report (report_code TEXT PRIMARY KEY, title TEXT DEFAULT '', zone TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS fight (report_code TEXT NOT NULL, fight_id INTEGER NOT NULL,
  name TEXT DEFAULT '', kill INTEGER DEFAULT 0, start_time INTEGER DEFAULT 0, end_time INTEGER DEFAULT 0,
  keystone_level INTEGER DEFAULT 0, PRIMARY KEY (report_code, fight_id));
CREATE TABLE IF NOT EXISTS player (id INTEGER PRIMARY KEY AUTOINCREMENT, report_code TEXT NOT NULL,
  fight_id INTEGER NOT NULL, name TEXT DEFAULT '', class TEXT DEFAULT '', spec TEXT DEFAULT '',
  ilvl INTEGER DEFAULT 0, damage_total REAL DEFAULT 0.0, heal_total REAL DEFAULT 0.0, dps REAL DEFAULT 0.0);
CREATE TABLE IF NOT EXISTS ability (id INTEGER PRIMARY KEY AUTOINCREMENT, player_id INTEGER NOT NULL,
  name TEXT DEFAULT '', spell_id INTEGER DEFAULT 0, amount REAL DEFAULT 0.0, hits INTEGER DEFAULT 0);
"""


def build(out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    conn = sqlite3.connect(str(out))
    conn.executescript(DDL)
    conn.execute("INSERT INTO report VALUES (?,?,?)", ("SAMPLE01", "示例报告·风行者之塔+10", "Windrunner Spire"))
    conn.execute("INSERT INTO fight VALUES (?,?,?,?,?,?,?)", ("SAMPLE01", 1, "示例BOSS", 1, 0, 600000, 10))
    cur = conn.execute(
        "INSERT INTO player (report_code,fight_id,name,class,spec,ilvl,damage_total,dps) VALUES (?,?,?,?,?,?,?,?)",
        ("SAMPLE01", 1, "示例法师", "Mage", "Frost", 270, 60_000_000, 100_000),
    )
    pid = cur.lastrowid
    conn.executemany(
        "INSERT INTO ability (player_id,name,spell_id,amount,hits) VALUES (?,?,?,?,?)",
        [(pid, "冰枪术", 30455, 20_000_000, 80), (pid, "寒冰箭", 116, 12_000_000, 50)],
    )
    conn.commit()
    conn.close()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/samples/sample.db")
    args = ap.parse_args()
    print(build(Path(args.out)))


if __name__ == "__main__":
    main()
