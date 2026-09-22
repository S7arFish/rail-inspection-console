"""``/api/serial/*`` - thin HTTP surface over :class:`SerialService`.

No serial code, no parser code, no SQL here: validate -> delegate -> model.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends

from ..deps import get_serial_service_dep, to_thread
from ..schemas import (
    ConnectRequest,
    ConnectResponse,
    DisconnectRequest,
    DisconnectResponse,
    ErrorDetail,
    PortInfo,
    PortsResponse,
    SerialStatusResponse,
)
from ..services.serial_service import SerialService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/serial", tags=["serial"])

ServiceDep = Annotated[SerialService, Depends(get_serial_service_dep)]


@router.get("/ports", response_model=PortsResponse, summary="List serial ports (CP210x preferred)")
async def list_ports(service: ServiceDep) -> PortsResponse:
    # enumeration touches the OS device list: keep it off the event loop
    view = await to_thread(service.enumerate_ports)
    return PortsResponse(
        ports=[PortInfo(**p.to_dict()) for p in view.ports],
        suggested_port=view.suggested_port,
        error=view.error,
    )


@router.post(
    "/connect",
    response_model=ConnectResponse,
    responses={422: {"model": ErrorDetail}},
    summary="Open the serial port and start reading",
)
async def connect(
    service: ServiceDep,
    payload: ConnectRequest | None = None,
) -> ConnectResponse:
    request = payload or ConnectRequest()
    options = request.to_options()
    # opening a COM port can block for a while -> worker thread, never the loop
    result = await to_thread(service.connect, options)
    return ConnectResponse(**result.to_dict())


@router.post("/disconnect", response_model=DisconnectResponse, summary="Stop reading and close the port")
async def disconnect(
    service: ServiceDep,
    payload: DisconnectRequest | None = None,
) -> DisconnectResponse:
    reason = payload.reason if payload is not None else None
    result = await to_thread(service.disconnect, reason=reason)
    return DisconnectResponse(**result.to_dict())


@router.get("/status", response_model=SerialStatusResponse, summary="Current link + counters snapshot")
async def status(service: ServiceDep) -> SerialStatusResponse:
    return SerialStatusResponse(**service.status())
