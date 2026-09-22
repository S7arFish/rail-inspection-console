#!/usr/bin/env python3
"""只读查看 RIC Console 的 SQLite 数据，用于真机测试时核对批次是否落库。

不写入、不建表、不修改任何数据：数据库以 `mode=ro` 打开，即使误操作也不可能改动文件。
只用标准库，不需要额外安装任何东西。

用法：
    backend\\.venv\\Scripts\\python.exe scripts\\inspect-db.py
    backend\\.venv\\Scripts\\python.exe scripts\\inspect-db.py --limit 10
    backend\\.venv\\Scripts\\python.exe scripts\\inspect-db.py --session SES-xxxx --samples 5
    backend\\.venv\\Scripts\\python.exe scripts\\inspect-db.py --db D:\\other\\rail_inspection.db
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path
from typing import NoReturn

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO_ROOT / "data" / "rail_inspection.db"


def fail(message: str) -> NoReturn:
    print(f"[错误] {message}")
    raise SystemExit(1)


def open_read_only(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        fail(
            f"数据库文件不存在：{path}\n"
            "       后端首次启动时才会创建它。请先运行 scripts\\dev.bat，"
            "再在系统设置里建立链路并完成一次导出。"
        )
    try:
        conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    except sqlite3.Error as exc:
        fail(f"无法以只读方式打开数据库：{exc}")
    conn.row_factory = sqlite3.Row
    return conn


def show_sessions(conn: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    rows = conn.execute(
        "SELECT id, started_at, ended_at, port, baud_rate, status,"
        " sample_count, batch_count, note FROM sessions"
        " ORDER BY started_at DESC, id DESC LIMIT ?",
        (limit,),
    ).fetchall()

    print("=" * 78)
    print(f"最近 {len(rows)} 个批次会话（一次“导出记录” = 一个 session）")
    print("=" * 78)
    if not rows:
        print("（还没有任何会话。建立链路本身不会创建会话，"
              "需要 DHJ-9 真正导出至少一条记录。）")
        return []

    print(f"{'会话号':<26} {'状态':<12} {'记录数':>6} {'结束时间':<21} 串口")
    print("-" * 78)
    for row in rows:
        ended = row["ended_at"] or "—（进行中）"
        print(
            f"{row['id']:<26} {row['status']:<12} {row['sample_count']:>6} "
            f"{ended:<21} {row['port']}@{row['baud_rate']}"
        )
    return rows


def show_samples(conn: sqlite3.Connection, session_id: str, count: int) -> None:
    print()
    print("=" * 78)
    print(f"会话 {session_id} 的最近 {count} 条记录")
    print("=" * 78)

    total = conn.execute(
        "SELECT COUNT(*) FROM measurements WHERE session_id = ?", (session_id,)
    ).fetchone()[0]
    raw_total = conn.execute(
        "SELECT COUNT(*) FROM raw_lines WHERE session_id = ?", (session_id,)
    ).fetchone()[0]
    kinds = conn.execute(
        "SELECT kind, COUNT(*) AS n FROM raw_lines WHERE session_id = ? GROUP BY kind",
        (session_id,),
    ).fetchall()
    kind_summary = "、".join(f"{r['kind']}={r['n']}" for r in kinds) or "无"
    print(f"measurements 行数：{total}    raw_lines 行数：{raw_total}")
    print(f"原始行分类：{kind_summary}")

    rows = conn.execute(
        "SELECT id, ts_raw, ts, fields, raw_line FROM measurements"
        " WHERE session_id = ? ORDER BY id DESC LIMIT ?",
        (session_id, count),
    ).fetchall()
    if not rows:
        print("（该会话没有解析成功的记录）")
        return

    for row in rows:
        print("-" * 78)
        print(f"#{row['id']}  原始时间={row['ts_raw']}  解析时间={row['ts'] or '解析失败'}")
        print(f"  原始行: {row['raw_line']}")
        print(f"  解析值: {row['fields']}")

    errors = conn.execute(
        "SELECT line, parse_error FROM raw_lines"
        " WHERE session_id = ? AND kind = 'invalid' ORDER BY id DESC LIMIT 5",
        (session_id,),
    ).fetchall()
    if errors:
        print("-" * 78)
        print("该会话内解析失败的原始行（最多 5 条，仅供排查）：")
        for row in errors:
            print(f"  {row['line']!r} -> {row['parse_error']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="只读查看 RIC Console 的 SQLite 批次数据（不修改数据库）"
    )
    parser.add_argument("--db", default=os.environ.get("RIC_DATABASE_PATH") or str(DEFAULT_DB),
                        help=f"数据库路径，默认 {DEFAULT_DB}")
    parser.add_argument("--limit", type=int, default=8, help="列出最近多少个会话（默认 8）")
    parser.add_argument("--session", default=None, help="查看指定会话的记录（默认取最近一个）")
    parser.add_argument("--samples", type=int, default=5, help="显示该会话最近几条记录（默认 5）")
    args = parser.parse_args(argv)

    db_path = Path(args.db).expanduser().resolve()
    conn = open_read_only(db_path)
    try:
        print(f"数据库（只读）：{db_path}")
        rows = show_sessions(conn, max(1, args.limit))
        target = args.session or (rows[0]["id"] if rows else None)
        if target:
            show_samples(conn, target, max(1, args.samples))
    except sqlite3.Error as exc:
        fail(f"查询失败：{exc}")
    finally:
        conn.close()

    print()
    print("说明：状态 completed 表示该批次已收到 OVER 并正常收尾；"
          "running 表示仍在接收；interrupted 表示断开时批次未结束。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
