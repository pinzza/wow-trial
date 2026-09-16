"""战斗解析器"""
from wcl_parser.models import Fight


class FightParser:
    @staticmethod
    def parse(fight_dict: dict) -> Fight:
        """从单个战斗的 dict 解析 Fight 对象"""
        return Fight(
            fight_id=fight_dict.get('id', 0),
            name=fight_dict.get('name', ''),
            kill=fight_dict.get('kill', False),
            difficulty='Mythic' if fight_dict.get('difficulty') == 5
                        else str(fight_dict.get('difficulty', '')),
            start_time=fight_dict.get('startTime', 0),
            end_time=fight_dict.get('endTime', 0),
            percentage=fight_dict.get('fightPercentage', 0.0),
        )


if __name__ == '__main__':
    mock = {'id': 3, 'name': '德纳修斯大帝', 'kill': True, 'difficulty': 5,
            'startTime': 1680002000000, 'endTime': 1680005000000,
            'fightPercentage': 0.0}
    f = FightParser.parse(mock)
    assert f.fight_id == 3
    assert f.difficulty == 'Mythic'
    assert f.players == []
    assert f.events == []
    print("FightParser 测试全部通过")
