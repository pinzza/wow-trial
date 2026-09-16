# WCL API combatantInfo 数据提取指南

> 版本: 2026-05-18 | 适用于 v1_pipeline v5.3.0+

## 概述

WCL V1 API 的 `/report/tables/summary/{code}` 返回的 `playerDetails` 中包含 `combatantInfo` 对象，提供角色装备、属性、天赋、消耗品等数据。**这比 V1 tables 端点的数据更完整**，特别适合单人教练报告的配装/增益分析。

## API 端点

```
GET /v1/report/tables/summary/{report_code}
```

## combatantInfo 结构

```json
{
  "playerDetails": {
    "dps": [{
      "name": "不穷锋",
      "potionUse": 5,
      "healthstoneUse": 0,
      "minItemLevel": 285,
      "maxItemLevel": 285,
      "combatantInfo": {
        "specIDs": [71],
        "stats": {
          "Strength": {"min": 2173, "max": 2173},
          "Stamina": {"min": 24814, "max": 24814},
          "Crit": {"min": 1113, "max": 1113},
          "Haste": {"min": 826, "max": 826},
          "Mastery": {"min": 568, "max": 568},
          "Versatility": {"min": 33, "max": 33},
          "Leech": {"min": 249, "max": 249}
        },
        "gear": [
          {"slot": 0, "name": "终夜者的獠牙头盔", "itemLevel": 289, "quality": 4, "setID": 1990, "setName": "..."},
          {"slot": 12, "name": "上古饥渴之心", "itemLevel": 289, ...},
          {"slot": 13, "name": "艾林先知的凝视", "itemLevel": 289, ...}
        ],
        "talents": [],
        "talentTree": [
          {"id": 112121}, {"id": 112122}, ...
        ]
      }
    }]
  }
}
```

## 关键字段用途

| 字段 | 路径 | 用途 |
|------|------|------|
| potionUse | `playerDetails[role][].potionUse` | 爆发药水使用次数 |
| healthstoneUse | `playerDetails[role][].healthstoneUse` | 治疗石使用次数 |
| stats.Strength | `combatantInfo.stats.Strength.min` | 主属性（力量/敏捷/智力） |
| stats.Crit | `combatantInfo.stats.Crit.min` | 暴击绿字 |
| stats.Haste | `combatantInfo.stats.Haste.min` | 急速绿字 |
| stats.Mastery | `combatantInfo.stats.Mastery.min` | 精通绿字 |
| stats.Versatility | `combatantInfo.stats.Versatility.min` | 全能绿字 |
| gear[].setID | `combatantInfo.gear[].setID` | 套装ID（用于判断4件套） |
| gear[].itemLevel | `combatantInfo.gear[].itemLevel` | 单件装等 |
| gear[].slot | `combatantInfo.gear[].slot` | 装备槽位 |
| talentTree | `combatantInfo.talentTree[]` | 天赋树节点（用于解析英雄天赋） |

## 装备槽位含义

| slot | 部位 | 分类 |
|------|------|------|
| 0 | 头部 | 大件 |
| 1 | 颈部 | 大件 |
| 2 | 肩部 | 大件 |
| 4 | 胸部 | 大件 |
| 5 | 腰部 | 小件 |
| 6 | 腿部 | 大件 |
| 7 | 脚部 | 小件 |
| 8 | 护腕 | 小件 |
| 9 | 手套 | 小件 |
| 10 | 戒指1 | 大件 |
| 11 | 戒指2 | 大件 |
| 12 | 饰品1 | 饰品 |
| 13 | 饰品2 | 饰品 |
| 14 | 披风 | 小件 |
| 15 | 主手武器 | 大件 |
| 16 | 副手/盾牌 | (视情况) |

**装等虚实计算**：大件 = {0,1,2,4,6,10,11,15} ∪ {16 if 双手武器}，小件 = {5,7,8,9,14}，饰品独立。

## 英雄天赋解析

通过 `talentTree` 的节点 ID 判断英雄天赋。核心 buff spell_id 在 aura 表中验证：

| 英雄天赋 | 职业 | 核心 Buff spell_id | 名称 |
|----------|------|-------------------|------|
| 巨神兵 (Colossus) | 战士 | 440989 | 巨人神力 |
| 屠戮者 (Slayer) | 战士 | 384361 | 屠戮者之赐 |
| 山丘领主 (Mountain Thane) | 战士 | 386196 | 雷霆之击 |

判断优先级：`talentTree` 节点 → `aura` 表 spell_id 验证。两者交叉确认最准确。

## 消耗品 Buff 映射

| WCL 显示名 | spell_id | 含义 |
|-----------|----------|------|
| 血骑士合剂 | 1235110 | 力量合剂 |
| 魔导师合剂 | 1235108 | 智力合剂 |
| 丰盛进食充分 | 1233732 | 食物（大餐） |
| 凡图斯符文：光耀 | 1277389 | 符文 |
| 凡图斯符文：宇宙之冕 | 1276715 | 符文（双符文检测） |
| 鲁莽药水 | 370602 | 爆发药水（通过 potionUse 而非 buff 检测） |
