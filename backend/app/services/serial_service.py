"""``SerialService`` - the single owner of *all* serial-port logic.

Nothing in this module knows about FastAPI: it takes a
:class:`~app.settings.Settings`, a :class:`~app.db.database.Database`, a
:class:`~app.parser.line_parser.LineParser` and an
:class:`~app.services.realtime.EventBridge`, and returns plain dataclasses.
API routes only validate input and forward it here.

Key properties
--------------
* Reading happens in a **daemon thread**; the event loop is never blocked and the
  thread never touches asyncio directly.
* A deliberate state machine: ``disconnected -> connecting -> connected_waiting``
  (port open, nothing exported yet) ``-> receiving`` (a batch is arriving)
  ``-> batch_complete`` (transient, on ``OVER``) ``-> connected_waiting``.
  Problems land in ``error`` / ``disconnected``. ``connect()`` is idempotent and
  concurrent attempts are rejected instead of spawning a second reader thread.
* Auto-reconnect is intentionally **not** implemented in this phase (see the
  ``TODO(reconnect)`` marker below).
* **One exported batch is one session.** ``OVER`` closes the session and the
  batch; the serial port stays open for the next 导出记录.
* Parsed data is buffered until the batch ends, then written in one SQLite
  transaction followed by one ``session.complete`` event.
* Testability: ``serial_factory`` lets a fake port be injected, and
  :meth:`SerialService.ingest_lines` runs the exact same parse/persist path
  synchronously without any thread or hardware.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Callable, Iterable, Sequence

from ..db import repository
from ..db.database import Database
from ..parser.line_parser import (
    KIND_CONTROL,
    KIND_DATA,
    KIND_HEADER,
    KIND_INVALID,
    LineParser,
    LineSchemaError,
    ParsedLine,
)
from ..settings import Settings, get_settings
from .realtime import (
    EV_MEASUREMENT,
    EV_PARSE_ERROR,
    EV_SESSION_COMPLETE,
    EV_STATUS,
    EventBridge,
)

logger = logging.getLogger(__name__)

# TODO(reconnect): automatic reconnection is deliberately out of scope for this
# scaffolding phase. On an I/O error the service parks in `error` with
# `last_error` filled and waits for an explicit POST /api/serial/connect.
# A later phase should add: backoff schedule + a supervised reconnect thread.


class SerialState(str, Enum):
    """DHJ-9 link states.

    The instrument is not a continuous source: the operator presses 导出记录, the
    device dumps one batch and ends it with ``OVER``. So "connected" is really
    *waiting for an export*, and one batch is one session.
    """

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    # port open, no batch in progress
    CONNECTED_WAITING = "connected_waiting"
    # at least one header/data line of the current batch received
    RECEIVING = "receiving"
    # transient: emitted on OVER, immediately followed by CONNECTED_WAITING
    BATCH_COMPLETE = "batch_complete"
    ERROR = "error"


# States in which the port is open and usable.
LINK_UP_STATES = (
    SerialState.CONNECTED_WAITING,
    SerialState.RECEIVING,
    SerialState.BATCH_COMPLETE,
)

# ports we would pick first (CP210x / Silicon Labs USB-UART bridge)
PREFERRED_PORT_MARKERS = ("cp210x", "silicon labs")


def _connect_failure_message(port: str, exc: BaseException) -> str:
    """Turn a pyserial/OS failure into an operator-readable Chinese message.

    The usual real-world cause is SSCOM (or any other terminal) still holding the
    COM port, so that case gets its own sentence instead of a raw traceback.
    """
    detail = str(exc)
    lowered = detail.lower()
    busy = (
        isinstance(exc, PermissionError)
        or "permission" in lowered
        or "access is denied" in lowered
        or "拒绝访问" in detail
        or "busy" in lowered
        or "正在使用" in detail
    )
    if busy:
        return f"串口 {port} 正被其他程序占用（例如 SSCOM），请先关闭该程序再连接"
    missing = (
        isinstance(exc, FileNotFoundError)
        or "file not found" in lowered
        or "找不到" in detail
        or "invalid com port" in lowered
    )
    if missing:
        return f"串口 {port} 不存在，请检查设备管理器中的端口号（DHJ-9 通常为 CP210x 虚拟端口）"
    return f"无法打开串口 {port}：{detail}"


@dataclass(frozen=True)
class ConnectOptions:
    """Normalised connect input. ``None`` means "use the settings default"."""

    port: str | None = None
    baud_rate: int | None = None
    data_bits: int | None = None
    parity: str | None = None
    stop_bits: float | None = None
    flow_control: str | None = None
    session_note: str | None = None


@dataclass(frozen=True)
class LinkConfig:
    port: str
    baud_rate: int
    data_bits: int
    parity: str
    stop_bits: float
    flow_control: str = "none"

    def serial_kwargs(self) -> dict[str, Any]:
        """Translate ``flow_control`` into pyserial keyword arguments."""
        mode = (self.flow_control or "none").strip().lower()
        kwargs: dict[str, Any] = {
            "port": self.port,
            "baudrate": self.baud_rate,
            "bytesize": self.data_bits,
            "parity": self.parity,
            "stopbits": self.stop_bits,
        }
        if mode in ("hardware", "rtscts", "rts_cts"):
            kwargs["rtscts"] = True
        elif mode in ("software", "xonxoff", "xon_any"):
            kwargs["xonxoff"] = True
        elif mode in ("rs485",):
            kwargs["rs485_mode"] = None  # pyserial default RS485 config
        elif mode not in ("none", "", "none,"):
            raise ValueError(f"unsupported flow control {self.flow_control!r}")
        return kwargs


@dataclass(frozen=True)
class PortInfo:
    device: str
    name: str
    description: str
    hwid: str
    preferred: bool
    active: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PortsView:
    ports: tuple[PortInfo, ...]
    suggested_port: str | None
    error: str | None = None


@dataclass(frozen=True)
class ConnectResult:
    ok: bool
    session_id: str | None
    state: str
    port: str
    baud_rate: int
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DisconnectResult:
    ok: bool
    state: str
    session_id: str | None
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _is_preferred(description: str, hwid: str) -> bool:
    haystack = f"{description} {hwid}".lower()
    return any(marker in haystack for marker in PREFERRED_PORT_MARKERS)


def _default_serial_factory(**kwargs: Any) -> Any:
    """Real port opener - imported lazily so the module loads without pyserial."""
    import serial  # noqa: PLC0415 - deliberate lazy import (hardware-free imports)

    timeout = kwargs.pop("timeout", 0.2)
    return serial.Serial(timeout=timeout, **kwargs)


def _default_port_lister() -> list[Any]:
    from serial.tools import list_ports  # noqa: PLC0415 - lazy: keeps imports safe

    return list(list_ports.comports())


class SerialService:
    """Owns the port, the reader thread, the batch buffer and the DB writes."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        database: Database,
        parser: LineParser,
        bridge: EventBridge | None = None,
        serial_factory: Callable[..., Any] | None = None,
        port_lister: Callable[[], Sequence[Any]] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.db = database
        self.parser = parser
        self.bridge = bridge
        self._serial_factory = serial_factory or _default_serial_factory
        self._port_lister = port_lister or _default_port_lister

        self._lock = threading.RLock()
        self._state: SerialState = SerialState.DISCONNECTED
        self._serial: Any | None = None
        self._thread: threading.Thread | None = None
        self._stop_event: threading.Event | None = None
        self._link: LinkConfig = self._default_link()

        self._session_id: str | None = None
        self._session_note: str | None = None
        self._last_error: str | None = None
        self._connected_monotonic: float | None = None
        self._last_line_at: str | None = None
        self._rx_line_count = 0
        self._parse_error_count = 0
        self._sample_count = 0
        self._batch_count = 0
        # data rows of the batch currently being received (reset at OVER)
        self._batch_received = 0

        self._pending_measurements: list[ParsedLine] = []
        self._pending_raw_lines: list[dict[str, Any]] = []
        self._shutdown = False
        self._stats = {"events_emitted": 0, "events_dropped": 0}

    # ------------------------------------------------------------------ setup
    def _default_link(self) -> LinkConfig:
        s = self.settings
        return LinkConfig(
            port=s.serial_port,
            baud_rate=s.serial_baudrate,
            data_bits=s.serial_bytesize,
            parity=s.serial_parity,
            stop_bits=s.serial_stopbits,
            flow_control=s.serial_flowcontrol,
        )

    def bind_loop(self, loop: Any) -> None:
        """Capture the event loop (called from the lifespan) for the WS bridge."""
        if self.bridge is not None:
            self.bridge.bind_loop(loop)

    # -------------------------------------------------------------- ports
    def enumerate_ports(self) -> PortsView:
        """List COM ports with CP210x / Silicon Labs candidates sorted first.

        Returns ``([], None, error)`` instead of raising when the platform gives
        us nothing usable - the console must stay operable without hardware.
        """
        try:
            raw_ports = list(self._port_lister())
        except Exception as exc:  # noqa: BLE001 - enumeration must never 500
            logger.warning("port enumeration failed: %s", exc)
            return PortsView(ports=(), suggested_port=None, error=f"port enumeration failed: {exc}")

        active_device = self.active_port()
        infos: list[PortInfo] = []
        for item in raw_ports:
            device = str(getattr(item, "device", "") or "")
            name = str(getattr(item, "name", "") or device)
            description = str(getattr(item, "description", "") or name)
            hwid = str(getattr(item, "hwid", "") or "")
            infos.append(
                PortInfo(
                    device=device,
                    name=name,
                    description=description,
                    hwid=hwid,
                    preferred=_is_preferred(description, hwid),
                    active=bool(active_device) and device.upper() == active_device.upper(),
                )
            )
        # stable partition: preferred candidates first, discovery order kept inside
        ordered = [p for p in infos if p.preferred] + [p for p in infos if not p.preferred]

        suggested = next((p.device for p in ordered if p.preferred), None)
        if suggested is None:
            # no CP210x anywhere: fall back to the active port, then to the
            # configured default, then to whatever exists. Never fails.
            by_device = {p.device.upper(): p.device for p in ordered}
            for candidate in (active_device, self.settings.serial_port):
                if candidate and candidate.upper() in by_device:
                    suggested = by_device[candidate.upper()]
                    break
            else:
                suggested = ordered[0].device if ordered else None
        return PortsView(ports=tuple(ordered), suggested_port=suggested, error=None)

    def active_port(self) -> str | None:
        """The port of a live link, or ``None`` when nothing is connected."""
        with self._lock:
            if self._state in LINK_UP_STATES and self._serial is not None:
                return self._link.port
            return None

    def resolve_port(self, requested: str | None) -> str:
        """Explicit request wins; otherwise prefer CP210x, else the default."""
        if requested and requested.strip():
            return requested.strip()
        view = self.enumerate_ports()
        if view.suggested_port:
            return view.suggested_port
        return self.settings.serial_port

    # -------------------------------------------------------------- lifecycle
    @property
    def state(self) -> SerialState:
        with self._lock:
            return self._state

    def is_connected(self) -> bool:
        """True while the port is open, whether or not a batch is running."""
        with self._lock:
            return self._state in LINK_UP_STATES and self._serial is not None

    def connect(self, request: ConnectOptions | None = None) -> ConnectResult:
        """Open the port + start the reader thread. Idempotent, never crashes.

        No session is created here: a session is one exported batch, so it starts
        with the first header/data line (see :meth:`_ensure_session`).
        """
        options = request or ConnectOptions()
        with self._lock:
            if self._shutdown:
                return ConnectResult(
                    ok=False, session_id=None, state=self._state.value,
                    port=self._link.port, baud_rate=self._link.baud_rate,
                    message="串口服务正在停机，拒绝新的连接",
                )
            if self._state in LINK_UP_STATES:
                return ConnectResult(
                    ok=False,
                    session_id=self._session_id,
                    state=self._state.value,
                    port=self._link.port,
                    baud_rate=self._link.baud_rate,
                    message=f"串口 {self._link.port} 已连接，请先断开",
                )
            if self._state is SerialState.CONNECTING:
                return ConnectResult(
                    ok=False,
                    session_id=None,
                    state=self._state.value,
                    port=self._link.port,
                    baud_rate=self._link.baud_rate,
                    message="已有一个连接请求正在进行中",
                )
            self._state = SerialState.CONNECTING
            self._last_error = None

        link = self._build_link(options)
        handle: Any = None
        try:
            handle = self._open_port(link)
        except Exception as exc:  # noqa: BLE001 - reported, never propagated
            message = _connect_failure_message(link.port, exc)
            logger.warning("serial connect failed: %s (%s)", message, exc)
            with self._lock:
                self._state = SerialState.ERROR
                self._last_error = message
                self._link = link
                self._connected_monotonic = None
            self._emit_status()
            return ConnectResult(
                ok=False, session_id=None, state=self._state.value, port=link.port,
                baud_rate=link.baud_rate, message=message,
            )

        stop_event = threading.Event()
        reader = threading.Thread(
            target=self._reader_loop,
            args=(handle, stop_event),
            name=f"ric-serial-reader-{link.port}",
            daemon=True,
        )
        with self._lock:
            self._serial = handle
            self._link = link
            self._session_id = None
            self._state = SerialState.CONNECTED_WAITING
            self._connected_monotonic = time.monotonic()
            self._stop_event = stop_event
            self._sample_count = 0
            self._batch_count = 0
            self._batch_received = 0
            self._rx_line_count = 0
            self._parse_error_count = 0
            self._last_line_at = None
            self._pending_measurements = []
            self._pending_raw_lines = []
            self._session_note = options.session_note
            self._shutdown = False
            self._thread = reader
        reader.start()
        logger.info("connected %s@%s, waiting for 导出记录", link.port, link.baud_rate)
        self._emit_status()
        return ConnectResult(
            ok=True, session_id=None, state=self._state.value, port=link.port,
            baud_rate=link.baud_rate,
            message=f"已连接 {link.port}，等待仪器导出记录",
        )

    def disconnect(self, *, reason: str | None = None, status: str | None = None) -> DisconnectResult:
        """Stop the reader, flush what is left, close the session. Idempotent."""
        with self._lock:
            if self._state is SerialState.DISCONNECTED and self._thread is None and self._serial is None:
                message = "already disconnected" if not reason else f"already disconnected ({reason})"
                return DisconnectResult(
                    ok=True, state=self._state.value, session_id=self._session_id, message=message
                )
            thread, stop_event, handle = self._thread, self._stop_event, self._serial
            session_id = self._session_id
            # Captured NOW, before the reader is stopped: whoever performs the
            # final flush (this thread or the reader's exit path), the session
            # must remember that a batch was still open when disconnect was asked
            # for. Sampling it later would race with that exit flush.
            batch_was_open = self._has_pending_batch()
            self._state = SerialState.DISCONNECTED
            self._thread = None
            self._serial = None
            self._connected_monotonic = None
            if stop_event is not None:
                stop_event.set()
            self._stop_event = None

        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=self.settings.serial_reader_join_timeout_s)
            if thread.is_alive():  # pragma: no cover - pathological blocked read
                logger.warning("serial reader thread did not stop within %.1fs",
                               self.settings.serial_reader_join_timeout_s)

        self._close_handle(handle)

        # Anything the reader did not flush before it stopped is archived here.
        self._flush_batch(reason="disconnect")
        final_status = status or (
            repository.STATUS_INTERRUPTED if batch_was_open else repository.STATUS_COMPLETED
        )
        with self._lock:
            counters = {"sample_count": self._sample_count, "batch_count": self._batch_count}
            self._session_id = None
            self._batch_received = 0
            self._pending_measurements = []
            self._pending_raw_lines = []
        if session_id:
            try:
                repository.finalize_session(self.db, session_id, status=final_status)
            except Exception:  # noqa: BLE001 - shutdown path must not raise
                logger.exception("could not finalize session %s", session_id)
        logger.info("disconnected session=%s status=%s samples=%s batches=%s",
                    session_id, final_status, counters["sample_count"], counters["batch_count"])
        self._emit_status()
        return DisconnectResult(
            ok=True, state=SerialState.DISCONNECTED.value, session_id=session_id,
            message=(f"disconnected ({reason})" if reason else "disconnected"),
        )

    def stop(self) -> None:
        """Lifespan shutdown: no new connects, reader stopped, port closed."""
        with self._lock:
            self._shutdown = True
        self.disconnect(reason="server shutdown")

    # -------------------------------------------------------------- status
    def status(self) -> dict[str, Any]:
        """The exact ``GET /api/serial/status`` shape."""
        with self._lock:
            uptime = 0
            if self._connected_monotonic is not None and self._state in LINK_UP_STATES:
                uptime = int((time.monotonic() - self._connected_monotonic) * 1000)
            return {
                "state": self._state.value,
                # Only a live link reports a port: after a failed attempt the
                # name would be stale, and the UI must not pre-fill it.
                "port": self._link.port if self._state in LINK_UP_STATES else None,
                "baud_rate": self._link.baud_rate,
                "data_bits": self._link.data_bits,
                "parity": self._link.parity,
                "stop_bits": self._link.stop_bits,
                "flow_control": self._link.flow_control,
                "session_id": self._session_id,
                "sample_count": self._sample_count,
                "batch_count": self._batch_count,
                # rows of the batch still in flight; 0 once OVER has been handled
                "records_in_batch": self._batch_received,
                "last_line_at": self._last_line_at,
                "last_error": self._last_error,
                "rx_line_count": self._rx_line_count,
                "parse_error_count": self._parse_error_count,
                "uptime_ms": uptime,
            }

    @property
    def session_id(self) -> str | None:
        with self._lock:
            return self._session_id

    # --------------------------------------------------- data path (thread)
    def _reader_loop(self, ser: Any, stop_event: threading.Event) -> None:
        """Daemon-thread loop: ``in_waiting`` + ``readline``; never asyncio."""
        logger.debug("serial reader started")
        poll = max(0.001, float(self.settings.serial_poll_interval_s))
        error: str | None = None
        try:
            while not stop_event.is_set():
                try:
                    waiting = int(getattr(ser, "in_waiting", 0) or 0)
                except Exception as exc:  # noqa: BLE001 - port gone
                    error = f"in_waiting failed: {exc}"
                    break
                if waiting <= 0:
                    stop_event.wait(poll)
                    continue
                try:
                    chunk = ser.readline()
                except Exception as exc:  # noqa: BLE001
                    error = f"readline failed: {exc}"
                    break
                if not chunk:  # read timeout, nothing complete yet
                    stop_event.wait(poll)
                    continue
                self.handle_raw_chunk(chunk)
        except Exception as exc:  # noqa: BLE001 - last-resort guard for the thread
            error = f"reader loop crashed: {exc}"
            logger.exception("serial reader thread crashed")
        finally:
            self._flush_batch(reason="reader exit")
            if error is None:
                logger.debug("serial reader stopped")
                return
            logger.error("serial reader error: %s", error)
            self._on_reader_error(error)

    def handle_raw_chunk(self, chunk: bytes | bytearray | str) -> ParsedLine | None:
        """One wire line -> parse -> buffer/flush -> bridge event. Thread-safe."""
        if isinstance(chunk, (bytes, bytearray)):
            text = self.parser.decode(chunk)
        else:
            text = str(chunk)
        return self.ingest_line(text)

    def ingest_line(self, line: str) -> ParsedLine | None:
        """Public entry point of the parse/persist path (used by the reader
        thread, by tests and by any future replay/simulator tool).

        Batch state machine: the first header/data line opens a session, ``OVER``
        closes it and returns the link to ``connected_waiting``. The port itself
        stays open — ``OVER`` ends a batch, never a connection.
        """
        try:
            parsed = self.parser.parse(line)
        except LineSchemaError as exc:
            # strict:true must still never kill the reader: archive + count.
            parsed = ParsedLine(raw_line=str(line).strip(), kind=KIND_INVALID, parse_error=str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.exception("parser blew up on %r", line)
            parsed = ParsedLine(raw_line=str(line).strip(), kind=KIND_INVALID, parse_error=f"parser error: {exc}")

        self._account_line(parsed)

        if parsed.is_control:
            self._complete_batch(parsed)
            return parsed

        if parsed.is_header:
            # The instrument echoing its own column names: archive it as protocol
            # (same kind as the terminator) and treat it as the start of a batch.
            session_id, _created = self._ensure_session()
            if session_id is not None:
                with self._lock:
                    self._pending_raw_lines.append(
                        {"line": parsed.raw_line, "kind": KIND_CONTROL, "parse_error": None}
                    )
            return parsed

        if parsed.raw_line == "":
            return parsed  # blank line we were told not to archive

        if parsed.is_data:
            session_id, created_now = self._ensure_session(counted=1)
            if session_id is None:
                return parsed  # _ensure_session already reported the failure
            with self._lock:
                self._pending_measurements.append(parsed)
                self._pending_raw_lines.append(
                    {"line": parsed.raw_line, "kind": KIND_DATA, "parse_error": parsed.parse_error}
                )
                if not created_now:
                    self._batch_received += 1
                snapshot = asdict(parsed)
            self._emit(EV_MEASUREMENT, self._measurement_payload(snapshot))
            return parsed

        # invalid: archived for debugging, never inserted into measurements.
        # Before the first data line of a batch there is no session to hang it
        # on (raw_lines.session_id is a NOT NULL FK), so such a line is counted
        # and reported but safely not archived.
        with self._lock:
            if self._session_id is not None:
                self._pending_raw_lines.append(
                    {"line": parsed.raw_line, "kind": KIND_INVALID, "parse_error": parsed.parse_error}
                )
        self._emit(EV_PARSE_ERROR, {"line": parsed.raw_line, "reason": parsed.parse_error or "unparseable line"})
        return parsed

    def ingest_lines(self, lines: Iterable[str]) -> dict[str, int]:
        """Feed an iterable of wire lines through the same path (simulator/tests)."""
        counts = {"data": 0, "control": 0, "invalid": 0, "header": 0}
        for line in lines:
            parsed = self.ingest_line(line)
            if parsed is not None:
                counts[parsed.kind] = counts.get(parsed.kind, 0) + 1
        return counts

    # ------------------------------------------------------- batch lifecycle
    def _ensure_session(self, *, counted: int = 0) -> tuple[str | None, bool]:
        """Open the session for the batch being received, if one is not open.

        Returns ``(session_id, created_now)``. `counted` seeds the row counter on
        the line that triggers the transition, so the status frame emitted at that
        moment already reports the right `records_in_batch`.
        """
        with self._lock:
            if self._session_id is not None:
                if self._state is not SerialState.RECEIVING:
                    self._state = SerialState.RECEIVING
                return self._session_id, False
            link = self._link
            note = self._session_note

        try:
            session = repository.create_session(
                self.db,
                port=link.port,
                baud_rate=link.baud_rate,
                note=note,
                source=repository.SOURCE_SERIAL,
            )
        except Exception as exc:  # noqa: BLE001 - no DB, no batch: report, keep reading
            logger.exception("session creation failed while receiving")
            with self._lock:
                self._last_error = f"无法创建批次会话：{exc}"
            self._emit_status()
            return None, False

        with self._lock:
            self._session_id = session["id"]
            self._state = SerialState.RECEIVING
            self._batch_received = counted
            self._pending_measurements = []
            self._pending_raw_lines = []
        logger.info("batch session %s started (export in progress)", session["id"])
        self._emit_status()
        return session["id"], True

    def _complete_batch(self, terminator: ParsedLine) -> None:
        """``OVER``: persist + close the batch's session, keep the port open."""
        with self._lock:
            session_id = self._session_id
            if session_id is not None:
                self._pending_raw_lines.append(
                    {"line": terminator.raw_line, "kind": KIND_CONTROL, "parse_error": None}
                )
        if session_id is None:
            logger.warning("terminator received with no batch in progress; ignored")
            return

        result = self._flush_batch(reason=terminator.raw_line)
        record_count = int(result["measurement_count"]) if result else 0
        try:
            finalized = repository.finalize_session(
                self.db, session_id, status=repository.STATUS_COMPLETED
            )
        except Exception:  # noqa: BLE001 - the batch is already on disk
            logger.exception("could not finalize session %s", session_id)
            finalized = None

        with self._lock:
            self._session_id = None
            self._batch_received = 0
            self._state = SerialState.BATCH_COMPLETE

        self._emit(
            EV_SESSION_COMPLETE,
            {
                "session_id": session_id,
                "record_count": record_count,
                "batch_seq": result["batch_seq"] if result else 0,
                "raw_line_count": result["raw_line_count"] if result else 0,
                "started_at": (finalized or {}).get("started_at"),
                "ended_at": (finalized or {}).get("ended_at"),
                "port": (finalized or {}).get("port") or self._link.port,
                "status": (finalized or {}).get("status") or repository.STATUS_COMPLETED,
            },
        )
        logger.info("batch session %s complete (records=%s)", session_id, record_count)

        # Back to waiting: the next 导出记录 on the DHJ-9 starts a new session.
        with self._lock:
            self._state = SerialState.CONNECTED_WAITING
        self._emit_status()

    # -------------------------------------------------------- batch flushing
    def _flush_batch(self, *, reason: str) -> dict[str, Any] | None:
        with self._lock:
            measurements = self._pending_measurements
            raw_lines = self._pending_raw_lines
            session_id = self._session_id
            self._pending_measurements = []
            self._pending_raw_lines = []
        if not measurements and not raw_lines:
            return None
        if not session_id:
            logger.error("dropping %s pending lines: no active session (reason=%s)", len(raw_lines), reason)
            return None
        payload: list[dict[str, Any]] = [
            {
                "fields": m.fields or {},
                "ts": m.ts,
                "ts_raw": m.ts_raw,
                "raw_line": m.raw_line,
            }
            for m in measurements
        ]
        try:
            result = repository.flush_batch(self.db, session_id=session_id, measurements=payload, raw_lines=raw_lines)
        except Exception as exc:  # noqa: BLE001 - a failed write must not kill the reader
            logger.exception("batch flush failed (reason=%s, session=%s)", reason, session_id)
            with self._lock:
                self._last_error = f"batch flush failed: {exc}"
                # put the lines back so the next OVER can retry them
                self._pending_measurements = measurements + self._pending_measurements
                self._pending_raw_lines = raw_lines + self._pending_raw_lines
            return None
        with self._lock:
            self._sample_count = int(result.get("sample_count", self._sample_count))
            self._batch_count = int(result.get("batch_count", self._batch_count))
        logger.info(
            "batch flushed (session=%s samples=%s raw=%s reason=%s)",
            session_id, result["measurement_count"], result["raw_line_count"], reason,
        )
        return result

    def _has_pending_batch(self) -> bool:
        with self._lock:
            return bool(self._pending_measurements or self._pending_raw_lines)

    # ---------------------------------------------------------------- events
    def _measurement_payload(self, parsed: dict[str, Any]) -> dict[str, Any]:
        """Live `measurement` envelope body.

        `id` / `batch_seq` are assigned by SQLite when the batch is flushed, so
        they are null here on purpose - the following `session.complete` carries the
        real `batch_seq`. `created_at` is the console receive time.
        """
        with self._lock:
            session_id = self._session_id
        return {
            "session_id": session_id,
            "fields": parsed.get("fields") or {},
            "raw_line": parsed.get("raw_line"),
            "ts": parsed.get("ts"),
            "ts_raw": parsed.get("ts_raw"),
            "id": None,
            "batch_seq": None,
            "created_at": repository.utc_now_iso(),
        }

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self.bridge is None:
            return
        try:
            if self.bridge.emit(event_type, payload):
                self._stats["events_emitted"] += 1
            else:
                self._stats["events_dropped"] += 1
        except Exception:  # noqa: BLE001 - realtime is best effort
            self._stats["events_dropped"] += 1
            logger.debug("event emission failed for %s", event_type, exc_info=True)

    def _emit_status(self) -> None:
        self._emit(EV_STATUS, self.status())

    def _account_line(self, parsed: ParsedLine) -> None:
        with self._lock:
            self._rx_line_count += 1
            self._last_line_at = repository.utc_now_iso()
            if parsed.kind == KIND_INVALID:
                self._parse_error_count += 1

    def _on_reader_error(self, message: str) -> None:
        """Device disappeared: park in `error`, close the port, mark session failed."""
        self._flush_batch(reason="reader error")
        with self._lock:
            session_id = self._session_id
            self._state = SerialState.ERROR
            self._last_error = message
            handle, self._serial = self._serial, None
            thread, self._thread = self._thread, None
            self._connected_monotonic = None
            self._session_id = None
            self._batch_received = 0
            if self._stop_event is not None:
                self._stop_event.set()
            self._stop_event = None
            counters = {"sample_count": self._sample_count, "batch_count": self._batch_count}
        self._close_handle(handle)
        if session_id:
            try:
                repository.finalize_session(self.db, session_id, status=repository.STATUS_FAILED)
            except Exception:  # noqa: BLE001
                logger.exception("could not mark session %s failed", session_id)
        logger.error("serial link lost (session=%s samples=%s batches=%s)",
                     session_id, counters["sample_count"], counters["batch_count"])
        self._emit_status()

    # ---------------------------------------------------------------- private
    def _build_link(self, options: ConnectOptions) -> LinkConfig:
        s = self.settings
        port = self.resolve_port(options.port)
        return LinkConfig(
            port=port,
            baud_rate=int(options.baud_rate or s.serial_baudrate),
            data_bits=int(options.data_bits or s.serial_bytesize),
            parity=str(options.parity or s.serial_parity).upper()[:1],
            stop_bits=float(options.stop_bits if options.stop_bits is not None else s.serial_stopbits),
            flow_control=str(options.flow_control or s.serial_flowcontrol).lower(),
        )

    def _open_port(self, link: LinkConfig) -> Any:
        kwargs = link.serial_kwargs()
        kwargs["timeout"] = self.settings.serial_read_timeout_s
        return self._serial_factory(**kwargs)

    @staticmethod
    def _close_handle(handle: Any) -> None:
        if handle is None:
            return
        try:
            handle.close()
        except Exception:  # noqa: BLE001
            logger.debug("closing the serial handle failed", exc_info=True)


__all__ = [
    "ConnectOptions",
    "ConnectResult",
    "DisconnectResult",
    "LINK_UP_STATES",
    "LinkConfig",
    "PREFERRED_PORT_MARKERS",
    "PortInfo",
    "PortsView",
    "SerialService",
    "SerialState",
]
