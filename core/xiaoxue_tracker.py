#!/usr/bin/env python3
"""
core/xiaoxue_tracker.py — 小雪法神之路进度追踪

管理 data/xiaoxue/progress.db，提供快照写入、历史查询、里程碑判定、
任务状态追踪和 ASCII 趋势图生成。

用法:
    python3 core/xiaoxue_tracker.py --latest 6
    python3 core/xiaoxue_tracker.py --trend dps --count 6
    python3 core/xiaoxue_tracker.py --milestones
"""

import json
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

# ── 路径 ──────────────────────────────────────────────────────────
PROJECT_DIR = Path(__file__).resolve().parent.parent
XIAOXUE_DATA_DIR = PROJECT_DIR / "data" / "xiaoxue"
DEFAULT_DB_PATH = XIAOXUE_DATA_DIR / "progress.db"

# ── DDL ───────────────────────────────────────────────────────────
DDL_SNAPSHOTS = """
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    report_code TEXT NOT NULL,
    dungeon TEXT NOT NULL,
    level INTEGER NOT NULL,
    timed INTEGER DEFAULT 0,
    dps INTEGER,
    vs_benchmark_pct REAL,
    deaths INTEGER,
    interrupts INTEGER,
    duration_sec REAL,
    ability_pcts TEXT DEFAULT '{}',
    ability_casts TEXT DEFAULT '{}',
    survival_skills TEXT DEFAULT '{}',
    report_path TEXT,
    summary_path TEXT
)
"""

DDL_TASKS = """
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date_created TEXT NOT NULL,
    date_closed TEXT,
    content TEXT NOT NULL,
    category TEXT,
    target_value TEXT,
    source_week TEXT,
    status TEXT DEFAULT '等待中'
)
"""

# ── 里程碑定义 ────────────────────────────────────────────────────
MILESTONES: dict[str, dict] = {
    "萌新出村": {"condition": lambda s: s.get("level", 0) >= 2, "desc": "首次完成 M0+"},
    "蓝分入门": {"condition": lambda s: s.get("vs_benchmark_pct", 0) >= 70, "desc": "vs 清心差距 ≤30%"},
    "紫分进阶": {"condition": lambda s: s.get("vs_benchmark_pct", 0) >= 85, "desc": "vs 清心差距 ≤15%"},
    "橙分法神": {"condition": lambda s: s.get("vs_benchmark_pct", 0) >= 95, "desc": "vs 清心差距 ≤5%"},
}


# ═══════════════════════════════════════════════════════════════════
# 初始化
# ═══════════════════════════════════════════════════════════════════


def init_db(db_path: Path | str | None = None):
    """初始化 progress.db（幂等，已存在则跳过建表）。"""
    if db_path is None:
        db_path = DEFAULT_DB_PATH
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.execute(DDL_SNAPSHOTS)
    conn.execute(DDL_TASKS)
    conn.commit()
    conn.close()


# ═══════════════════════════════════════════════════════════════════
# 快照写入与读取
# ═══════════════════════════════════════════════════════════════════


def write_snapshot(db_path: Path | str, data: dict) -> int:
    """写入一条快照记录，返回自增 id。

    Args:
        data: 须包含 date, report_code, dungeon, level, timed
              可选: dps, vs_benchmark_pct, deaths, interrupts, duration_sec
                    ability_pcts, ability_casts, survival_skills
    """
    db_path = Path(db_path)
    conn = sqlite3.connect(str(db_path))
    cur = conn.execute(
        """INSERT INTO snapshots
           (date, report_code, dungeon, level, timed, dps, vs_benchmark_pct,
            deaths, interrupts, duration_sec, ability_pcts, ability_casts,
            survival_skills, report_path, summary_path)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            data["date"],
            data["report_code"],
            data["dungeon"],
            data["level"],
            data.get("timed", 0),
            data.get("dps"),
            data.get("vs_benchmark_pct"),
            data.get("deaths"),
            data.get("interrupts"),
            data.get("duration_sec"),
            json.dumps(data.get("ability_pcts", {}), ensure_ascii=False),
            json.dumps(data.get("ability_casts", {}), ensure_ascii=False),
            json.dumps(data.get("survival_skills", {}), ensure_ascii=False),
            data.get("report_path", ""),
            data.get("summary_path", ""),
        ),
    )
    conn.commit()
    row_id = cur.lastrowid
    conn.close()
    return row_id


def get_latest(db_path: Path | str | None = None, count: int = 6) -> list[dict]:
    """获取最近 count 条快照（按日期降序）。"""
    if db_path is None:
        db_path = DEFAULT_DB_PATH
    db_path = Path(db_path)

    if not db_path.exists():
        return []

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM snapshots ORDER BY date DESC, id DESC LIMIT ?",
        (count,),
    ).fetchall()
    conn.close()

    results = []
    for row in rows:
        d = dict(row)
        for json_col in ["ability_pcts", "ability_casts", "survival_skills"]:
            if isinstance(d.get(json_col), str):
                d[json_col] = json.loads(d[json_col])
        results.append(d)

    return results


def _extract_metric(row: sqlite3.Row | None, path: str):
    """从快照行中按路径提取指标值。

    如 path='ability_pcts.冰枪术.hits' 表示从 ability_pcts JSON 中取 hits。
    """
    if row is None or not path:
        return None

    parts = path.split(".", 1)
    top_key = parts[0]

    if top_key in row.keys():
        val = row[top_key]
    else:
        return None

    # 字符串类型可能是 JSON，需要反序列化
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
        except (json.JSONDecodeError, TypeError):
            parsed = val
        val = parsed

    if len(parts) == 1:
        return val

    # 递归进入嵌套
    sub_path = parts[1]
    if isinstance(val, dict):
        sub_parts = sub_path.split(".", 1)
        inner = val.get(sub_parts[0])
        if len(sub_parts) == 1:
            return inner
        if isinstance(inner, dict):
            return inner.get(sub_parts[1])
        return None

    return None


# ═══════════════════════════════════════════════════════════════════
# 查询与统计
# ═══════════════════════════════════════════════════════════════════


def get_weekly_diff(db_path: Path | str | None = None) -> dict:
    """比较最近两次快照，返回各指标的变化。"""
    latest = get_latest(db_path, count=2)
    if len(latest) < 2:
        return {}

    this_week = latest[0]
    last_week = latest[1]

    diff = {}
    for key in ["dps", "level", "deaths", "interrupts", "duration_sec", "vs_benchmark_pct"]:
        v_this = this_week.get(key, 0) or 0
        v_last = last_week.get(key, 0) or 0
        diff[f"{key}_change"] = v_this - v_last

    return diff


def check_milestones(snapshot: dict) -> dict[str, bool]:
    """对单个快照判定所有里程碑。"""
    return {name: ms["condition"](snapshot) for name, ms in MILESTONES.items()}


def get_best_ever(db_path: Path | str | None = None, metric: str = "dps") -> dict:
    """查询某指标的历史最佳值。"""
    if db_path is None:
        db_path = DEFAULT_DB_PATH
    db_path = Path(db_path)
    if not db_path.exists():
        return {}

    allowed = {"dps", "level", "vs_benchmark_pct", "interrupts", "deaths"}
    if metric not in allowed:
        raise ValueError(f"不支持的指标: {metric}，仅支持 {allowed}")

    order = "ASC" if metric == "deaths" else "DESC"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        f"SELECT date, {metric} FROM snapshots ORDER BY {metric} {order} LIMIT 1"
    ).fetchone()
    conn.close()

    if row is None:
        return {}

    return {"date": row["date"], "value": row[metric]}


def get_task_completion(db_path: Path | str | None = None) -> dict[str, int]:
    """统计各状态任务数量。"""
    if db_path is None:
        db_path = DEFAULT_DB_PATH
    db_path = Path(db_path)
    if not db_path.exists():
        return {}

    conn = sqlite3.connect(str(db_path))
    rows = conn.execute(
        "SELECT status, COUNT(*) as cnt FROM tasks GROUP BY status"
    ).fetchall()
    conn.close()
    return {row[0]: row[1] for row in rows}


# ═══════════════════════════════════════════════════════════════════
# 任务追踪
# ═══════════════════════════════════════════════════════════════════


def add_task(db_path: Path | str, data: dict) -> int:
    """创建一条改进任务，返回自增 id。"""
    db_path = Path(db_path)
    conn = sqlite3.connect(str(db_path))
    cur = conn.execute(
        """INSERT INTO tasks
           (date_created, date_closed, content, category,
            target_value, source_week, status)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            data.get("date_created", date.today().isoformat()),
            data.get("date_closed"),
            data["content"],
            data.get("category"),
            data.get("target_value"),
            data.get("source_week"),
            data.get("status", "等待中"),
        ),
    )
    conn.commit()
    row_id = cur.lastrowid
    conn.close()
    return row_id


def update_task_status(db_path: Path | str, task_id: int) -> str:
    """根据最新快照自动判定任务状态，返回新状态。

    判定逻辑:
      - 当前值 >= 目标值 → 已达成
      - 当前值 <= 上次值 → 未改善
      - 当前值 > 上次值 → 改善中
      - 无历史数据 → 保持原状态
    """
    db_path = Path(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    task = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if task is None:
        conn.close()
        return ""

    # 获取最新两次快照
    snapshots = conn.execute(
        "SELECT * FROM snapshots ORDER BY date DESC, id DESC LIMIT 2"
    ).fetchall()

    if not snapshots:
        conn.close()
        return task["status"]

    latest = snapshots[0]
    prev = snapshots[1] if len(snapshots) >= 2 else None

    target = json.loads(task["target_value"] or "{}")
    metric_path = target.get("metric", "")
    target_to = target.get("to")

    current_value = _extract_metric(latest, metric_path)

    if target_to is not None and current_value is not None:
        if current_value >= target_to:
            new_status = "已达成"
        elif prev is not None:
            prev_value = _extract_metric(prev, metric_path)
            if prev_value is not None and current_value <= prev_value:
                new_status = "未改善"
            elif prev_value is not None and current_value > prev_value:
                new_status = "改善中"
            else:
                new_status = task["status"]
        else:
            # 只有一条快照，无法判断趋势
            new_status = task["status"]
    else:
        new_status = task["status"]

    conn.execute("UPDATE tasks SET status = ? WHERE id = ?", (new_status, task_id))
    if new_status == "已达成":
        conn.execute(
            "UPDATE tasks SET date_closed = ? WHERE id = ?",
            (date.today().isoformat(), task_id),
        )
    conn.commit()
    conn.close()
    return new_status


# ═══════════════════════════════════════════════════════════════════
# 趋势图
# ═══════════════════════════════════════════════════════════════════


def ascii_trend_chart(
    db_path: Path | str | None = None,
    metric: str = "dps",
    count: int = 6,
) -> str:
    """生成 ASCII 趋势图文本，可直接嵌入报告。"""
    rows = get_latest(db_path, count=count)
    if len(rows) < 2:
        return f"(数据不足，仅有 {len(rows)} 条记录，无法绘制趋势)"

    rows = list(reversed(rows))
    values = [r.get(metric, 0) or 0 for r in rows]
    labels = [r["date"][-5:] for r in rows]

    max_val = max(values)
    min_val = min(values)
    if max_val == min_val:
        max_val += 1

    chart_width = 30
    lines = [f"{metric} 趋势 (最近 {len(rows)} 次):"]
    for label, val in zip(labels, values):
        bar_len = int((val - min_val) / (max_val - min_val) * chart_width)
        bar = "█" * bar_len + "░" * (chart_width - bar_len)
        lines.append(f"  {label}  {bar}  {val:,.0f}")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════


def main():
    import argparse

    parser = argparse.ArgumentParser(description="小雪法神之路进度追踪")
    parser.add_argument("--init", action="store_true", help="初始化数据库")
    parser.add_argument("--latest", type=int, nargs="?", const=6, metavar="N", help="显示最近 N 条快照")
    parser.add_argument("--trend", metavar="METRIC", help="显示指定指标的趋势图")
    parser.add_argument("--trend-count", type=int, default=6, help="趋势图数据点数")
    parser.add_argument("--milestones", action="store_true", help="显示里程碑状态")
    parser.add_argument("--best", metavar="METRIC", help="显示指定指标的历史最佳")
    args = parser.parse_args()

    if args.init:
        init_db()
        print(f"[OK] 数据库已初始化: {DEFAULT_DB_PATH}")
        return

    if args.latest:
        rows = get_latest(count=args.latest)
        if not rows:
            print("暂无快照数据")
            return
        print(f"最近 {len(rows)} 条快照:")
        for r in rows:
            print(f"  {r['date']}  {r['dungeon']} +{r['level']}  "
                  f"DPS={r['dps'] or '-'}  死亡={r['deaths'] or 0}  打断={r['interrupts'] or 0}")
        return

    if args.trend:
        print(ascii_trend_chart(metric=args.trend, count=args.trend_count))
        return

    if args.milestones:
        rows = get_latest(count=1)
        if rows:
            ms = check_milestones(rows[0])
            for name, achieved in ms.items():
                icon = "✅" if achieved else "⬜"
                desc = MILESTONES[name]["desc"]
                print(f"  {icon}  {name}: {desc}")
        else:
            print("⚠️  无快照数据，无法判定里程碑")
        return

    if args.best:
        best = get_best_ever(metric=args.best)
        if best:
            print(f"  {args.best} 历史最佳: {best['value']:,} (日期: {best['date']})")
        else:
            print(f"  暂无 {args.best} 数据")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
