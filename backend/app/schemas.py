"""Pydantic request/response models: the HTTP + WebSocket contract.

This is the only place where wire shapes are declared. Route modules must not
build response dicts by hand, and the service layer must not import from here
(the API layer adapts service dataclasses to these models).

Note on semantics: the field names exposed by ``/api/parser/fields`` come from
``config/parser.yaml``. Positions 0-10 are confirmed against the DHJ-9 instrument
header; position 11 is not, and the ``confirmed`` flag is carried all the way to
the client so the UI can say which is which.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Parity = Literal["N", "E", "O", "M", "S"]
FlowControl = Literal["none", "hardware", "rtscts", "software", "xonxoff"]
SessionStatus = Literal["running", "completed", "interrupted", "failed"]
RawLineKind = Literal["data", "control", "invalid"]
# `reconnecting` is part of the wire vocabulary so the console can render it, but
# SerialService never emits it in this phase - automatic reconnection is a TODO.
SerialStateName = Literal[
    "disconnected",
    "connecting",
    "connected_waiting",
    "receiving",
    "batch_complete",
    "error",
    "reconnecting",
]


# --------------------------------------------------------------------------- #
# /api/serial/*
# --------------------------------------------------------------------------- #
class ConnectRequest(BaseModel):
    """Every member is optional; omitted values fall back to ``.env`` defaults
    (COM7 / 115200 / 8 / N / 1 / none) and an omitted ``port`` falls back to the
    auto-detected CP210x suggestion."""

    model_config = ConfigDict(extra="ignore")

    port: str | None = Field(default=None, min_length=1, max_length=64, description="e.g. COM7")
    baud_rate: int | None = Field(default=None, ge=300, le=2_000_000)
    data_bits: int | None = Field(default=None, ge=5, le=8)
    parity: Parity | None = None
    stop_bits: float | None = Field(default=None, description="1, 1.5 or 2")
    flow_control: FlowControl | None = None
    session_note: str | None = Field(default=None, max_length=500)

    @field_validator("port")
    @classmethod
    def _strip_port(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("port must not be blank")
        # preserved verbatim (Windows COM names are case-insensitive anyway, and
        # POSIX paths such as /dev/ttyUSB0 must not be mangled)
        return cleaned

    def to_options(self) -> Any:
        """Adapt to :class:`app.services.serial_service.ConnectOptions`."""
        from .services.serial_service import ConnectOptions  # noqa: PLC0415 - avoids an import cycle

        return ConnectOptions(
            port=self.port,
            baud_rate=self.baud_rate,
            data_bits=self.data_bits,
            parity=self.parity,
            stop_bits=self.stop_bits,
            flow_control=self.flow_control,
            session_note=self.session_note,
        )


class ConnectResponse(BaseModel):
    ok: bool
    session_id: str | None = None
    state: SerialStateName
    port: str | None = None
    baud_rate: int | None = None
    message: str


class DisconnectRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    reason: str | None = Field(default=None, max_length=200)

    @field_validator("reason")
    @classmethod
    def _strip_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class DisconnectResponse(BaseModel):
    ok: bool
    state: SerialStateName
    session_id: str | None = None
    message: str


class PortInfo(BaseModel):
    """Platform-neutral port descriptor.

    `device` is ``COM7`` on Windows and ``/dev/ttyUSB0`` on Linux; nothing here
    assumes either naming scheme.
    """

    device: str
    name: str
    description: str | None = None
    hwid: str | None = None
    manufacturer: str | None = None
    vid: int | None = None
    pid: int | None = None
    serial_number: str | None = None
    suggested: bool = False
    active: bool = False


class PortsResponse(BaseModel):
    ports: list[PortInfo] = Field(default_factory=list)
    suggested_port: str | None = None
    error: str | None = None


class SerialStatusResponse(BaseModel):
    state: SerialStateName
    port: str | None = None
    baud_rate: int | None = None
    data_bits: int | None = None
    parity: str | None = None
    stop_bits: float | None = None
    flow_control: str | None = None
    session_id: str | None = None
    sample_count: int = 0
    batch_count: int = 0
    # rows of the batch still in flight (0 while waiting, or after OVER)
    records_in_batch: int = 0
    last_line_at: str | None = None
    last_error: str | None = None
    rx_line_count: int = 0
    parse_error_count: int = 0
    uptime_ms: int = 0


# --------------------------------------------------------------------------- #
# /api/sessions*
# --------------------------------------------------------------------------- #
class SessionOut(BaseModel):
    id: str
    started_at: str
    ended_at: str | None = None
    port: str
    baud_rate: int
    status: SessionStatus
    sample_count: int = 0
    batch_count: int = 0
    source: str = "serial"
    note: str | None = None


class SessionsResponse(BaseModel):
    items: list[SessionOut] = Field(default_factory=list)
    total: int = 0


class MeasurementOut(BaseModel):
    id: int | None = None
    session_id: str | None = None
    ts_raw: str | None = None
    ts: str | None = None
    # Parsed fields keyed by the configured (mostly unconfirmed) names.
    fields: dict[str, Any] = Field(default_factory=dict)
    raw_line: str
    batch_seq: int = 0
    created_at: str | None = None


class SessionDetailResponse(BaseModel):
    session: SessionOut
    samples: list[MeasurementOut] = Field(default_factory=list)
    latest: MeasurementOut | None = None
    count: int = 0


class RawLineOut(BaseModel):
    id: int
    session_id: str
    line: str
    kind: RawLineKind
    parse_error: str | None = None
    created_at: str


class ErrorDetail(BaseModel):
    detail: str


# --------------------------------------------------------------------------- #
# /api/parser/fields + /api/health
# --------------------------------------------------------------------------- #
class ParserFieldOut(BaseModel):
    index: int
    name: str
    type: str
    unit: str | None = None
    confirmed: bool = False
    note: str | None = None


class ParserFieldsResponse(BaseModel):
    fields: list[ParserFieldOut] = Field(default_factory=list)
    # INDEX of the timestamp column (7), matching the frontend's `timestamp_field: number`
    timestamp_field: int | None = None
    end_of_batch_token: str | None = None
    expected_field_count: int | None = None
    timestamp_format: str | None = None
    # extra context that keeps the "these names are guesses" story visible
    timestamp_name: str | None = None
    strict: bool | None = None
    delimiter: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    version: str
    db_path: str
    serial_state: SerialStateName


# --------------------------------------------------------------------------- #
# /ws/live
# --------------------------------------------------------------------------- #
class WSClientMessage(BaseModel):
    """Client -> server frame. Only ``ping`` is understood in this phase."""

    model_config = ConfigDict(extra="ignore")

    type: Literal["ping"] = "ping"


class WSEnvelope(BaseModel):
    """Server -> client frame: ``{ type, source, timestamp, payload }``.

    `source` names the rig that produced the frame (``dhj9`` for the DHJ-9 laser
    detector, ``console`` for transport replies), so a second source can share
    this socket later without reinterpreting existing events.
    """

    type: str
    source: str
    timestamp: str
    payload: dict[str, Any] = Field(default_factory=dict)


class WSSnapshotPayload(BaseModel):
    status: SerialStatusResponse
    session: SessionOut | None = None
    measurements: list[MeasurementOut] = Field(default_factory=list)
    parser: ParserFieldsResponse | None = None


class WSSessionCompletePayload(BaseModel):
    """Emitted once per ``OVER``: the batch that just closed."""

    session_id: str | None = None
    # measurement rows written by the batch (0 for an empty or garbage-only one)
    record_count: int = 0
    batch_seq: int = 0
    raw_line_count: int = 0
    started_at: str | None = None
    ended_at: str | None = None
    port: str | None = None
    status: SessionStatus = "completed"


class WSParseErrorPayload(BaseModel):
    line: str
    reason: str | None = None


__all__ = [
    "ConnectRequest",
    "ConnectResponse",
    "DisconnectRequest",
    "DisconnectResponse",
    "ErrorDetail",
    "HealthResponse",
    "MeasurementOut",
    "ParserFieldOut",
    "ParserFieldsResponse",
    "PortInfo",
    "PortsResponse",
    "RawLineOut",
    "SerialStatusResponse",
    "SessionDetailResponse",
    "SessionOut",
    "SessionsResponse",
    "WSClientMessage",
    "WSEnvelope",
    "WSParseErrorPayload",
    "WSSessionCompletePayload",
    "WSSnapshotPayload",
]
