"""SQLite 写入器 — 批量写入 + 跳过检测"""
import sqlite3
import os
from wcl_parser.storage.schema import TABLES, INDEXES
from wcl_parser.models import Report, Fight


class SQLiteWriter:
    def __init__(self, db_dir: str = '/home/code/wow-trial/data/wcl_db'):
        self.db_dir = db_dir
        os.makedirs(db_dir, exist_ok=True)

    def _db_path(self, report_code: str) -> str:
        return os.path.join(self.db_dir, f'{report_code}.db')

    def create_tables(self, db_path: str):
        with sqlite3.connect(db_path) as conn:
            for ddl in TABLES.values():
                conn.execute(ddl)
            for idx_ddl in INDEXES:
                conn.execute(idx_ddl)
            conn.commit()

    def is_parsed(self, report_code: str, fight_id: int = None) -> bool:
        db_path = self._db_path(report_code)
        if not os.path.exists(db_path):
            return False
        with sqlite3.connect(db_path) as conn:
            if fight_id is not None:
                row = conn.execute(
                    'SELECT 1 FROM fight WHERE report_code=? AND fight_id=?',
                    (report_code, fight_id)
                ).fetchone()
                return row is not None
            else:
                row = conn.execute(
                    'SELECT 1 FROM report WHERE report_code=?', (report_code,)
                ).fetchone()
                return row is not None

    def write_report(self, report: Report):
        db_path = self._db_path(report.report_code)
        self.create_tables(db_path)
        with sqlite3.connect(db_path) as conn:
            conn.execute('''INSERT OR REPLACE INTO report
                (report_code, title, start_time, end_time, zone, owner)
                VALUES (?, ?, ?, ?, ?, ?)''',
                (report.report_code, report.title, report.start_time,
                 report.end_time, report.zone, report.owner))
            conn.commit()

    def write_fight_full(self, report_code: str, fight: Fight):
        """一个事务写入: fight + players(+abilities+auras) + events + npcs"""
        db_path = self._db_path(report_code)
        self.create_tables(db_path)
        with sqlite3.connect(db_path) as conn:
            conn.execute('BEGIN')
            try:
                # fight
                conn.execute('''INSERT OR REPLACE INTO fight
                    (report_code, fight_id, name, kill, difficulty, start_time, end_time, percentage)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                    (report_code, fight.fight_id, fight.name, int(fight.kill),
                     fight.difficulty, fight.start_time, fight.end_time, fight.percentage))
                # players + abilities + auras
                for player in fight.players:
                    cur = conn.execute('''INSERT INTO player
                        (report_code, fight_id, name, class, spec, ilvl, server,
                         damage_total, heal_total, parse_pct, dps)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                        (report_code, fight.fight_id, player.name, player.class_,
                         player.spec, player.ilvl, player.server,
                         player.damage_total, player.heal_total,
                         player.parse_pct, player.dps))
                    player_id = cur.lastrowid
                    for ab in player.abilities:
                        conn.execute('''INSERT INTO ability
                            (player_id, name, spell_id, amount, hits, crits, miss_pct)
                            VALUES (?, ?, ?, ?, ?, ?, ?)''',
                            (player_id, ab.name, ab.spell_id, ab.amount,
                             ab.hits, ab.crits, ab.miss_pct))
                    for au in player.auras:
                        conn.execute('''INSERT INTO aura
                            (player_id, name, spell_id, uptime_pct)
                            VALUES (?, ?, ?, ?)''',
                            (player_id, au.name, au.spell_id, au.uptime_pct))
                # events
                for evt in fight.events:
                    conn.execute('''INSERT INTO event
                        (report_code, fight_id, timestamp, type, source, target,
                         ability_name, ability_id, amount, hit_type, absorbed, resisted)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                        (report_code, fight.fight_id, evt.timestamp, evt.type,
                         evt.source, evt.target, evt.ability_name, evt.ability_id,
                         evt.amount, evt.hit_type, evt.absorbed, evt.resisted))
                # npcs
                for npc in fight.npcs:
                    conn.execute('''INSERT OR REPLACE INTO npc
                        (report_code, fight_id, name, npc_id, type, damage_taken, death_time)
                        VALUES (?, ?, ?, ?, ?, ?, ?)''',
                        (report_code, fight.fight_id, npc.name, npc.npc_id,
                         npc.type, npc.damage_taken, npc.death_time))
                conn.commit()
            except Exception:
                conn.rollback()
                raise


if __name__ == '__main__':
    import tempfile
    tmp_dir = tempfile.mkdtemp()
    w = SQLiteWriter(db_dir=tmp_dir)
    # 测试建表
    db_path = os.path.join(tmp_dir, '_test.db')
    w.create_tables(db_path)
    # 测试跳过检测
    assert w.is_parsed('non_existent') is False
    # 清理
    os.remove(db_path)
    os.rmdir(tmp_dir)
    print("SQLiteWriter 测试全部通过")
