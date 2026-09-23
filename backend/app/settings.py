"""Application settings: every value comes from the environment (or `.env`).

Centralised on purpose - no other module may read ``os.environ`` directly.
There are no secrets in this service; the redaction helpers below exist so that
adding a secret later cannot accidentally leak it into a log line or the
``/api/health`` payload.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

# backend/ -> app/settings.py -> parents[1] == backend/, parents[2] == repo root
BACKEND_DIR: Path = Path(__file__).resolve().parents[1]
REPO_ROOT: Path = BACKEND_DIR.parent

_SECRET_KEY_RE = re.compile(r"(secret|token|password|passwd|api[_-]?key|credential)", re.IGNORECASE)


def _load_dotenv(path: Path) -> dict[str, str]:
    """Minimal ``KEY=value`` reader (stdlib only, no python-dotenv import).

    Real environment variables always win over ``.env`` values; ``export`` is
    not understood, comments and blank lines are skipped.
    """
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return values
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        # strip trailing inline comment (` # ...`) but keep '#' inside a value
        if " #" in value:
            value = value.split(" #", 1)[0].strip()
        if key:
            values[key] = value
    return values


_DOTENV = _load_dotenv(BACKEND_DIR / ".env")


def _raw(key: str, default: str = "") -> str:
    env_value = os.environ.get(key)
    if env_value is not None and env_value != "":
        return env_value
    dotenv_value = _DOTENV.get(key)
    if dotenv_value is not None and dotenv_value != "":
        return dotenv_value
    return default


def _int(key: str, default: int) -> int:
    value = _raw(key, "")
    if value == "":
        return default
    try:
        return int(value, 10)
    except ValueError:
        return default


def _bool(key: str, default: bool) -> bool:
    value = _raw(key, "").strip().lower()
    if value in ("1", "true", "yes", "on"):
        return True
    if value in ("0", "false", "no", "off"):
        return False
    return default


@dataclass(frozen=True)
class Settings:
    """Resolved runtime settings (see ``backend/.env.example`` for the docs)."""

    # --- paths -------------------------------------------------------------
    database_path: Path = field(default_factory=lambda: REPO_ROOT / "data" / "rail_inspection.db")
    parser_config_path: Path = field(default_factory=lambda: BACKEND_DIR / "config" / "parser.yaml")
    # Pre-built React SPA served by FastAPI in production (Pi kiosk). Absent on a
    # dev machine, where Vite serves the frontend instead.
    web_dir: Path = field(default_factory=lambda: REPO_ROOT / "deploy" / "pi" / "web")

    # --- listen address ----------------------------------------------------
    # Loopback by default: the Pi shows the console on its own HDMI output, so
    # there is no reason to expose it to the LAN. RIC_HOST=0.0.0.0 is the
    # documented debug override and does so at the operator's own risk.
    host: str = "127.0.0.1"
    port: int = 8000

    # --- HTTP / CORS -------------------------------------------------------
    app_name: str = "rail-inspection-console-api"
    app_version: str = "0.1.0"
    cors_origins: tuple[str, ...] = ("http://localhost:5173", "http://127.0.0.1:5173")

    # --- serial defaults (used when the request omits the field) -----------
    serial_port: str = "COM7"
    serial_baudrate: int = 115200
    serial_bytesize: int = 8
    serial_parity: str = "N"
    serial_stopbits: float = 1
    serial_flowcontrol: str = "none"

    # --- serial service tuning --------------------------------------------
    serial_read_timeout_s: float = 0.2
    serial_poll_interval_s: float = 0.01
    serial_reader_join_timeout_s: float = 2.0

    # --- websocket / snapshot ---------------------------------------------
    ws_snapshot_size: int = 50
    ws_max_connections: int = 50

    @property
    def db_path_str(self) -> str:
        return str(self.database_path)

    def redacted_dict(self) -> dict[str, object]:
        """Loggable view of the settings (no value that looks secret, none today)."""
        return {
            "app_name": self.app_name,
            "app_version": self.app_version,
            "database_path": self.db_path_str,
            "parser_config_path": str(self.parser_config_path),
            "web_dir": str(self.web_dir),
            "host": self.host,
            "port": self.port,
            "cors_origins": list(self.cors_origins),
            "serial_port": self.serial_port,
            "serial_baudrate": self.serial_baudrate,
            "serial_bytesize": self.serial_bytesize,
            "serial_parity": self.serial_parity,
            "serial_stopbits": self.serial_stopbits,
            "serial_flowcontrol": self.serial_flowcontrol,
        }


def _origins(raw: str) -> tuple[str, ...]:
    parts = [p.strip() for p in raw.replace(";", ",").split(",")]
    cleaned = tuple(p for p in parts if p)
    return cleaned or ("http://localhost:5173", "http://127.0.0.1:5173")


def _stopbits(raw: str) -> float:
    value = raw.strip()
    if value in ("1.5", "1.5,"):
        return 1.5
    if value in ("2",):
        return 2.0
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 1.0
    return parsed if parsed in (1.0, 1.5, 2.0) else 1.0


def load_settings() -> Settings:
    """Build :class:`Settings` from the environment, falling back to defaults."""
    db_raw = _raw("RIC_DATABASE_PATH", "")
    database_path = Path(db_raw).expanduser().resolve() if db_raw else REPO_ROOT / "data" / "rail_inspection.db"

    parser_raw = _raw("RIC_PARSER_CONFIG", "")
    parser_path = Path(parser_raw).expanduser().resolve() if parser_raw else BACKEND_DIR / "config" / "parser.yaml"

    web_raw = _raw("RIC_WEB_DIR", "")
    web_dir = Path(web_raw).expanduser().resolve() if web_raw else REPO_ROOT / "deploy" / "pi" / "web"

    stopbits_raw = _raw("RIC_SERIAL_STOPBITS", "1")

    return Settings(
        database_path=database_path,
        parser_config_path=parser_path,
        web_dir=web_dir,
        host=_raw("RIC_HOST", "127.0.0.1").strip() or "127.0.0.1",
        port=_int("RIC_PORT", 8000),
        app_name=_raw("RIC_APP_NAME", "rail-inspection-console-api"),
        app_version=_raw("RIC_APP_VERSION", "0.1.0"),
        cors_origins=_origins(_raw("RIC_CORS_ORIGINS", "")),
        serial_port=_raw("RIC_SERIAL_PORT", "COM7"),
        serial_baudrate=_int("RIC_SERIAL_BAUDRATE", 115200),
        serial_bytesize=_int("RIC_SERIAL_BYTESIZE", 8),
        serial_parity=(_raw("RIC_SERIAL_PARITY", "N")[:1] or "N").upper(),
        serial_stopbits=_stopbits(stopbits_raw) if stopbits_raw else 1.0,
        serial_flowcontrol=_raw("RIC_SERIAL_FLOWCONTROL", "none").strip().lower() or "none",
        serial_read_timeout_s=float(_int("RIC_SERIAL_READ_TIMEOUT_MS", 200)) / 1000.0,
        ws_snapshot_size=_int("RIC_WS_SNAPSHOT_SIZE", 50),
        ws_max_connections=_int("RIC_WS_MAX_CONNECTIONS", 50),
    )


SETTINGS: Settings = load_settings()


def get_settings() -> Settings:
    return SETTINGS


def override_settings(settings: Settings) -> Settings:
    """Test hook: replace the process-wide settings object."""
    global SETTINGS
    SETTINGS = settings
    return SETTINGS


def is_secret_key(key: str) -> bool:
    """True for env/settings names that must never be logged or serialised."""
    return bool(_SECRET_KEY_RE.search(key))


__all__ = [
    "BACKEND_DIR",
    "REPO_ROOT",
    "Settings",
    "get_settings",
    "load_settings",
    "override_settings",
    "is_secret_key",
]
