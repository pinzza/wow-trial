# 孙青云（Sun Qingyun）调研资料

> 资料收集日期：2026-05-11
> 用途：T1 桃鹤僧教练模式——对标选手档案（教练/教学视频来源）

---

## 基本信息

| 项目 | 值 |
|------|-----|
| B站昵称 | 孙青云 |
| B站空间 | https://space.bilibili.com/3546744384774744 （推测，待确认） |
| 内容方向 | 魔兽世界织雾武僧（鹤僧）教学 |

## B站鹤僧（织雾武僧）教学视频

| 视频标题 | BV号 | 时长 | 类型 | 说明 |
|---------|------|------|------|------|
| 【迷雾之道】至暗之夜S1鹤僧逻辑入门 | BV1vvwozkEZ5 | ~20min | 基础入门 | **核心鹤僧教学**，含鹤僧核心逻辑、天赋、资源循环 |
| 【迷雾之道】大秘境鹤僧技能施放逻辑 | BV1na9nB8EZF | ~8min | 进阶技能 | 大秘境各技能使用优先级、爆发节奏判断 |
| 【迷雾之道】织雾武僧12.0.5改动分析 | BV1FzQHBoEmE | ~8min | 版本更新 | 12.0.5版本变化、新套装/新天赋影响 |

### 视频内容概要（基于标题和简介推测）

#### BV1vvwozkEZ5 — 至暗之夜S1鹤僧逻辑入门
- 鹤僧和治疗玩家的基本思维差异
- 天赋构筑逻辑（英雄天赋选择）
- 资源循环：真气/法力管理
- 铺雾与爆发的时机判断

#### BV1na9nB8EZF — 大秘境鹤僧技能施放逻辑
- 不同战斗场景的技能优先级
- 大招对齐副本时间轴
- 移动战中的治疗策略
- 减伤技能的预判使用

#### BV1FzQHBoEmE — 织雾武僧12.0.5改动分析
- 新套装效果解读
- 天赋树变化
- 手法调整要点
- 属性权重变化

---

## 绿绿月光 WCL 信息

### 初始基准报告

| 项目 | 值 |
|------|-----|
| WCL 报告代码 | DLQHbFkqyX14dvgr |
| 战斗 ID | 92 |
| 副本 | 艾杰斯亚学院 |
| 层数 | +21 |
| 来源 (source) | 398 |
| 类型 | healing |
| 链接 | https://cn.warcraftlogs.com/reports/DLQHbFkqyX14dvgr?fight=92&type=healing&source=398 |

### 搜索方式

使用 WCL Rankings API 按 encounter 搜索：
```bash
WCL_API_KEY=<YOUR_WCL_V1_KEY> python3 -c "
import json, urllib.request
enc_id = 112526  # 艾尔文学院/Algeth'ar Academy
for page in range(1, 30):
    url = f'https://cn.warcraftlogs.com/v1/rankings/encounter/{enc_id}?api_key=<YOUR_WCL_V1_KEY>&page={page}'
    data = json.loads(urllib.request.urlopen(url).read())
    rankings = data.get('rankings', [])
    if not rankings: break
    for r in rankings:
        name = r.get('name', '')
        if '月光' in name:
            print(f'Found: {name} page={page} spec={r.get(\"spec\")} reportID={r.get(\"reportID\")} fightID={r.get(\"fightID\")} level={r.get(\"keystoneLevel\")} hps={r.get(\"total\")}')
"
```

---

## 鹤僧（织雾武僧）12.0 关键要点

### 核心机制
- 织雾在 12.0 是**混合型治疗**：输出伤害的同时产生治疗
- 旭日东升踢（Rising Sun Kick）既是伤害技能也是治疗资源
- 神龙之赐（Invoke Chi-Ji / Yu'lon）是主要爆发治疗手段
- 复苏之雾（Renewing Mist）是核心 HOT 铺场技能

### 重要天赋
- 英雄天赋通常选择**织雾大师**（Mistweaver Mastery）或**神龙尊者**
- 碧玉疾风（Chi Burst）用于 AOE 治疗爆发
- 升腾迷雾（Rising Mist）强化 HOT 续杯机制

### 大秘境注意事项
- 鹤僧对踢法（输出循环）依赖度高，站桩治疗较弱
- 铺雾节奏决定总治疗量上限
- 减伤技能（壮胆酒/散魔功/作茧缚命）需要预判使用
- 12.0.5 版本可能有新的套装/天赋变化（待视频确认）
