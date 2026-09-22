"""Service layer: the serial link owner and the realtime fan-out bridge."""

from __future__ import annotations

from .realtime import (
    EV_ERROR,
    EV_MEASUREMENT,
    EV_PARSE_ERROR,
    EV_PONG,
    EV_SESSION_COMPLETE,
    EV_SNAPSHOT,
    EV_STATUS,
    SOURCE_CONSOLE,
    SOURCE_DHG9,
    ConnectionManager,
    EventBridge,
    make_envelope,
)
from .serial_service import (
    LINK_UP_STATES,
    PREFERRED_PORT_MARKERS,
    ConnectOptions,
    ConnectResult,
    DisconnectResult,
    LinkConfig,
    PortInfo,
    PortsView,
    SerialService,
    SerialState,
)

__all__ = [
    "EV_ERROR",
    "EV_MEASUREMENT",
    "EV_PARSE_ERROR",
    "EV_PONG",
    "EV_SESSION_COMPLETE",
    "EV_SNAPSHOT",
    "EV_STATUS",
    "LINK_UP_STATES",
    "PREFERRED_PORT_MARKERS",
    "SOURCE_CONSOLE",
    "SOURCE_DHG9",
    "ConnectOptions",
    "ConnectResult",
    "ConnectionManager",
    "DisconnectResult",
    "EventBridge",
    "LinkConfig",
    "PortInfo",
    "PortsView",
    "SerialService",
    "SerialState",
    "make_envelope",
]
