"""SQLite persistence package (stdlib ``sqlite3`` only)."""

from __future__ import annotations

from .database import Database, DatabaseUnavailable, get_database, set_database

__all__ = ["Database", "DatabaseUnavailable", "get_database", "set_database"]
