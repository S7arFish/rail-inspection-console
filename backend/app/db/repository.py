"""Persistence + query layer for the three SQLite tables.

Pure stdlib/sqlite + data structures: **no FastAPI, no pydantic, no service
imports** in here, so it stays usable from the serial reader thread, from tests
and from any future CLI.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .database import Database

logger = logging.getLogger(__name__)

# sessions.status
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_INTERRUPTED = "interrupted"
STATUS_FAILED = "failed"
SESSION_STATUSES = (STATUS_RUNNING, STATUS_COMPLETED, STATUS_INTERRUPTED, STATUS_FAILED)

# raw_lines.kind
KIND_DATA = "data"
KIND_CONTROL = "control"
KIND_INVALID = "invalid"
RAW_LINE_KINDS = (KIND_DATA, KIND_CONTROL, KIND_INVALID)

SOURCE_SERIAL = "serial"


def utc_now_iso() -> str:
    """Wall-clock timestamp used for `created_at` / envelope `ts` (UTC, ms)."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def new_session_id(now: datetime | None = None) -> str:
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%S")
    return f"SES-{stamp}-{uuid.uuid4().hex[:8]}"


# --------------------------------------------------------------------------- #
# row mappers
# --------------------------------------------------------------------------- #
def row_to_session(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row["id"],
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
        "port": row["port"],
        "baud_rate": row["baud_rate"],
        "status": row["status"],
        "sample_count": int(row["sample_count"] or 0),
        "batch_count": int(row["batch_count"] or 0),
        "source": row["source"],
        "note": row["note"],
    }


def row_to_measurement(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    raw_fields = row["fields"]
    try:
        fields = json.loads(raw_fields) if raw_fields else {}
        if not isinstance(fields, dict):
            fields = {"_unparsed": fields}
    except (TypeError, ValueError):
        # Never lose data because of a bad JSON blob.
        fields = {"_json_error": str(raw_fields)[:2000]}
    return {
        "id": int(row["id"]),
        "session_id": row["session_id"],
        "ts_raw": row["ts_raw"],
        "ts": row["ts"],
        "fields": fields,
        "raw_line": row["raw_line"],
        "batch_seq": int(row["batch_seq"] or 0),
        "created_at": row["created_at"],
    }


def row_to_raw_line(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": int(row["id"]),
        "session_id": row["session_id"],
        "line": row["line"],
        "kind": row["kind"],
        "parse_error": row["parse_error"],
        "created_at": row["created_at"],
    }


# --------------------------------------------------------------------------- #
# sessions
# --------------------------------------------------------------------------- #
def create_session(
    db: Database,
    *,
    port: str,
    baud_rate: int,
    note: str | None = None,
    source: str = SOURCE_SERIAL,
    session_id: str | None = None,
    started_at: str | None = None,
    status: str = STATUS_RUNNING,
) -> dict[str, Any]:
    if status not in SESSION_STATUSES:
        raise ValueError(f"unknown session status {status!r}")
    session_id = session_id or new_session_id()
    started_at = started_at or utc_now_iso()
    db.execute(
        "INSERT INTO sessions (id, started_at, ended_at, port, baud_rate, status,"
        " sample_count, batch_count, source, note) VALUES (?, ?, NULL, ?, ?, ?, 0, 0, ?, ?)",
        (session_id, started_at, port, int(baud_rate), status, source, note),
    )
    session = get_session(db, session_id)
    assert session is not None  # just inserted
    return session


def get_session(db: Database, session_id: str) -> dict[str, Any] | None:
    return row_to_session(db.query_one("SELECT * FROM sessions WHERE id = ?", (session_id,)))


def set_session_counters(
    db: Database,
    session_id: str,
    *,
    sample_count: int | None = None,
    batch_count: int | None = None,
) -> None:
    sets: list[str] = []
    params: list[Any] = []
    if sample_count is not None:
        sets.append("sample_count = ?")
        params.append(int(sample_count))
    if batch_count is not None:
        sets.append("batch_count = ?")
        params.append(int(batch_count))
    if not sets:
        return
    params.append(session_id)
    db.execute(f"UPDATE sessions SET {', '.join(sets)} WHERE id = ?", params)


def finalize_session(
    db: Database,
    session_id: str,
    *,
    status: str,
    ended_at: str | None = None,
    note: str | None = None,
) -> dict[str, Any] | None:
    """Close a session; a session that is already closed is left untouched."""
    if status not in SESSION_STATUSES:
        raise ValueError(f"unknown session status {status!r}")
    existing = get_session(db, session_id)
    if existing is None:
        logger.warning("finalize_session: unknown session %s", session_id)
        return None
    if existing["ended_at"] is not None:
        return existing
    params: list[Any] = [status, ended_at or utc_now_iso(), session_id]
    sql = "UPDATE sessions SET status = ?, ended_at = ? WHERE id = ?"
    if note is not None and existing["note"] is None:
        sql = "UPDATE sessions SET status = ?, ended_at = ?, note = ? WHERE id = ?"
        params = [status, ended_at or utc_now_iso(), note, session_id]
    db.execute(sql, params)
    return get_session(db, session_id)


def count_running_sessions(db: Database) -> int:
    return int(db.scalar("SELECT COUNT(*) FROM sessions WHERE status = 'running'", default=0) or 0)


def list_sessions(db: Database, *, limit: int = 50, offset: int = 0) -> tuple[list[dict[str, Any]], int]:
    total = int(db.scalar("SELECT COUNT(*) FROM sessions", default=0) or 0)
    rows = db.query(
        "SELECT * FROM sessions ORDER BY started_at DESC, id DESC LIMIT ? OFFSET ?",
        (int(limit), int(offset)),
    )
    return [row_to_session(r) for r in rows if r is not None], total  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# batch write path (single transaction)
# --------------------------------------------------------------------------- #
def flush_batch(
    db: Database,
    *,
    session_id: str,
    measurements: Sequence[Mapping[str, Any]] = (),
    raw_lines: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Persist one batch atomically: every raw line + every parsed measurement.

    ``batch_seq`` is derived inside the transaction (per session, 1-based) so the
    rows written now and the session counters stay consistent even if two flushes
    race. Returns ``{batch_seq, measurement_count, raw_line_count, sample_count,
    batch_count, measurement_ids}``.
    """
    created_ids: list[int] = []
    batch_seq = 0
    counters: dict[str, int] = {"sample_count": 0, "batch_count": 0}

    with db.transaction() as conn:
        batch_seq = int(conn.execute(
            "SELECT COALESCE(MAX(batch_seq), 0) + 1 FROM measurements WHERE session_id = ?",
            (session_id,),
        ).fetchone()[0])

        raw_rows: list[tuple[Any, ...]] = []
        for entry in raw_lines:
            line = entry.get("line")
            if line is None or line == "":
                continue
            kind = str(entry.get("kind") or KIND_INVALID)
            if kind not in RAW_LINE_KINDS:
                logger.warning("unknown raw line kind %r -> storing as 'invalid'", kind)
                kind = KIND_INVALID
            raw_rows.append((session_id, str(line), kind, entry.get("parse_error"), utc_now_iso()))
        if raw_rows:
            conn.executemany(
                "INSERT INTO raw_lines (session_id, line, kind, parse_error, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                raw_rows,
            )

        for entry in measurements:
            fields = entry.get("fields") or {}
            if not isinstance(fields, (str, Mapping)):
                fields = {"_repr": str(fields)}
            fields_json = fields if isinstance(fields, str) else json.dumps(fields, ensure_ascii=False, default=str)
            cursor = conn.execute(
                "INSERT INTO measurements (session_id, ts_raw, ts, fields, raw_line, batch_seq, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    session_id,
                    entry.get("ts_raw"),
                    entry.get("ts"),
                    fields_json,
                    str(entry.get("raw_line") or ""),
                    batch_seq,
                    utc_now_iso(),
                ),
            )
            if cursor.lastrowid is not None:
                created_ids.append(int(cursor.lastrowid))

        conn.execute(
            "UPDATE sessions SET sample_count = sample_count + ?, batch_count = batch_count + ? WHERE id = ?",
            (len(created_ids), 1 if measurements else 0, session_id),
        )
        row = conn.execute("SELECT sample_count, batch_count FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if row is not None:
            counters["sample_count"] = int(row["sample_count"] or 0)
            counters["batch_count"] = int(row["batch_count"] or 0)

    return {
        "batch_seq": batch_seq,
        "measurement_count": len(created_ids),
        "raw_line_count": len(raw_lines),
        "measurement_ids": created_ids,
        **counters,
    }


def append_raw_line(
    db: Database,
    *,
    session_id: str,
    line: str,
    kind: str,
    parse_error: str | None = None,
) -> int | None:
    """Immediate single-line archive (used only outside the batch path)."""
    if line == "":
        return None
    if kind not in RAW_LINE_KINDS:
        kind = KIND_INVALID
    cursor = db.execute(
        "INSERT INTO raw_lines (session_id, line, kind, parse_error, created_at) VALUES (?, ?, ?, ?, ?)",
        (session_id, line, kind, parse_error, utc_now_iso()),
    )
    return None if cursor.lastrowid is None else int(cursor.lastrowid)


# --------------------------------------------------------------------------- #
# measurements / raw_lines queries
# --------------------------------------------------------------------------- #
def get_measurement(db: Database, measurement_id: int) -> dict[str, Any] | None:
    return row_to_measurement(db.query_one("SELECT * FROM measurements WHERE id = ?", (int(measurement_id),)))


def count_measurements(db: Database, session_id: str) -> int:
    return int(db.scalar("SELECT COUNT(*) FROM measurements WHERE session_id = ?", (session_id,), default=0) or 0)


def list_measurements(
    db: Database,
    session_id: str,
    *,
    limit: int = 500,
    offset: int = 0,
    order: str = "asc",
) -> list[dict[str, Any]]:
    direction = "DESC" if str(order).lower() in ("desc", "descending") else "ASC"
    rows = db.query(
        f"SELECT * FROM measurements WHERE session_id = ? ORDER BY id {direction} LIMIT ? OFFSET ?",
        (session_id, int(limit), int(offset)),
    )
    return [row_to_measurement(r) for r in rows if r is not None]  # type: ignore[misc]


def latest_measurement(db: Database, session_id: str) -> dict[str, Any] | None:
    return row_to_measurement(
        db.query_one("SELECT * FROM measurements WHERE session_id = ? ORDER BY id DESC LIMIT 1", (session_id,))
    )


def recent_measurements(db: Database, *, limit: int = 50, session_id: str | None = None) -> list[dict[str, Any]]:
    """Newest rows across all sessions (or one session) for the WS snapshot."""
    count = max(0, int(limit))
    if count == 0:
        return []
    if session_id:
        rows = db.query(
            "SELECT * FROM measurements WHERE session_id = ? ORDER BY id DESC LIMIT ?", (session_id, count)
        )
    else:
        rows = db.query("SELECT * FROM measurements ORDER BY id DESC LIMIT ?", (count,))
    measurements = [row_to_measurement(r) for r in rows if r is not None]
    measurements.reverse()  # oldest -> newest, so the UI can append in order
    return measurements  # type: ignore[return-value]


def list_raw_lines(
    db: Database,
    session_id: str,
    *,
    limit: int = 200,
    offset: int = 0,
    kind: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    where = "session_id = ?"
    params: list[Any] = [session_id]
    if kind:
        where += " AND kind = ?"
        params.append(kind)
    total = int(db.scalar(f"SELECT COUNT(*) FROM raw_lines WHERE {where}", params, default=0) or 0)
    rows = db.query(
        f"SELECT * FROM raw_lines WHERE {where} ORDER BY id ASC LIMIT ? OFFSET ?",
        [*params, int(limit), int(offset)],
    )
    return [row_to_raw_line(r) for r in rows if r is not None], total  # type: ignore[misc]


def count_raw_lines(db: Database, session_id: str, *, kind: str | None = None) -> int:
    sql = "SELECT COUNT(*) FROM raw_lines WHERE session_id = ?"
    params: list[Any] = [session_id]
    if kind:
        sql += " AND kind = ?"
        params.append(kind)
    return int(db.scalar(sql, params, default=0) or 0)


__all__ = [
    "KIND_CONTROL",
    "KIND_DATA",
    "KIND_INVALID",
    "RAW_LINE_KINDS",
    "SESSION_STATUSES",
    "SOURCE_SERIAL",
    "STATUS_COMPLETED",
    "STATUS_FAILED",
    "STATUS_INTERRUPTED",
    "STATUS_RUNNING",
    "append_raw_line",
    "count_measurements",
    "count_raw_lines",
    "count_running_sessions",
    "create_session",
    "finalize_session",
    "flush_batch",
    "get_measurement",
    "get_session",
    "latest_measurement",
    "list_measurements",
    "list_raw_lines",
    "list_sessions",
    "new_session_id",
    "recent_measurements",
    "row_to_measurement",
    "row_to_raw_line",
    "row_to_session",
    "set_session_counters",
    "utc_now_iso",
]
