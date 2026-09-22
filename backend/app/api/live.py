"""``WS /ws/live`` - the only realtime endpoint.

Server -> client envelopes: ``{ type, source, timestamp, payload }`` with
``laser.snapshot | laser.measurement | session.complete | laser.status |
laser.parse_error`` from source ``dhj9``, plus transport frames (``pong`` /
``error``) from source ``console``.
Client -> server: ``{"type": "ping"}`` -> ``{"type": "pong"}``.

The route does nothing but register the socket with the connection manager and
answer pings; *pushing* is the manager's job and is driven by ``SerialService``
through the thread-safe bridge.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from ..db import repository
from ..db.database import Database
from ..deps import get_container, to_thread
from ..parser.line_parser import LineParser
from ..schemas import MeasurementOut, ParserFieldsResponse, SessionOut
from ..services.realtime import EV_PONG, EV_SNAPSHOT, SOURCE_CONSOLE, ConnectionManager, make_envelope
from ..services.serial_service import SerialService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["live"])


@router.websocket("/ws/live")
async def live(websocket: WebSocket) -> None:
    container = await get_container(websocket)
    manager: ConnectionManager = container.manager
    service: SerialService = container.serial
    db: Database = container.database
    parser: LineParser = container.parser

    if not await manager.accept(websocket):
        return

    try:
        snapshot = await _build_snapshot(container.settings.ws_snapshot_size, db, service, parser)
        await manager.send(websocket, make_envelope(EV_SNAPSHOT, snapshot))
    except Exception:  # noqa: BLE001 - a bad snapshot must not kill the socket
        logger.exception("failed to send the initial snapshot")
        await manager.send(
            websocket,
            make_envelope("error", {"message": "initial snapshot could not be built"}, source=SOURCE_CONSOLE),
        )

    try:
        while True:
            message = await websocket.receive_text()
            reply = _handle_client_message(message)
            if reply is not None:
                await manager.send(websocket, reply)
    except WebSocketDisconnect:
        logger.debug("/ws/live client disconnected")
    finally:
        await manager.leave(websocket)
        if websocket.client_state is not WebSocketState.DISCONNECTED:
            try:
                await websocket.close(code=1000)
            except RuntimeError:  # pragma: no cover - already closing
                logger.debug("websocket was already closed")


async def _build_snapshot(limit: int, db: Database, service: SerialService, parser: LineParser) -> dict[str, Any]:
    """Current status + the last N measurements (plus the field legend)."""
    status = service.status()
    session_id = status.get("session_id")
    measurements = await to_thread(repository.recent_measurements, db, limit=limit)
    session = await to_thread(repository.get_session, db, session_id) if session_id else None
    return {
        "status": status,
        "session": SessionOut(**session).model_dump() if session else None,
        "measurements": [MeasurementOut(**m).model_dump() for m in measurements],
        "parser": _parser_legend(parser),
    }


def _parser_legend(parser: LineParser) -> dict[str, Any]:
    """Same legend body as ``GET /api/parser/fields``."""
    return ParserFieldsResponse(**parser.config.legend_payload()).model_dump()


def _handle_client_message(raw: str) -> dict[str, Any] | None:
    """Only ``ping`` is answered in this phase; everything else is ignored."""
    text = (raw or "").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return make_envelope(
            "error", {"message": 'expected a JSON object, e.g. {"type":"ping"}'}, source=SOURCE_CONSOLE
        )
    if not isinstance(data, dict):
        return make_envelope("error", {"message": "expected a JSON object"}, source=SOURCE_CONSOLE)
    kind = str(data.get("type") or "").lower()
    if kind == "ping":
        return make_envelope(EV_PONG, {"echo": data if isinstance(data, dict) else {}}, source=SOURCE_CONSOLE)
    logger.debug("/ws/live ignoring client message type %r", data.get("type"))
    return None


__all__ = ["router"]
