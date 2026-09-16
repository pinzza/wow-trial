#!/usr/bin/env python3
"""
spell_cn_map.py — spell_id → 国服简体中文名 解析模块

解决跨语言客户端导致的技能名/Buff名不统一问题：
  - 我方报告 (cn.warcraftlogs.com) → 中文名
  - 顶层选手报告 (俄/英等客户端) → 俄文/英文名
  - 统一通过 spell_id 解析为国服简体中文名

设计原则:
  1. spell_id 为主键，不做客户端语言假设
  2. 内置字典覆盖已知高频技能/Buff
  3. 自动从已有中文 DB 提取映射 (bootstrap)
  4. 未命中时回退到原始名称，同时记录到 missing 日志

用法:
    from core.spell_cn_map import resolve, is_chinese, lookup_multiple

    name = resolve(455476)           # → "召唤灼焦恶犬"
    name = resolve(455476, "Summon Charhound")  # fallback if not found
"""

import sqlite3
import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── 硬编码核心映射（优先于 DB 自提取）──────────────────────────────
# 来源：Wowhead CN / 游戏内 / 已知跨语言需求
HARDCODED_MAP: dict[int, str] = {
    # ── 基础 ──
    1: "近战",
    # ── 恶魔术 ──
    455476: "召唤灼焦恶犬",        # Summon Charhound (Mark of F'harg)
    104316: "召唤恐惧猎犬",
    265187: "召唤恶魔暴君",
    1276222: "阿古斯支配",
    428514: "敬魔仪式",
    105174: "古尔丹之手",
    104317: "野生小鬼 (古尔丹之手)",
    279910: "野生小鬼 (内心之魔/地狱一游)",
    30146: "奥里克阿沙克",
    686: "暗影箭",
    1276452: "魔典：小鬼领主",
    196278: "内爆",
    264178: "恶魔之箭",
    # ── 暗牧 ──
    34914: "吸血鬼之触",             # Прикосновение вампира / Vampiric Touch
    232698: "暗影形态",
    15473: "暗影形态",
    199486: "心智联结",
    147193: "暗影幻灵",
    335467: "暗言术：癫",
    120644: "光晕",
    1264176: "虚空幻灵",
    390978: "命运多舛",
    373277: "彼岸之物",
    393919: "虚空尖啸",
    373213: "怒火暗生",
    391092: "碎裂心智",
    # ── 武器战 ──
    845: "顺劈斩",
    436358: "崩摧",
    12294: "致死打击",
    7384: "压制",
    1464: "猛击",
    262115: "重伤",
    260708: "横扫攻击",
    1269394: "战争大师",
    440989: "巨人神力",
    # ── 酒仙 ──
    121253: "醉酿投",
    450615: "疾风乱打",
    115181: "火焰之息",
    100780: "猛虎掌",
    322109: "轮回之触",
    196733: "特别快递",
    205523: "幻灭踢",
    452333: "无匹之劲",              # Подавляющая мощь / Overwhelming Power
    1292919: "大道同归",             # Слияние / Confluence
    450508: "和谐化身",              # Аспект гармонии / Aspect of Harmony
    215479: "酒醒入定",
    1260619: "强化醉拳",
    383733: "砮皂的试炼",
    # ── 恢复萨 ──
    73921: "治疗之雨",
    188389: "烈焰震击",
    51505: "熔岩爆裂",
    61295: "激流",
    53390: "潮汐奔涌",
    188443: "闪电链",                # Chain Lightning
    207400: "先祖活力",
    # ── 通用 Buff / 装备触发 ──
    1255504: "太阳耀斑棱镜",
    1252489: "变通狩猎",
    1241715: "虚空的力量",
    334783: "间接伤害",
    392778: "狂野打击",
    1270840: "削肉剔骨",
    1241759: "睿识真知",
    470077: "聚合流水",
    192082: "狂风",
    1262753: "上古饥渴之心",
    1266686: "艾林洞察",
    1266687: "艾蔑精华",
    1229746: "奥纹洞察",
    393515: "无常虚妄",
    # ── 噬灭 DH ──
    1256322: "虚落",
    1227338: "天启将至",
    1217607: "虚空变形",
    1227702: "坍缩之星",
    1232310: "灵魂盛宴",
    1225789: "虚空变形",
    1245577: "灵魂残片",
    1226033: "根除",
    1221150: "坍缩之星",
    473728: "虚空射线",
    1256306: "虚落流星",
    1217610: "吞噬",
    # ── 防骑 ──
    31935: "复仇者之盾",
    53600: "正义盾击",
    275779: "审判",
    447258: "锻炉的清算",
    1241413: "愤怒之锤",
    188370: "奉献",
    31884: "复仇之怒",
    132403: "正义盾击",
    460822: "神恩指引",
    432502: "圣洁武器",
    1272298: "光佑之盾",
    462568: "元素抗性",
    182104: "闪耀之光",
    1277026: "愤怒之锤",
    # ── 术士通用 ──
    108366: "灵魂榨取",
    387552: "狱火统御",
    # ── 其他技能/事件 ──
    1258283: "光盲圣怒的道标",        # Beacon of Lightblind Wrath
    1263721: "光盲圣怒的连祷",
    # ── 治疗技能 ──
    5672: "治疗之泉",
    1267765: "风暴涌流图腾",
    # ── 小怪/Boss 技能 ──
    394917: "湮灭之箭",
    # ── 12.0 武器战 ──
    227847: "剑刃风暴",              # Bladestorm
    445579: "屠戮者打击",            # Slayer's Strike
    446005: "掠武风暴",              # Reap the Storm
}

# ── 从已有 DB 自提取映射 ──────────────────────────────────────────

_DB_EXTRACTED: dict[int, str] = {}
_initialized = False


def _extract_from_dbs(db_paths: list[str]) -> dict[int, str]:
    """从已有的中文 DB 中提取 spell_id → 中文名映射"""
    result = {}
    for db_path in db_paths:
        if not Path(db_path).exists():
            continue
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            # abilities
            for row in conn.execute("SELECT spell_id, name FROM ability"):
                sid = row["spell_id"]
                name = row["name"]
                if sid and name and sid > 1 and _has_cjk(name):
                    result[sid] = name
            # auras
            for row in conn.execute("SELECT spell_id, name FROM aura"):
                sid = row["spell_id"]
                name = row["name"]
                if sid and name and sid > 1 and _has_cjk(name):
                    result[sid] = name
            # event abilities
            for row in conn.execute(
                "SELECT ability_id, ability_name FROM event WHERE ability_id > 1"
            ):
                sid = row["ability_id"]
                name = row["ability_name"]
                if sid and name and _has_cjk(name):
                    result[sid] = name
            conn.close()
        except Exception:
            pass
    return result


def _has_cjk(text: str) -> bool:
    """检测文本是否含有 CJK 字符（中日韩统一表意文字）"""
    return bool(re.search(r"[\u4e00-\u9fff\u3400-\u4dbf]", text))


# ── 公开 API ──────────────────────────────────────────────────────


def init(db_dir: str = "data/wcl_db", extra_dbs: list[str] | None = None):
    """初始化映射表：合并硬编码 + DB 自提取

    Args:
        db_dir: 含 *.db 文件的目录
        extra_dbs: 额外 DB 路径列表
    """
    global _DB_EXTRACTED, _initialized

    # 扫描所有 DB
    db_paths = []
    db_dir_path = Path(db_dir)
    if db_dir_path.exists():
        db_paths.extend(str(p) for p in db_dir_path.glob("*.db"))
    if extra_dbs:
        db_paths.extend(extra_dbs)

    extracted = _extract_from_dbs(db_paths)
    logger.info(f"从 {len(db_paths)} 个 DB 提取到 {len(extracted)} 个中文技能名")

    _DB_EXTRACTED = extracted
    _initialized = True


def resolve(spell_id: int, fallback: str = "") -> str:
    """spell_id → 国服简体中文名

    解析优先级: 硬编码 > DB 自提取 > fallback > f"spell_{spell_id}"

    Args:
        spell_id: 技能/法术 ID
        fallback: 未命中时的回退名（如原始英文名）

    Returns:
        中文名（或 fallback）
    """
    if not spell_id or spell_id <= 0:
        return fallback or "未知"

    # 1. 硬编码
    if spell_id in HARDCODED_MAP:
        return HARDCODED_MAP[spell_id]

    # 2. DB 自提取
    if spell_id in _DB_EXTRACTED:
        return _DB_EXTRACTED[spell_id]

    # 3. Fallback
    if fallback and _has_cjk(fallback):
        return fallback  # fallback 本身就是中文

    if fallback:
        return fallback  # 英文/俄文 fallback，保持原样

    return f"spell_{spell_id}"


def resolve_safe(spell_id: int, fallback: str = "") -> str:
    """resolve() 的变体：如果 fallback 是非中文，标记出来"""
    result = resolve(spell_id, fallback)
    if result == fallback and fallback and not _has_cjk(fallback):
        # 非中文的 fallback，标记
        return f"{fallback} [非中文, spell_id={spell_id}]"
    return result


def is_chinese(text: str) -> bool:
    """检查文本是否为中文"""
    return _has_cjk(text)


def lookup_multiple(spell_ids: list[int], fallbacks: dict[int, str] | None = None) -> dict[int, str]:
    """批量解析"""
    fb = fallbacks or {}
    return {sid: resolve(sid, fb.get(sid, "")) for sid in spell_ids}


def get_missing(spell_ids: list[int]) -> list[int]:
    """检查哪些 spell_id 未命中映射"""
    return [sid for sid in spell_ids if sid not in HARDCODED_MAP and sid not in _DB_EXTRACTED]


def add_mapping(spell_id: int, cn_name: str):
    """运行时动态添加映射（如从 Wowhead 确认后）"""
    HARDCODED_MAP[spell_id] = cn_name


def mapping_stats() -> dict:
    """返回映射表统计"""
    return {
        "hardcoded": len(HARDCODED_MAP),
        "db_extracted": len(_DB_EXTRACTED),
        "total": len(set(HARDCODED_MAP) | set(_DB_EXTRACTED)),
    }
