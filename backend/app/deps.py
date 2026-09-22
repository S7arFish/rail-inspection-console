"""Dependency wiring: one construction point, thin routes everywhere else.

``create_app()`` builds a :class:`Container` and stores it on ``app.state``;
routes receive pieces of it through the ``Annotated`` dependencies below. Because
the container is built at import time, ``TestClient`` and unit tests can use the
app without running the lifespan (no hardware, no DB file needed until a query
actually touches SQLite).
"""

from __future__ import annotations

import functools
import logging
from dataclasses import dataclass
from typing import Any, Callable, TypeVar

from fastapi import HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from .db.database import Database, DatabaseUnavailable
from .parser.line_parser import LineParser, ParserConfig, ParserConfigError
from .services.realtime import ConnectionManager, EventBridge
from .services.serial_service import SerialService
from .settings import Settings, get_settings

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class Container:
    settings: Settings
    database: Database
    parser: LineParser
    manager: ConnectionManager
    bridge: EventBridge
    serial: SerialService


def build_container(settings: Settings | None = None) -> Container:
    """Wire settings -> db -> parser -> realtime -> serial service."""
    settings = settings or get_settings()
    database = Database(settings.database_path)

    try:
        config = ParserConfig.from_yaml(settings.parser_config_path)
    except ParserConfigError as exc:
        # The console must still boot (and report health) with a broken config.
        logger.error("parser config unusable (%s); falling back to the built-in defaults", exc)
        config = ParserConfig.default()
    parser = LineParser(config)

    manager = ConnectionManager(max_connections=settings.ws_max_connections)
    bridge = EventBridge(manager=manager)
    serial = SerialService(settings=settings, database=database, parser=parser, bridge=bridge)

    return Container(
        settings=settings,
        database=database,
        parser=parser,
        manager=manager,
        bridge=bridge,
        serial=serial,
    )


# --------------------------------------------------------------------------- #
# FastAPI dependencies
# --------------------------------------------------------------------------- #
def _container(request: Request) -> Container:
    container: Container | None = getattr(request.app.state, "container", None)
    if container is None:  # pragma: no cover - would mean a broken app factory
        raise HTTPException(status_code=503, detail="application services are not initialised")
    return container


async def get_container(request: Request) -> Container:
    return _container(request)


async def get_settings_dep(request: Request) -> Settings:
    return _container(request).settings


async def get_database_dep(request: Request) -> Database:
    return _container(request).database


async def get_parser_dep(request: Request) -> LineParser:
    return _container(request).parser


async def get_serial_service_dep(request: Request) -> SerialService:
    return _container(request).serial


async def get_manager_dep(request: Request) -> ConnectionManager:
    return _container(request).manager


async def to_thread(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Run a blocking (sqlite3 / pyserial) call in a worker thread.

    Keeps the event loop free for WebSocket traffic; SQLite access is threaded
    through :class:`app.db.database.Database`'s per-thread connections.
    """
    return await run_in_threadpool(functools.partial(fn, *args, **kwargs))


def get_container_from_app(app: Any) -> Container | None:
    return getattr(app.state, "container", None)


__all__ = [
    "Container",
    "DatabaseUnavailable",
    "build_container",
    "get_container",
    "get_database_dep",
    "get_manager_dep",
    "get_parser_dep",
    "get_serial_service_dep",
    "get_settings_dep",
    "to_thread",
]
