#!/usr/bin/env python3
"""WCL 数据模型 — Pydantic 定义所有实体"""

from pydantic import BaseModel, Field
from typing import Optional


class Ability(BaseModel):
    """玩家技能统计"""
    name: str
    spell_id: int = 0
    amount: float = 0.0
    hits: int = 0
    crits: int = 0
    miss_pct: float = 0.0


class Aura(BaseModel):
    """光环/Buff 覆盖统计"""
    name: str
    spell_id: int = 0
    uptime_pct: float = 0.0


class Event(BaseModel):
    """毫秒级战斗事件"""
    timestamp: int
    type: str  # damage / heal / death / aura_apply / aura_remove
    source: str = ''
    target: str = ''
    ability_name: str = ''
    ability_id: int = 0
    amount: float = 0.0
    hit_type: str = ''  # hit / crit / miss / tick
    absorbed: float = 0.0
    resisted: float = 0.0


class Player(BaseModel):
    """玩家统计"""
    name: str
    class_: str = Field(default='', alias='class')
    spec: str = ''
    ilvl: int = 0
    server: str = ''
    damage_total: float = 0.0
    heal_total: float = 0.0
    parse_pct: float = 0.0
    dps: float = 0.0
    abilities: list[Ability] = []
    auras: list[Aura] = []

    class Config:
        populate_by_name = True


class NPC(BaseModel):
    """NPC 统计"""
    name: str
    npc_id: int = 0
    type: str = 'add'  # boss / add / caster
    damage_taken: float = 0.0
    death_time: int = 0


class Fight(BaseModel):
    """单场战斗摘要"""
    fight_id: int
    name: str = ''
    kill: bool = False
    difficulty: str = ''
    start_time: int = 0
    end_time: int = 0
    percentage: float = 0.0
    players: list[Player] = []
    events: list[Event] = []
    npcs: list[NPC] = []


class Report(BaseModel):
    """报告元数据"""
    report_code: str
    title: str = ''
    start_time: int = 0
    end_time: int = 0
    zone: str = ''
    owner: str = ''
    fights: list[Fight] = []


if __name__ == '__main__':
    # 测试 Ability
    a = Ability(name="暗影箭", spell_id=47813, amount=1234567.0, hits=50, crits=20)
    assert a.miss_pct == 0.0  # 默认值
    d = a.model_dump()
    assert d['name'] == '暗影箭'

    # 测试类型自动转换
    a2 = Ability(name="火球术", spell_id=133, amount="500000", hits="30", crits="10")
    assert a2.amount == 500000.0
    assert a2.hits == 30

    # 测试 Aura
    au = Aura(name="奥术智慧", spell_id=1459, uptime_pct=95.5)
    assert au.uptime_pct == 95.5

    # 测试 Event
    e = Event(timestamp=1234567890, type="damage", source="玩家A", target="Boss",
              ability_name="暗影箭", ability_id=47813, amount=15000.0, hit_type="crit")
    assert e.absorbed == 0.0  # 默认值

    # 测试 Player (含内嵌 abilities + auras)
    p = Player(name="测试玩家", class_="Warlock", spec="Destruction", ilvl=280, server="霜狼",
               damage_total=5000000.0, parse_pct=95.5, dps=12000.0,
               abilities=[a], auras=[au])
    assert len(p.abilities) == 1
    assert len(p.auras) == 1
    d = p.model_dump()
    assert d['class_'] == 'Warlock'

    # 测试 Fight
    f = Fight(fight_id=1, name="BOSS名称", kill=True, difficulty="Mythic",
              start_time=1234567890, end_time=1234667890,
              players=[p], events=[e])
    assert len(f.players) == 1

    # 测试 Report
    r = Report(report_code="qavZzKjfyNhmF7V1", title="测试报告",
               start_time=1234567890, end_time=1234667890,
               zone="纳斯利亚堡", owner="RL名称")
    assert r.fights == []  # 默认空列表

    # 测试递归 model_dump
    d = f.model_dump()
    assert d['players'][0]['abilities'][0]['name'] == '暗影箭'

    print("所有模型测试通过")
