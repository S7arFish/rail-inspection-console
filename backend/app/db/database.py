"""SQLite access with the **stdlib only** (``sqlite3``) - no ORM, no driver.

Responsibilities:
* open the database file (default ``<repo>/data/rail_inspection.db``)
* create the schema (``sessions`` / ``measurements`` / ``raw_lines``)
* enable WAL + foreign keys + busy timeout
* hand out *thread-safe* connections: one connection per thread plus a global
  write lock, because the serial reader thread writes while the ASGI worker
  threads read.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

from ..settings import Settings, get_settings

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

_SCHEMA_SQL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS sessions (
        id           TEXT    PRIMARY KEY,
        started_at   TEXT    NOT NULL,
        ended_at     TEXT    NULL,
        port         TEXT    NOT NULL,
        baud_rate    INTEGER NOT NULL,
        status       TEXT    NOT NULL DEFAULT 'running'
                     CHECK (status IN ('running', 'completed', 'interrupted', 'failed')),
        sample_count INTEGER NOT NULL DEFAULT 0,
        batch_count  INTEGER NOT NULL DEFAULT 0,
        source       TEXT    NOT NULL DEFAULT 'serial',
        note         TEXT    NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS measurements (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT    NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
        ts_raw     TEXT    NULL,
        ts         TEXT    NULL,
        fields     TEXT    NOT NULL DEFAULT '{}',
        raw_line   TEXT    NOT NULL,
        batch_seq  INTEGER NOT NULL DEFAULT 0,
        created_at TEXT    NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS raw_lines (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id  TEXT    NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
        line        TEXT    NOT NULL,
        kind        TEXT    NOT NULL
                    CHECK (kind IN ('data', 'control', 'invalid')),
        parse_error TEXT    NULL,
        created_at  TEXT    NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_measurements_session ON measurements (session_id, id)",
    "CREATE INDEX IF NOT EXISTS idx_measurements_ts ON measurements (ts)",
    "CREATE INDEX IF NOT EXISTS idx_raw_lines_session ON raw_lines (session_id, id)",
    "CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions (started_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS schema_meta (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
)


class DatabaseUnavailable(RuntimeError):
    """Raised when the SQLite file cannot be opened/created at all."""


class Database:
    """Thread-safe stdlib-sqlite3 wrapper (one connection per thread)."""

    def __init__(self, path: str | Path, *, timeout: float = 30.0, expect_dir: bool = True) -> None:
        self.path = Path(path).expanduser()
        self._timeout = timeout
        self._local = threading.local()
        self._write_lock = threading.RLock()
        self._all_connections: list[sqlite3.Connection] = []
        self._connections_guard = threading.Lock()
        self._closed = False
        if expect_dir:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise DatabaseUnavailable(f"cannot create database directory {self.path.parent}: {exc}") from exc

    # ------------------------------------------------------------ connections
    @property
    def connection(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            if self._closed:
                raise DatabaseUnavailable("database handle has been closed")
            conn = self._open_connection()
            self._local.conn = conn
            with self._connections_guard:
                self._all_connections.append(conn)
        return conn

    def _open_connection(self) -> sqlite3.Connection:
        try:
            conn = sqlite3.connect(
                str(self.path),
                timeout=self._timeout,
                isolation_level=None,  # explicit BEGIN/COMMIT via `transaction()`
                check_same_thread=False,
            )
        except sqlite3.Error as exc:
            raise DatabaseUnavailable(f"cannot open database {self.path}: {exc}") from exc
        conn.row_factory = sqlite3.Row
        pragmas = (
            "PRAGMA foreign_keys = ON",
            "PRAGMA journal_mode = WAL",
            "PRAGMA synchronous = NORMAL",
            f"PRAGMA busy_timeout = {int(self._timeout * 1000)}",
        )
        for pragma in pragmas:
            try:
                conn.execute(pragma)
            except sqlite3.Error:  # pragma: no cover - journal_mode can be refused
                logger.warning("failed to apply %r on %s", pragma, self.path, exc_info=True)
        return conn

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Serialize writes: ``BEGIN IMMEDIATE`` ... ``COMMIT`` / ``ROLLBACK``."""
        conn = self.connection
        with self._write_lock:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:  # pragma: no cover
                    logger.exception("rollback failed on %s", self.path)
                raise
            else:
                conn.execute("COMMIT")

    # ------------------------------------------------------------- primitives
    def execute(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> sqlite3.Cursor:
        with self._write_lock:
            return self.connection.execute(sql, params)

    def executemany(self, sql: str, rows: Iterable[Sequence[Any]]) -> sqlite3.Cursor:
        with self._write_lock:
            return self.connection.executemany(sql, list(rows))

    def query(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> list[sqlite3.Row]:
        return list(self.connection.execute(sql, params).fetchall())

    def query_one(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> sqlite3.Row | None:
        return self.connection.execute(sql, params).fetchone()

    def scalar(self, sql: str, params: Sequence[Any] | dict[str, Any] = (), default: Any = None) -> Any:
        row = self.query_one(sql, params)
        if row is None:
            return default
        return row[0]

    # ------------------------------------------------------------- lifecycle
    def init_schema(self) -> None:
        with self.transaction() as conn:
            for statement in _SCHEMA_SQL:
                conn.execute(statement)
            conn.execute(
                "INSERT INTO schema_meta (key, value) VALUES ('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(SCHEMA_VERSION),),
            )
        logger.info("sqlite schema ready at %s (version %s)", self.path, SCHEMA_VERSION)

    def integrity_check(self) -> str:
        return str(self.scalar("PRAGMA integrity_check", default="unknown"))

    def close(self) -> None:
        self._closed = True
        with self._connections_guard:
            connections = list(self._all_connections)
            self._all_connections.clear()
        for conn in connections:
            try:
                conn.close()
            except sqlite3.Error:  # pragma: no cover
                logger.debug("closing a sqlite connection failed", exc_info=True)
        self._local = threading.local()

    def __repr__(self) -> str:  # pragma: no cover - logging helper
        return f"<Database path={str(self.path)!r}>"


def database_from_settings(settings: Settings | None = None) -> Database:
    settings = settings or get_settings()
    return Database(settings.database_path)


# --------------------------------------------------------------------------
# Process-wide handle, created lazily so `import app.main` never touches disk
# in a way that could fail (the lifespan calls `init_database()`).
# --------------------------------------------------------------------------
_shared: Database | None = None
_shared_lock = threading.Lock()


def get_database(settings: Settings | None = None) -> Database:
    """Lazily build the process-wide :class:`Database` (only a mkdir on first use)."""
    global _shared
    if _shared is not None:
        return _shared
    with _shared_lock:
        if _shared is None:
            _shared = database_from_settings(settings)
    return _shared


def set_database(database: "Database | None") -> None:
    """Lifespan/test hook: install (or clear) the shared handle."""
    global _shared
    with _shared_lock:
        _shared = database


__all__ = [
    "Database",
    "DatabaseUnavailable",
    "SCHEMA_VERSION",
    "database_from_settings",
    "get_database",
    "set_database",
]
