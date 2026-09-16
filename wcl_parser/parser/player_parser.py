"""玩家数据解析器"""
from wcl_parser.models import Player, Ability, Aura


class PlayerParser:
    @staticmethod
    def parse(player_dict: dict) -> Player:
        """从 V2 table 响应的单个 entry 解析 Player 对象"""
        abilities = []
        for ab in player_dict.get('abilities', []) or []:
            abilities.append(Ability(
                name=ab.get('name', ''),
                spell_id=ab.get('guid', 0),
                amount=ab.get('total', 0),
                hits=ab.get('hitCount', 0) + ab.get('tickCount', 0),
                crits=ab.get('critCount', 0),
                miss_pct=ab.get('missPercent', 0.0),
            ))
        auras = []
        for au in player_dict.get('auras', []) or []:
            auras.append(Aura(
                name=au.get('name', ''),
                spell_id=au.get('guid', 0),
                uptime_pct=au.get('uptimePercent', 0.0),
            ))
        return Player(
            name=player_dict.get('name', ''),
            class_=player_dict.get('class', player_dict.get('icon', '')),
            spec=player_dict.get('spec', ''),
            ilvl=player_dict.get('ilvl', player_dict.get('itemLevel', 0)),
            server=player_dict.get('server', ''),
            damage_total=player_dict.get('total', 0),
            heal_total=player_dict.get('healingTotal', 0),
            parse_pct=player_dict.get('percentile', player_dict.get('parsePercent', 0)),
            dps=player_dict.get('amount', player_dict.get('perSecond', 0)),
            abilities=abilities,
            auras=auras,
        )


if __name__ == '__main__':
    mock = {
        'name': '测试法师', 'class': 'Mage', 'spec': 'Fire',
        'itemLevel': 285, 'server': '霜狼',
        'total': 5000000.0, 'percentile': 96.0, 'amount': 12000.0,
        'abilities': [
            {'name': '火球术', 'guid': 133, 'total': 3000000, 'hitCount': 100, 'critCount': 50, 'missPercent': 0.5},
            {'name': '炎爆术', 'guid': 11366, 'total': 2000000, 'hitCount': 20, 'critCount': 12, 'missPercent': 0.0},
        ],
        'auras': [
            {'name': '燃烧', 'guid': 190319, 'uptimePercent': 25.0},
        ],
    }
    p = PlayerParser.parse(mock)
    assert p.name == '测试法师'
    assert p.class_ == 'Mage'
    assert p.spec == 'Fire'
    assert p.ilvl == 285
    assert p.damage_total == 5000000.0
    assert p.parse_pct == 96.0
    assert p.dps == 12000.0
    assert len(p.abilities) == 2
    assert p.abilities[0].name == '火球术'
    assert p.abilities[0].spell_id == 133
    assert p.abilities[0].hits == 100
    assert p.abilities[0].crits == 50
    assert p.abilities[0].miss_pct == 0.5
    assert len(p.auras) == 1
    assert p.auras[0].name == '燃烧'
    assert p.auras[0].uptime_pct == 25.0
    print("PlayerParser 测试全部通过")
