#!/usr/bin/env python3
"""WCL V1 事件抓取器 —— 已内建全部已知 API 陷阱的规避。

为什么需要它：`core/v1_pipeline.py` 落库的 `event` 表把 events 端点返回的所有事件
都标成 `type='cast'`，混有 damage/heal/applybuff 的 tick，**不能**用作施法序列。
需要逐次施法/伤害序列时必须直连 `/report/events`。

本脚本处理的陷阱（详见 ../references/pitfalls.md）：
  * 带 `sourceid` 时 `type` / `abilityid` 过滤会被忽略 → 只请求一次，本地过滤
  * `sourceid` 过滤不彻底 → 本地按 sourceID 精确过滤
  * V1 不返回 `crit` 字段 → 用 `hitType`（1=命中, 2=暴击）
  * 分页用 `nextPageTimestamp` + guard 兜底
  * SSLEOFError / 429 / 5xx → 指数退避重试

只依赖标准库，系统 python3 (3.12) 可直接运行。

用法
----
# 1) 先看报告元数据（层数 / 战斗窗口 / friendlies 的 sourceID）
python3 wcl_events.py meta --code RXCBtHF4yD37qK1w

# 2) 拉某个玩家在某场战斗内的事件序列
python3 wcl_events.py events \
    --code RXCBtHF4yD37qK1w --start 7482072 --end 9053072 \
    --source-id 2 --out data/cache/dh/ours_events.json

# 3) 看一下已有输出里的技能聚合
python3 wcl_events.py summarize --in data/cache/dh/ours_events.json --top 15
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://www.warcraftlogs.com/v1"
# 与本仓库 core/v1_pipeline.py 的默认值保持一致；可用 $WCL_API_KEY 覆盖。
DEFAULT_API_KEY = "<YOUR_WCL_V1_KEY>"


def api_key(explicit: str | None = None) -> str:
    return explicit or os.environ.get("WCL_API_KEY") or DEFAULT_API_KEY


def wcl_get(path: str, params: dict, retries: int = 4, timeout: int = 90) -> dict:
    """带指数退避的 GET。返回解析后的 JSON。"""
    params = {k: v for k, v in params.items() if v is not None}
    url = f"{BASE}{path}?{urllib.parse.urlencode(params)}"
    last: Exception | None = None
    for attempt in range(retries):
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code in (429, 500, 502, 503) and attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise
        except Exception as exc:  # noqa: BLE001  (SSL EOF 等网络抖动)
            last = exc
            time.sleep(1 + attempt)
    raise RuntimeError(f"请求失败: {path} ({last})")


# --------------------------------------------------------------------------- #
# meta
# --------------------------------------------------------------------------- #
def cmd_meta(args) -> int:
    key = api_key(args.api_key)
    data = wcl_get(f"/report/fights/{args.code}", {"api_key": key, "translate": "true"})

    print(f"报告: {data.get('title')}  ({args.code})")
    # V1 的 zone 字段在不同报告里可能是 int（zone id）或 dict，别假设。
    zone = data.get("zone")
    zone_name = zone.get("name") if isinstance(zone, dict) else zone
    print(f"副本: {zone_name}   owner: {data.get('owner')}")
    print()

    fights = data.get("fights") or []
    if fights:
        print("战斗 (fight_id | 名称 | 层数 | start_time | end_time | 时长):")
        for f in fights:
            if f.get("boss") == 0 and not f.get("keystoneLevel"):
                continue
            dur = (f.get("end_time", 0) - f.get("start_time", 0)) / 1000
            print(
                f"  {f.get('id'):>4} | {str(f.get('name'))[:28]:<28} | "
                f"{f.get('keystoneLevel') or '-':>4} | {f.get('start_time'):>10} | "
                f"{f.get('end_time'):>10} | {dur/60:5.1f} min"
            )
        print()

    friendlies = data.get("friendlies") or []
    if friendlies:
        print("友方 (friendlies[].id 就是 events 的 sourceID):")
        # 注意: 玩家的 type 字段是**职业名**(Paladin/DemonHunter/...)，不是 "Player"；
        # 非玩家才是 "NPC"/"Pet"。
        for p in friendlies:
            if p.get("type") in ("NPC", "Pet"):
                continue
            print(f"  id={p.get('id'):<6} {str(p.get('type')):<14} {p.get('name')}")
    print()
    print("提示: URL 的 ?source= 等于 friendlies[].id，但不等于 DB 的 player.id；")
    print("      请用玩家名在 DB 里定位，用这里的 id 拉 events。")
    return 0


# --------------------------------------------------------------------------- #
# events
# --------------------------------------------------------------------------- #
def fetch_events(code: str, key: str, start: int, end: int,
                 source_id: int | None, guard: int = 80) -> tuple[list, list, int]:
    """拉取 [start, end) 窗口内的全部事件，并在本地过滤。

    注意：**不传 type**（传了也会被忽略），把过滤全部放到本地做。
    """
    raw: list = []
    cur = start
    pages = 0
    while cur is not None and cur < end and pages < guard:
        pages += 1
        # 传 sourceid 只能起"部分"过滤作用，绝不能依赖；本地仍会精确过滤。
        params = {"api_key": key, "start": cur, "end": end}
        if source_id is not None:
            params["sourceid"] = source_id
        data = wcl_get(f"/report/events/{code}", params)
        events = data.get("events") or []
        if not events:
            break
        raw.extend(events)
        nxt = data.get("nextPageTimestamp")
        if nxt is None or nxt <= cur:
            break
        cur = nxt
        time.sleep(0.2)

    casts: list = []
    damage: list = []
    for e in raw:
        if source_id is not None and e.get("sourceID") != source_id:
            continue
        ability = e.get("ability") or {}
        guid = ability.get("guid")
        name = ability.get("name")
        ts = e.get("timestamp")
        etype = e.get("type")
        if etype == "cast":
            casts.append([ts, guid, name])
        elif etype == "damage":
            # hitType: 1=命中, 2=暴击（V1 不返回 crit 字段）
            damage.append([
                ts, guid, name, e.get("amount"),
                e.get("hitType"), e.get("targetID"),
            ])
    casts.sort(key=lambda r: r[0] or 0)
    damage.sort(key=lambda r: r[0] or 0)
    return casts, damage, len(raw)


def cmd_events(args) -> int:
    key = api_key(args.api_key)
    casts, damage, seen = fetch_events(
        args.code, key, args.start, args.end, args.source_id, args.guard
    )
    payload = {
        "code": args.code,
        "start": args.start,
        "end": args.end,
        "source_id": args.source_id,
        "counts": {
            "events_seen": seen,
            "casts": len(casts),
            "damage": len(damage),
        },
        # 紧凑数组，控制体积
        "casts": casts,
        "damage": damage,
    }
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
        print(f"已写入 {args.out}")
    print(
        f"窗口 [{args.start}, {args.end}) 收到 {seen} 条事件；"
        f"本地过滤后 cast={len(casts)} damage={len(damage)}"
    )
    if seen and len(casts) + len(damage) > seen:
        print("警告: 本地保留数大于收到数，说明分页有重叠，请检查窗口参数。", file=sys.stderr)

    if not casts and not damage:
        print(
            "提示: 一条都没留下。常见原因：\n"
            "  * source-id 传错（用 meta 子命令核对 friendlies[].id）\n"
            "  * start/end 不是该战斗的窗口（用 meta 子命令看 fight.start_time/end_time）",
            file=sys.stderr,
        )
    return 0


# --------------------------------------------------------------------------- #
# summarize
# --------------------------------------------------------------------------- #
def _fmt(value) -> str:
    return f"{value:,.0f}" if isinstance(value, (int, float)) else "-"


def cmd_summarize(args) -> int:
    with open(args.input, encoding="utf-8") as fh:
        payload = json.load(fh)

    casts = payload.get("casts") or []
    damage = payload.get("damage") or []

    cast_count: dict = {}
    for _ts, guid, name in casts:
        key = (guid, name)
        cast_count[key] = cast_count.get(key, 0) + 1

    dmg: dict = {}
    for _ts, guid, name, amount, hit_type, _target in damage:
        slot = dmg.setdefault((guid, name), {"n": 0, "sum": 0.0, "nc": 0, "ncs": 0.0, "c": 0})
        slot["n"] += 1
        slot["sum"] += amount or 0
        if hit_type == 1:
            slot["nc"] += 1
            slot["ncs"] += amount or 0
        elif hit_type == 2:
            slot["c"] += 1

    print(f"=== 施法次数 top {args.top}（唯一可信口径）===")
    for (guid, name), n in sorted(cast_count.items(), key=lambda kv: -kv[1])[: args.top]:
        print(f"  {str(name)[:30]:<30} {n:>6} 次   id={guid}")

    print()
    print(f"=== 伤害（按每发排序）top {args.top} ===")
    print(f"  {'技能':<30}{'事件':>8}{'总伤':>14}{'每发':>12}{'非暴击每发':>14}{'暴击率':>9}")
    rows = []
    for (guid, name), s in dmg.items():
        per = s["sum"] / s["n"] if s["n"] else 0
        nc_per = s["ncs"] / s["nc"] if s["nc"] else 0
        cr = s["c"] / s["n"] if s["n"] else 0
        rows.append((per, name, guid, s, per, nc_per, cr))
    for _per, name, guid, s, per, nc_per, cr in sorted(rows, reverse=True)[: args.top]:
        print(
            f"  {str(name)[:30]:<30}{s['n']:>8}{_fmt(s['sum']):>14}"
            f"{_fmt(per):>12}{_fmt(nc_per):>14}{cr:>8.1%}"
        )
    print()
    print("非暴击每发 = 用作装等基准的干净口径；暴击率由 hitType==2 统计。")

    if args.out_stats:
        stats = {
            f"{guid}|{name}": {
                "casts": cast_count.get((guid, name), 0),
                "events": s["n"],
                "damage_total": s["sum"],
                "per_hit": (s["sum"] / s["n"]) if s["n"] else 0,
                "per_hit_nocrit": (s["ncs"] / s["nc"]) if s["nc"] else 0,
                "crit_rate": (s["c"] / s["n"]) if s["n"] else 0,
            }
            for (guid, name), s in dmg.items()
        }
        with open(args.out_stats, "w", encoding="utf-8") as fh:
            json.dump(stats, fh, ensure_ascii=False, indent=2)
        print(f"统计已写入 {args.out_stats}")
    return 0


# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="WCL V1 事件抓取与聚合（已规避已知 API 陷阱）")
    p.add_argument("--api-key", help="默认取 $WCL_API_KEY，否则用仓库内置默认值")
    sub = p.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("meta", help="打印报告元数据：层数 / 战斗窗口 / friendlies 的 sourceID")
    m.add_argument("--code", required=True)
    m.set_defaults(func=cmd_meta)

    e = sub.add_parser("events", help="拉取指定玩家在指定战斗窗口内的事件序列")
    e.add_argument("--code", required=True)
    e.add_argument("--start", type=int, required=True, help="fight.start_time")
    e.add_argument("--end", type=int, required=True, help="fight.end_time")
    e.add_argument("--source-id", type=int, default=None,
                   help="friendlies[].id；不传则保留全部来源（体积会大很多）")
    e.add_argument("--out", help="输出 JSON 路径")
    e.add_argument("--guard", type=int, default=80, help="分页上限，防死循环")
    e.set_defaults(func=cmd_events)

    s = sub.add_parser("summarize", help="聚合已抓取的事件文件")
    s.add_argument("--in", dest="input", required=True)
    s.add_argument("--top", type=int, default=15)
    s.add_argument("--out-stats", help="把逐技能统计写成 JSON")
    s.set_defaults(func=cmd_summarize)
    return p


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
