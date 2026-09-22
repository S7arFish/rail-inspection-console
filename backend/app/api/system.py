"""``GET /api/health`` and ``GET /api/parser/fields``.

Small read-only endpoints that describe the running system and the *configurable*
parser legend. The legend is what lets the frontend render columns without the
backend hard-coding any field semantics - and it carries ``confirmed: false`` for
every placeholder name so an unconfirmed label can never look like a fact.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends

from ..db.database import Database
from ..deps import get_database_dep, get_parser_dep, get_serial_service_dep, get_settings_dep, to_thread
from ..parser.line_parser import LineParser
from ..schemas import HealthResponse, ParserFieldsResponse
from ..services.serial_service import SerialService
from ..settings import Settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["system"])


@router.get("/api/health", response_model=HealthResponse, summary="Liveness + where its data lives")
async def health(
    settings: Annotated[Settings, Depends(get_settings_dep)],
    service: Annotated[SerialService, Depends(get_serial_service_dep)],
    db: Annotated[Database, Depends(get_database_dep)],
) -> HealthResponse:
    # a single cheap statement proves the DB file is usable without a real query
    await to_thread(db.scalar, "SELECT 1", (), "unavailable")
    return HealthResponse(
        status="ok",
        version=settings.app_version,
        db_path=settings.db_path_str,
        serial_state=service.state.value,  # type: ignore[arg-type]
    )


@router.get(
    "/api/parser/fields",
    response_model=ParserFieldsResponse,
    summary="Field legend currently driving the parser (config/parser.yaml)",
)
async def parser_fields(parser: Annotated[LineParser, Depends(get_parser_dep)]) -> ParserFieldsResponse:
    return ParserFieldsResponse(**parser.config.legend_payload())


__all__ = ["router"]
