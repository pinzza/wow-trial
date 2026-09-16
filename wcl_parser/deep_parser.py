"""WCL 深度数据解析器 — 门面入口"""
from wcl_parser.api.v2_client import V2Client
from wcl_parser.parser.report_parser import ReportParser
from wcl_parser.parser.player_parser import PlayerParser
from wcl_parser.parser.event_parser import EventParser
from wcl_parser.storage.writer import SQLiteWriter
from wcl_parser.models import Report, Fight
from wcl_parser.exceptions import WCLAPIError


class DeepParser:
    def __init__(self, client_id: str, client_secret: str,
                 db_dir: str = '/home/code/wow-trial/data/wcl_db'):
        self.client = V2Client(client_id, client_secret)
        self.storage = SQLiteWriter(db_dir)

    async def parse(self, report_code: str, fight_id: int = None) -> Report:
        if self.storage.is_parsed(report_code, fight_id):
            print(f"[跳过] 报告 {report_code} 已解析，直接加载")
            return Report(report_code=report_code)

        # 1. 获取报告元数据
        print(f"[步骤 1/4] 获取报告元数据: {report_code}")
        raw_report = await self.client.query_report(report_code)
        report = ReportParser.parse(raw_report)
        self.storage.write_report(report)

        # 2. 确定战斗列表
        fight_ids = [fight_id] if fight_id else [f.fight_id for f in report.fights]
        print(f"[步骤 2/4] 待解析战斗: {fight_ids}")

        # 3. 逐场解析
        for idx, fid in enumerate(fight_ids, 1):
            if self.storage.is_parsed(report_code, fid):
                print(f"  [跳过] 战斗 {fid} 已解析")
                continue
            print(f"  [步骤 3/4] 解析战斗 {fid} ({idx}/{len(fight_ids)})")

            # 3a. 获取玩家伤害表
            table_raw = await self.client.query_player_table(report_code, [fid])
            players_data = self._extract_table_entries(table_raw)
            players = [PlayerParser.parse(p) for p in players_data]

            # 找到对应的 Fight 对象
            fight = next((f for f in report.fights if f.fight_id == fid), None)
            if fight is None:
                fight = Fight(fight_id=fid)
                report.fights.append(fight)
            else:
                fight.players = players

            # 3b. 获取治疗和承伤表，合并到玩家数据
            for dtype in ['Healing', 'DamageTaken']:
                try:
                    t = await self.client.query_player_table(report_code, [fid], dtype)
                    entries = self._extract_table_entries(t)
                    for entry in entries:
                        name = entry.get('name', '')
                        for p in players:
                            if p.name == name:
                                if dtype == 'Healing':
                                    p.heal_total = entry.get('total', p.heal_total)
                                break
                except WCLAPIError:
                    pass

            # 3c. 分页获取事件
            events = []
            if fight.start_time and fight.end_time:
                start, page = fight.start_time, 0
                max_pages = 50
                while start < fight.end_time and page < max_pages:
                    events_raw = await self.client.query_events(
                        report_code, [fid],
                        start_time=start, end_time=fight.end_time,
                        limit=10000
                    )
                    events_container = events_raw.get('reportData', {}).get('report', {}).get('events', {})
                    events_data = events_container.get('data', []) or []
                    next_page = events_container.get('nextPageTimestamp')
                    if events_data:
                        events.extend(EventParser.parse(events_data))
                    if next_page and next_page > start:
                        start = next_page
                    else:
                        break
                    page += 1
            fight.events = events
            print(f"    玩家: {len(players)}, 事件: {len(events)}")

            # 3d. 写入存储
            self.storage.write_fight_full(report_code, fight)

        print(f"[步骤 4/4] 完成! 报告 {report_code} 全部解析完毕")
        return report

    @staticmethod
    def _extract_table_entries(table_raw: dict) -> list[dict]:
        """从 table GraphQL 响应中提取 entries 列表"""
        table = table_raw.get('reportData', {}).get('report', {}).get('table')
        if table is None:
            return []
        data = table.get('data', table)
        if isinstance(data, dict) and 'entries' in data:
            return data['entries']
        if isinstance(data, list):
            return data
        return []


if __name__ == '__main__':
    # 结构验证 + 模拟集成测试
    import tempfile
    import os
    from wcl_parser.parser.player_parser import PlayerParser
    from wcl_parser.parser.event_parser import EventParser

    tmp_dir = tempfile.mkdtemp()
    parser = DeepParser(
        client_id='dummy',
        client_secret='dummy',
        db_dir=tmp_dir
    )

    # 测试 _extract_table_entries
    mock_table = {
        'reportData': {'report': {'table': {
            'data': {'entries': [{'name': '测试A', 'class': 'Mage', 'total': 1000000}]}
        }}}
    }
    entries = DeepParser._extract_table_entries(mock_table)
    assert len(entries) == 1
    assert entries[0]['name'] == '测试A'

    # 测试列表格式
    mock_list = {'reportData': {'report': {'table': {'data': [{'name': '测试B'}]}}}}
    entries = DeepParser._extract_table_entries(mock_list)
    assert len(entries) == 1

    # 测试空响应
    entries = DeepParser._extract_table_entries({})
    assert entries == []

    # 测试跳过检测 (空数据库)
    assert parser.storage.is_parsed('nonexistent') is False
    assert parser.storage.is_parsed('nonexistent', 1) is False

    # 测试写报告 + 验证跳过
    from wcl_parser.models import Report, Fight, Player, Ability, Event
    report = Report(
        report_code='test123', title='测试报告', zone='测试副本',
        start_time=1680000000000, end_time=1680003600000,
        fights=[Fight(fight_id=1, name='测试BOSS')]
    )
    parser.storage.write_report(report)
    assert parser.storage.is_parsed('test123') is True

    # 测试写完整战斗
    fight = Fight(
        fight_id=1, name='测试BOSS', kill=True, difficulty='Mythic',
        start_time=1680000100000, end_time=1680000300000,
        players=[
            Player(name='玩家A', class_='Mage', damage_total=5000000.0, dps=15000.0,
                   abilities=[Ability(name='火球术', amount=3000000)]),
            Player(name='玩家B', class_='Warrior', damage_total=4000000.0, dps=12000.0),
        ],
        events=[
            Event(timestamp=1680000100000, type='damage', source='玩家A', target='BOSS',
                  ability_name='火球术', amount=15000.0, hit_type='crit'),
        ],
    )
    parser.storage.write_fight_full('test123', fight)
    assert parser.storage.is_parsed('test123', 1) is True

    # 验证数据库内容
    import sqlite3
    db_path = parser.storage._db_path('test123')
    conn = sqlite3.connect(db_path)
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name != 'sqlite_sequence'").fetchall()]
    assert len(tables) == 7, f"预期 7 张表，实际 {len(tables)}"
    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
    print(f"数据库验证: {counts}")
    conn.close()

    # 清理
    import shutil
    shutil.rmtree(tmp_dir)

    print("\nDeepParser 集成测试全部通过")
