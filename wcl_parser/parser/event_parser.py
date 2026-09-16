"""事件流解析器"""
from wcl_parser.models import Event


class EventParser:
    # 事件类型映射
    TYPE_MAP = {
        'damage': 'damage',
        'heal': 'heal',
        'begincast': 'begincast',
        'cast': 'cast',
        'applybuff': 'aura_apply',
        'removebuff': 'aura_remove',
        'applydebuff': 'aura_apply',
        'removedebuff': 'aura_remove',
        'death': 'death',
        'summon': 'summon',
    }

    @staticmethod
    def parse(events_list: list[dict]) -> list[Event]:
        """从 V2 events.data 解析 Event 列表"""
        result = []
        for raw in events_list:
            evt_type = raw.get('type', '')
            result.append(Event(
                timestamp=raw.get('timestamp', 0),
                type=EventParser.TYPE_MAP.get(evt_type, evt_type),
                source=EventParser._actor_name(raw.get('source')),
                target=EventParser._actor_name(raw.get('target')),
                ability_name=raw.get('ability', {}).get('name', '') if isinstance(raw.get('ability'), dict) else str(raw.get('ability', '')),
                ability_id=raw.get('ability', {}).get('guid', 0) if isinstance(raw.get('ability'), dict) else 0,
                amount=raw.get('amount') if raw.get('amount') is not None else raw.get('total', 0),
                hit_type=raw.get('hitType', '') if raw.get('hitType') is not None else '',
                absorbed=raw.get('absorbed') if raw.get('absorbed') is not None else 0,
                resisted=raw.get('resisted') if raw.get('resisted') is not None else 0,
            ))
        return result

    @staticmethod
    def _actor_name(actor) -> str:
        """统一提取 source/target 名称"""
        if isinstance(actor, dict):
            return actor.get('name', '')
        if isinstance(actor, str):
            return actor
        return ''


if __name__ == '__main__':
    mock_events = [
        {
            'timestamp': 1234567890, 'type': 'cast',
            'source': {'name': '测试法师'}, 'target': {'name': '啸翼'},
            'ability': {'name': '火球术', 'guid': 133},
            'amount': 0, 'hitType': '',
        },
        {
            'timestamp': 1234568000, 'type': 'damage',
            'source': {'name': '测试法师'}, 'target': {'name': '啸翼'},
            'ability': {'name': '火球术', 'guid': 133},
            'amount': 15000, 'hitType': 'crit',
            'absorbed': 0, 'resisted': 0,
        },
        {
            'timestamp': 1234568100, 'type': 'applybuff',
            'source': {'name': '测试法师'}, 'target': {'name': '测试法师'},
            'ability': {'name': '燃烧', 'guid': 190319},
        },
    ]
    events = EventParser.parse(mock_events)
    assert len(events) == 3
    assert events[0].type == 'cast'
    assert events[0].source == '测试法师'
    assert events[1].type == 'damage'
    assert events[1].amount == 15000
    assert events[1].hit_type == 'crit'
    assert events[2].type == 'aura_apply'
    assert events[2].ability_name == '燃烧'
    print("EventParser 测试全部通过")
