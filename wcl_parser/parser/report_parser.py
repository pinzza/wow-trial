"""报告元数据解析器"""
from wcl_parser.models import Report, Fight


class ReportParser:
    @staticmethod
    def parse(api_response: dict) -> Report:
        """从 V2 GraphQL 响应解析 Report 对象"""
        report_data = api_response['reportData']['report']
        fights_raw = report_data.get('fights') or []
        fights = [ReportParser._parse_fight(f) for f in fights_raw]
        return Report(
            report_code=report_data.get('code', ''),
            title=report_data.get('title', ''),
            start_time=report_data.get('startTime', 0),
            end_time=report_data.get('endTime', 0),
            zone=report_data.get('zone', {}).get('name', '') if report_data.get('zone') else '',
            owner=report_data.get('owner', {}).get('name', '') if report_data.get('owner') else '',
            fights=fights,
        )

    @staticmethod
    def _parse_fight(f: dict) -> Fight:
        return Fight(
            fight_id=f.get('id', 0),
            name=f.get('name', ''),
            kill=f.get('kill', False),
            difficulty='Mythic' if f.get('difficulty') == 5 else str(f.get('difficulty', '')),
            start_time=f.get('startTime', 0),
            end_time=f.get('endTime', 0),
            percentage=f.get('fightPercentage', 0.0),
        )


if __name__ == '__main__':
    # 用模拟数据测试
    mock = {
        'reportData': {
            'report': {
                'code': 'qavZzKjfyNhmF7V1',
                'title': '测试团队副本',
                'startTime': 1680000000000,
                'endTime': 1680003600000,
                'zone': {'name': '纳斯利亚堡'},
                'owner': {'name': '测试团长'},
                'fights': [
                    {'id': 1, 'name': '啸翼', 'kill': True, 'difficulty': 5,
                     'startTime': 1680000100000, 'endTime': 1680000300000,
                     'fightPercentage': 0.0},
                    {'id': 2, 'name': '猎手阿尔迪莫', 'kill': False, 'difficulty': 5,
                     'startTime': 1680000500000, 'endTime': 1680001000000,
                     'fightPercentage': 22.5},
                ]
            }
        }
    }
    report = ReportParser.parse(mock)
    assert report.report_code == 'qavZzKjfyNhmF7V1'
    assert report.zone == '纳斯利亚堡'
    assert len(report.fights) == 2
    assert report.fights[0].name == '啸翼'
    assert report.fights[0].kill is True
    assert report.fights[0].difficulty == 'Mythic'
    assert report.fights[1].kill is False
    assert report.fights[1].percentage == 22.5
    print("ReportParser 测试全部通过")
