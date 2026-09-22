"""Realtime fan-out: WebSocket connection manager + thread -> event-loop bridge.

The serial reader runs in its own *thread*; WebSocket sends are coroutines bound
to the event loop captured in the lifespan. ``EventBridge.publish`` is therefore
the only object the reader thread talks to, and it uses
``asyncio.run_coroutine_threadsafe`` to hand the envelope to the loop.

Everything here degrades to a no-op when nobody is subscribed and when the loop
is gone (shutdown), so the serial path never depends on WebSocket clients.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from inspect import isawaitable
from typing import Any, Awaitable, Callable, Iterable

from fastapi import WebSocket

from ..db.repository import utc_now_iso

logger = logging.getLogger(__name__)

# Envelope `type` values of the /ws/live protocol. Device events are namespaced
# by their origin so a second source (e.g. a vision rig) can share this socket
# later without colliding. `pong` / `error` are transport-level, not device data.
EV_SNAPSHOT = "laser.snapshot"
EV_MEASUREMENT = "laser.measurement"
EV_SESSION_COMPLETE = "session.complete"
EV_STATUS = "laser.status"
EV_PARSE_ERROR = "laser.parse_error"
EV_PONG = "pong"
EV_ERROR = "error"

# Envelope `source` values.
SOURCE_DHG9 = "dhj9"
SOURCE_CONSOLE = "console"


def make_envelope(
    event_type: str,
    payload: dict[str, Any] | None = None,
    *,
    source: str = SOURCE_DHG9,
    ts: str | None = None,
) -> dict[str, Any]:
    """``{ type, source, timestamp, payload }`` - the single wire shape.

    Every frame carries its origin, so consumers never have to infer which rig
    produced an event.
    """
    return {
        "type": event_type,
        "source": source,
        "timestamp": ts or utc_now_iso(),
        "payload": payload or {},
    }


class ConnectionManager:
    """Keeps the live ``/ws/live`` sockets and broadcasts JSON envelopes."""

    def __init__(self, *, max_connections: int = 50) -> None:
        self.max_connections = max(1, int(max_connections))
        self._connections: list[WebSocket] = []
        self._lock = asyncio.Lock()
        self._dropped = 0

    # ------------------------------------------------------------- membership
    @property
    def connection_count(self) -> int:
        return len(self._connections)

    async def accept(self, websocket: WebSocket) -> bool:
        await websocket.accept()
        async with self._lock:
            if len(self._connections) >= self.max_connections:
                self._dropped += 1
                logger.warning("ws connection limit reached (%s), rejecting client", self.max_connections)
                await websocket.close(code=1013, reason="too many live console clients")
                return False
            self._connections.append(websocket)
            logger.info("ws client connected (%d live)", len(self._connections))
        return True

    async def leave(self, websocket: WebSocket) -> None:
        async with self._lock:
            if websocket in self._connections:
                self._connections.remove(websocket)
                logger.info("ws client disconnected (%d live)", len(self._connections))

    def forget(self, websocket: WebSocket) -> None:
        """Synchronous removal used by the broadcast loop when a send fails."""
        if websocket in self._connections:
            self._connections.remove(websocket)

    # -------------------------------------------------------------- broadcast
    async def broadcast(self, envelope: dict[str, Any]) -> int:
        """Send to every live client; failed sockets are dropped, never raised."""
        targets: Iterable[WebSocket] = list(self._connections)
        sent = 0
        for websocket in targets:
            try:
                await websocket.send_json(envelope)
                sent += 1
            except Exception:  # noqa: BLE001 - client vanished / loop closing
                logger.debug("dropping unreachable ws client", exc_info=True)
                self.forget(websocket)
        return sent

    async def send(self, websocket: WebSocket, envelope: dict[str, Any]) -> bool:
        try:
            await websocket.send_json(envelope)
            return True
        except Exception:  # noqa: BLE001
            logger.debug("ws send failed", exc_info=True)
            self.forget(websocket)
            return False

    async def close_all(self, *, code: int = 1001, reason: str = "server shutdown") -> None:
        async with self._lock:
            connections = list(self._connections)
            self._connections.clear()
        for websocket in connections:
            try:
                await websocket.close(code=code, reason=reason)
            except Exception:  # noqa: BLE001
                logger.debug("ws close failed", exc_info=True)


@dataclass
class EventBridge:
    """Thread-safe facade used by the serial service (no asyncio knowledge there).

    ``publisher`` is an injectable callable - async, or plain synchronous when the
    caller just wants to record envelopes (unit tests, in-process listeners).
    """

    manager: ConnectionManager | None = None
    publisher: Callable[[dict[str, Any]], Awaitable[int] | Any] | None = None
    _loop: asyncio.AbstractEventLoop | None = None
    _pending: set[Any] = field(default_factory=set)
    published: int = 0
    failed: int = 0

    def bind_loop(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        """Capture the lifespan loop; broadcasts then cross the thread boundary."""
        self._loop = loop or asyncio.get_running_loop()
        logger.debug("event bridge bound to loop %r", self._loop)

    @property
    def bound(self) -> bool:
        return self._loop is not None or self.publisher is not None

    def emit(
        self,
        event_type: str,
        payload: dict[str, Any] | None = None,
        *,
        source: str = SOURCE_DHG9,
        ts: str | None = None,
    ) -> bool:
        """Fire-and-forget from *any* thread. Returns False if nothing can receive."""
        return self.publish_nowait(make_envelope(event_type, payload, source=source, ts=ts))

    def publish_nowait(self, envelope: dict[str, Any]) -> bool:
        """Hand one envelope to the loop; safe with zero subscribers, or none."""
        if self.publisher is not None:
            result = self.publisher(envelope)
            if not isawaitable(result):
                # A synchronous recorder (tests, future in-process listeners).
                self.published += 1
                return True
            return self._submit(result)
        loop = self._loop
        if loop is None or self.manager is None or loop.is_closed():
            logger.debug("no live event loop bound, dropping %s event", envelope.get("type"))
            self.failed += 1
            return False
        return self._submit(self.manager.broadcast(envelope), loop=loop)

    # ---------------------------------------------------------------- private
    def _submit(self, coro: Awaitable[Any], *, loop: asyncio.AbstractEventLoop | None = None) -> bool:
        target = loop or self._loop
        if target is None:
            try:  # we are already running inside a loop: schedule on it
                asyncio.get_running_loop().create_task(coro)
                self.published += 1
                return True
            except RuntimeError:
                self.failed += 1
                logger.debug("no event loop available, dropped event")
                return False
        try:
            future = asyncio.run_coroutine_threadsafe(coro, target)
        except RuntimeError:  # loop stopped between check and submit
            self.failed += 1
            logger.debug("run_coroutine_threadsafe failed", exc_info=True)
            return False
        self._pending.add(future)
        self.published += 1

        def _done(fut: Any) -> None:
            self._pending.discard(fut)
            try:
                fut.result()
            except Exception:  # noqa: BLE001 - never propagate into the reader thread
                logger.debug("ws broadcast task failed", exc_info=True)

        future.add_done_callback(_done)
        return True


__all__ = [
    "EV_ERROR",
    "EV_MEASUREMENT",
    "EV_PARSE_ERROR",
    "EV_PONG",
    "EV_SESSION_COMPLETE",
    "EV_SNAPSHOT",
    "EV_STATUS",
    "ConnectionManager",
    "EventBridge",
    "SOURCE_CONSOLE",
    "SOURCE_DHG9",
    "make_envelope",
]
