"""SQLite DDL — 7 张表"""

TABLES = {}

TABLES['report'] = '''
CREATE TABLE IF NOT EXISTS report (
    report_code TEXT PRIMARY KEY,
    title TEXT DEFAULT '',
    start_time INTEGER DEFAULT 0,
    end_time INTEGER DEFAULT 0,
    zone TEXT DEFAULT '',
    owner TEXT DEFAULT '',
    keystone_timed INTEGER DEFAULT 0,
    dungeon_name TEXT DEFAULT '',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)
'''

TABLES['fight'] = '''
CREATE TABLE IF NOT EXISTS fight (
    report_code TEXT NOT NULL,
    fight_id INTEGER NOT NULL,
    name TEXT DEFAULT '',
    kill INTEGER DEFAULT 0,
    difficulty TEXT DEFAULT '',
    start_time INTEGER DEFAULT 0,
    end_time INTEGER DEFAULT 0,
    percentage REAL DEFAULT 0.0,
    keystone_level INTEGER DEFAULT 0,
    keystone_time INTEGER DEFAULT 0,
    PRIMARY KEY (report_code, fight_id),
    FOREIGN KEY (report_code) REFERENCES report(report_code)
)
'''

TABLES['player'] = '''
CREATE TABLE IF NOT EXISTS player (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_code TEXT NOT NULL,
    fight_id INTEGER NOT NULL,
    name TEXT DEFAULT '',
    class TEXT DEFAULT '',
    spec TEXT DEFAULT '',
    hero_talent TEXT DEFAULT '',
    ilvl INTEGER DEFAULT 0,
    server TEXT DEFAULT '',
    damage_total REAL DEFAULT 0.0,
    heal_total REAL DEFAULT 0.0,
    parse_pct REAL DEFAULT 0.0,
    dps REAL DEFAULT 0.0,
    potion_use INTEGER DEFAULT 0,
    healthstone_use INTEGER DEFAULT 0,
    FOREIGN KEY (report_code, fight_id) REFERENCES fight(report_code, fight_id)
)
'''

TABLES['ability'] = '''
CREATE TABLE IF NOT EXISTS ability (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL,
    name TEXT DEFAULT '',
    spell_id INTEGER DEFAULT 0,
    amount REAL DEFAULT 0.0,
    hits INTEGER DEFAULT 0,
    crits INTEGER DEFAULT 0,
    miss_pct REAL DEFAULT 0.0,
    FOREIGN KEY (player_id) REFERENCES player(id)
)
'''

TABLES['aura'] = '''
CREATE TABLE IF NOT EXISTS aura (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL,
    name TEXT DEFAULT '',
    spell_id INTEGER DEFAULT 0,
    uptime_pct REAL DEFAULT 0.0,
    FOREIGN KEY (player_id) REFERENCES player(id)
)
'''

TABLES['event'] = '''
CREATE TABLE IF NOT EXISTS event (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_code TEXT NOT NULL,
    fight_id INTEGER NOT NULL,
    timestamp INTEGER DEFAULT 0,
    type TEXT DEFAULT '',
    source TEXT DEFAULT '',
    target TEXT DEFAULT '',
    ability_name TEXT DEFAULT '',
    ability_id INTEGER DEFAULT 0,
    amount REAL DEFAULT 0.0,
    hit_type TEXT DEFAULT '',
    absorbed REAL DEFAULT 0.0,
    resisted REAL DEFAULT 0.0,
    FOREIGN KEY (report_code, fight_id) REFERENCES fight(report_code, fight_id)
)
'''

TABLES['npc'] = '''
CREATE TABLE IF NOT EXISTS npc (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_code TEXT NOT NULL,
    fight_id INTEGER NOT NULL,
    name TEXT DEFAULT '',
    npc_id INTEGER DEFAULT 0,
    type TEXT DEFAULT 'add',
    damage_taken REAL DEFAULT 0.0,
    death_time INTEGER DEFAULT 0,
    FOREIGN KEY (report_code, fight_id) REFERENCES fight(report_code, fight_id)
)
'''

TABLES['player_stats'] = '''
CREATE TABLE IF NOT EXISTS player_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL UNIQUE,
    strength REAL DEFAULT 0.0,
    agility REAL DEFAULT 0.0,
    intellect REAL DEFAULT 0.0,
    stamina REAL DEFAULT 0.0,
    crit REAL DEFAULT 0.0,
    haste REAL DEFAULT 0.0,
    mastery REAL DEFAULT 0.0,
    versatility REAL DEFAULT 0.0,
    leech REAL DEFAULT 0.0,
    FOREIGN KEY (player_id) REFERENCES player(id)
)
'''

TABLES['player_gear'] = '''
CREATE TABLE IF NOT EXISTS player_gear (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL,
    slot INTEGER DEFAULT 0,
    item_name TEXT DEFAULT '',
    item_level INTEGER DEFAULT 0,
    quality INTEGER DEFAULT 1,
    set_id INTEGER DEFAULT 0,
    set_name TEXT DEFAULT '',
    perm_enchant_id INTEGER DEFAULT 0,
    perm_enchant_name TEXT DEFAULT '',
    temp_enchant_id INTEGER DEFAULT 0,
    temp_enchant_name TEXT DEFAULT '',
    gems TEXT DEFAULT '[]',
    FOREIGN KEY (player_id) REFERENCES player(id)
)
'''

# 索引
INDEXES = [
    'CREATE INDEX IF NOT EXISTS idx_event_time ON event(report_code, fight_id, timestamp)',
    'CREATE INDEX IF NOT EXISTS idx_player_fight ON player(report_code, fight_id)',
    'CREATE INDEX IF NOT EXISTS idx_ability_player ON ability(player_id)',
    'CREATE INDEX IF NOT EXISTS idx_aura_player ON aura(player_id)',
]


if __name__ == '__main__':
    assert len(TABLES) == 9, f"预期 9 张表，实际 {len(TABLES)}"
    for name, ddl in TABLES.items():
        assert 'CREATE TABLE' in ddl, f"{name} 缺少 CREATE TABLE"
        assert name in ddl.lower(), f"{name} 表名不在 DDL 中"
    print(f"Schema 定义完毕，{len(TABLES)} 张表 + {len(INDEXES)} 个索引")
