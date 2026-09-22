"""Shared fixtures: a real parser config, a throwaway SQLite file, a service
wired to a fake port and an envelope recorder.

Everything here runs without hardware: `connect()` opens :class:`FakeSerial`, and
the tests then drive the documented `ingest_line()` path so the assertions are
deterministic instead of racing the reader thread's poll interval.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:  # pytest.ini sets pythonpath too
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db.database import Database  # noqa: E402
from app.parser.line_parser import LineParser, ParserConfig  # noqa: E402
from app.services.realtime import EventBridge  # noqa: E402
from app.services.serial_service import SerialService  # noqa: E402
from app.settings import get_settings  # noqa: E402

PARSER_YAML = BACKEND_ROOT / "config" / "parser.yaml"

# The six real records the DHJ-9 produced, exactly as they came off the wire.
REAL_BATCH = [
    "0,0,0,0,0,1,1,260922-091952,2121.5,582.2,1434.6,-9.8",
    "0,0,0,0,0,1,3,260922-092112,2126.4,581.7,1432.4,7.6",
    "0,0,0,0,0,1,4,260923-065404,2132.0,1599.8,1432.4,6.6",
    "0,0,0,0,0,1,5,260923-072226,2122.3,135.9,1435.5,8.7",
    "0,0,0,0,0,1,6,260923-072346,2120.3,136.1,1435.7,6.9",
    "0,0,0,0,0,1,7,260923-083528,2123.2,95.2,1432.4,7.7",
    "OVER",
]

INSTRUMENT_HEADER = "记录类型,测量方向,记录号,线号,工区,杆号,测量位置,时间,高度,拉出,轨距"


class FakeSerial:
    """Stands in for `serial.Serial`: openable, closable, permanently idle."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.closed = False
        self.port = kwargs.get("port")

    @property
    def in_waiting(self) -> int:
        return 0

    def readline(self) -> bytes:
        return b""

    def close(self) -> None:
        self.closed = True


@pytest.fixture()
def config() -> ParserConfig:
    """The SHIPPED parser.yaml, so the tests guard the real config file."""
    return ParserConfig.from_yaml(PARSER_YAML)


@pytest.fixture()
def parser(config: ParserConfig) -> LineParser:
    return LineParser(config)


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "test-rail.db")
    database.init_schema()
    try:
        yield database
    finally:
        database.close()


@pytest.fixture()
def envelopes() -> list[dict]:
    return []


@pytest.fixture()
def app_settings():
    """The process settings (ports/paths come from .env, defaults otherwise)."""
    return get_settings()


@pytest.fixture()
def bridge(envelopes: list[dict]) -> EventBridge:
    """A bridge whose "broadcast" just records the envelope."""

    def publisher(envelope: dict) -> int:
        envelopes.append(envelope)
        return 1

    return EventBridge(publisher=publisher)


@pytest.fixture()
def service(db, parser, bridge) -> SerialService:
    """Service with a fake port, a recording bridge and a settings override."""
    settings = get_settings()
    return SerialService(
        settings=settings,
        database=db,
        parser=parser,
        bridge=bridge,
        serial_factory=lambda **kwargs: FakeSerial(**kwargs),
        port_lister=lambda: [],
    )


@pytest.fixture()
def connected(service: SerialService) -> SerialService:
    """A service with the link already open, waiting for an export."""
    result = service.connect()
    assert result.ok, result.message
    return service
