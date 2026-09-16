#!/usr/bin/env python3
"""
events_pipeline.py — WCL V1 Events API 数据拉取

用于 mplus_pipeline.py _run_coaching_pipeline 的 Phase 4.5。
产出 x_comparison.json 供报告模型使用。

功能：
  1. 拉取施法时间轴（cast events）
  2. 拉取伤害时间轴（damage-done events）
  3. 拉死亡前15秒治疗事件（healing events）
  4. 按 dungeonPulls 分组 -> 逐波次施法密度 + 技能分布
  5. 输出 x_comparison.json
"""

import json
import os
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any

WCL_BASE = "https://www.warcraftlogs.com/v1"

from core.config import get_api_key

# 冰法主动施法白名单
FROST_MAGE_ACTIVE_CASTS = {
    # 核心伤害
    "寒冰箭", "冰枪术", "冰风暴", "冰川尖刺",
    "寒冰宝珠", "暴风雪", "冰霜射线", "裂片风暴", "冰冻之雨",
    "永冻冰枪", "冰霜裂片", "解离射线", "吞噬裂隙", "冰河突击",
    # AOE/辅助
    "魔爆术", "奥术齐射", "超级新星",
    # 功能性
    "寒冰护体", "闪光术", "镜像", "操控时间", "强化隐形术",
    "法术反制", "解除诅咒", "奥术智慧",
    # 嗜血/药水
    "时间扭曲", "鲁莽药水", "银月城生命药水",
    # 天赋/额外技能
    "深寒凝冰", "龙息术",
}

# 织雾武僧（鹤僧）主动施法白名单
MISTWEAVER_ACTIVE_CASTS = {
    "复苏之雾", "氤氲之雾", "活血术", "还魂术", "神龙之赐",
    "旭日东升踢", "幻灭踢", "猛虎掌", "神鹤引项踢", "碎玉闪电",
    "壮胆酒", "散魔功", "作茧缚命",
    "天神御身", "朱鹤下凡", "碧火踏",
    "雷光聚神茶", "法力茶", "抚慰之雾",
    "滚地翻", "迅如猛虎", "清创生血", "扫堂腿", "魂体双分",
    "死而复生",
}

# 酒仙（坦克）主动施法白名单
BREWMASTER_ACTIVE_CASTS = {
    # 核心输出循环
    "醉酿投", "火焰之息", "幻灭踢", "猛虎掌", "神鹤引项踢",
    "龙焰酒", "迎面铁掌", "特别快递",
    # 爆发/大技能
    "玄牛下凡", "天神灌注", "淬火神酿", "风暴烈酒的珍藏酒桶",
    "再来一桶", "萨萨拉比姆的力量",
    # 酒池管理/减伤
    "活血酒", "浅斟快饮", "壮胆酒", "禅悟状态", "散魔功",
    "躯不坏", "坚定不屈", "明志灵药", "玄牛之魂",
    # 自疗/被动
    "玄牛之赐",
    # 功能性
    "切喉手", "清创生血", "迅如猛虎", "分筋错骨",
    "滚地翻", "无影步", "魂体双分", "平心之环",
    "真气爆裂", "扫堂腿",
    # 药水
    "鲁莽药水",
}

# mode → 白名单映射
ACTIVE_CASTS_MAP = {
    "x": FROST_MAGE_ACTIVE_CASTS,
    "t": MISTWEAVER_ACTIVE_CASTS,
    "b": BREWMASTER_ACTIVE_CASTS,
}


def wcl_get(path: str, params: dict[str, Any]) -> dict:
    """调用 WCL V1 API"""
    params["api_key"] = get_api_key()
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{WCL_BASE}{path}?{qs}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            raise
    raise RuntimeError(f"API 请求失败 (3次重试): {url[:80]}")


def fetch_fights(code: str) -> list[dict]:
    """获取报告的战斗列表"""
    data = wcl_get(f"/report/fights/{code}", {})
    return data.get("fights", [])


def fetch_events(code: str, start_ms: int, end_ms: int,
                 sourceid: int, event_type: str = "cast") -> list[dict]:
    """拉取所有事件（自动分页）"""
    all_events = []
    next_ts = start_ms
    while next_ts is not None and next_ts < end_ms:
        params = {
            "start": next_ts, "end": end_ms,
            "sourceid": sourceid, "type": event_type,
        }
        data = wcl_get(f"/report/events/{code}", params)
        events = data.get("events", [])
        all_events.extend(events)
        next_ts = data.get("nextPageTimestamp")
        if len(events) < 10000:
            break
    return all_events


def filter_active_casts(events: list[dict], whitelist: set[str]) -> list[dict]:
    """从 events 中过滤出主动施法"""
    result = []
    for e in events:
        if e.get("type") != "cast":
            continue
        ability = e.get("ability", {})
        name = ability.get("name", "")
        if name in whitelist:
            result.append(e)
        # 也保留不在白名单但确实是主动施法的技能
        # 冰刺/凛冬之末等被动技会自然排除
    return result


def compute_wave_stats(code: str, fight: dict, sourceid: int,
                       whitelist: set[str]) -> list[dict]:
    """逐波次计算施法统计"""
    fight_start = fight.get("start_time", 0)
    fight_end = fight.get("end_time", 0)
    pulls = fight.get("dungeonPulls", [])
    if not pulls:
        return []

    # 拉全量 cast events
    raw_events = fetch_events(code, fight_start, fight_end, sourceid, "cast")
    casts = filter_active_casts(raw_events, whitelist)

    # 按波次分组
    waves = []
    for i, pull in enumerate(pulls):
        ps = pull.get("start_time", 0)
        pe = pull.get("end_time", 0)
        name = pull.get("name", f"波次{i+1}")
        is_boss = pull.get("boss", False)

        wave_casts = [c for c in casts if ps <= c.get("timestamp", 0) <= pe]
        duration_s = (pe - ps) / 1000
        density = len(wave_casts) / duration_s if duration_s > 0 else 0

        # 技能分布
        skill_dist = {}
        for c in wave_casts:
            sn = c.get("ability", {}).get("name", "未知")
            skill_dist[sn] = skill_dist.get(sn, 0) + 1

        # 取 top 5 技能
        top5 = sorted(skill_dist.items(), key=lambda x: -x[1])[:5]

        waves.append({
            "wave_id": i + 1,
            "name": name,
            "is_boss": is_boss,
            "duration_s": round(duration_s, 1),
            "total_casts": len(wave_casts),
            "density": round(density, 2),
            "top_skills": [{"name": k, "count": v} for k, v in top5],
            "casts_simple": [
                {"t": c.get("timestamp", 0) - ps,
                 "s": c.get("ability", {}).get("name", "?")}
                for c in wave_casts[:50]  # 最多50个节点
            ],
        })

    return waves


def fetch_death_healing(code: str, death_time_ms: int,
                        fight_start: int, sourceid: int) -> dict:
    """拉死亡前15秒的治疗事件"""
    window_start = max(fight_start, death_time_ms - 15000)
    events = fetch_events(code, window_start, death_time_ms, sourceid, "healing")
    total_healing = sum(e.get("amount", 0) for e in events)
    return {
        "death_time_s": round(death_time_ms / 1000, 1),
        "window_start_s": round(window_start / 1000, 1),
        "heal_events": len(events),
        "total_healing": total_healing,
    }


def build_x_comparison(learner_code: str, learner_fight_id: int,
                       learner_sourceid: int,
                       benchmark_code: str, benchmark_fight_id: int,
                       benchmark_sourceid: int,
                       death_events: list[dict] | None = None,
                       output_path: str | Path | None = None,
                       mode: str = "x") -> dict:
    """主入口：生成 x_comparison.json"""
    result = {
        "pipeline_version": "5.0.0",
        "learner": {"report": learner_code, "fight": learner_fight_id, "source": learner_sourceid},
        "benchmark": {"report": benchmark_code, "fight": benchmark_fight_id, "source": benchmark_sourceid},
        "waves_learner": [],
        "waves_benchmark": [],
        "death_healing": [],
        "summary": {},
    }

    # 1. 获取 fights 元数据
    log("拉取学习者 fights...")
    l_fights = fetch_fights(learner_code)
    l_fight = next((f for f in l_fights if f.get("id") == learner_fight_id), None)
    if not l_fight:
        result["error"] = f"学习者 fight {learner_fight_id} 未找到"
        return result

    log("拉取清心 fights...")
    b_fights = fetch_fights(benchmark_code)
    b_fight = next((f for f in b_fights if f.get("id") == benchmark_fight_id), None)
    if not b_fight:
        result["error"] = f"清心 fight {benchmark_fight_id} 未找到"
        return result

    # 2. 逐波次分析（按 mode 选择白名单）
    whitelist = ACTIVE_CASTS_MAP.get(mode, FROST_MAGE_ACTIVE_CASTS)
    log(f"使用白名单: {mode} mode ({len(whitelist)} 个技能)")

    log("逐波次分析学习者...")
    result["waves_learner"] = compute_wave_stats(
        learner_code, l_fight, learner_sourceid, whitelist)

    log("逐波次分析清心...")
    result["waves_benchmark"] = compute_wave_stats(
        benchmark_code, b_fight, benchmark_sourceid, whitelist)

    # 3. 死亡治疗分析
    if death_events:
        log("拉取死亡前治疗...")
        for d in death_events:
            dt = d.get("timestamp", 0)
            healing = fetch_death_healing(
                learner_code, dt, l_fight.get("start_time", 0), learner_sourceid)
            healing["death_ability"] = d.get("ability_name", "?")
            healing["damage_taken"] = d.get("damage", 0)
            result["death_healing"].append(healing)

    # 4. 汇总
    l_casts = sum(w["total_casts"] for w in result["waves_learner"])
    b_casts = sum(w["total_casts"] for w in result["waves_benchmark"])
    l_density = [w["density"] for w in result["waves_learner"]]
    b_density = [w["density"] for w in result["waves_benchmark"]]
    result["summary"] = {
        "learner_total_casts": l_casts,
        "benchmark_total_casts": b_casts,
        "learner_avg_density": round(sum(l_density) / len(l_density), 2) if l_density else 0,
        "benchmark_avg_density": round(sum(b_density) / len(b_density), 2) if b_density else 0,
        "learner_wave_count": len(result["waves_learner"]),
        "benchmark_wave_count": len(result["waves_benchmark"]),
    }

    # 5. 写入
    if output_path:
        Path(output_path).write_text(
            json.dumps(result, ensure_ascii=False, indent=2))
        log(f"✅ x_comparison.json 已写入: {output_path}")

    return result


def log(msg: str):
    print(f"[events_pipeline] {msg}", flush=True)
