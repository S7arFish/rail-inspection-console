"""``/api/sessions*`` - read-only queries over persisted batches.

Queries go straight to the repository (via a worker thread); nothing is computed
in here beyond mapping rows onto response models.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from ..db import repository
from ..db.database import Database
from ..deps import get_database_dep, to_thread
from ..schemas import ErrorDetail, MeasurementOut, SessionDetailResponse, SessionOut, SessionsResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sessions", tags=["sessions"])

DbDep = Annotated[Database, Depends(get_database_dep)]

DEFAULT_SAMPLE_LIMIT = 500


@router.get("", response_model=SessionsResponse, summary="List capture sessions (newest first)")
async def list_sessions(
    db: DbDep,
    limit: Annotated[int, Query(ge=1, le=500, description="page size")] = 50,
    offset: Annotated[int, Query(ge=0, description="page offset")] = 0,
) -> SessionsResponse:
    items, total = await to_thread(repository.list_sessions, db, limit=limit, offset=offset)
    return SessionsResponse(items=[SessionOut(**s) for s in items], total=total)


@router.get(
    "/{session_id}",
    response_model=SessionDetailResponse,
    responses={404: {"model": ErrorDetail}},
    summary="One session with its samples",
)
async def get_session_detail(
    db: DbDep,
    session_id: Annotated[str, Path(min_length=1, max_length=64)],
    limit: Annotated[int, Query(ge=1, le=5000, description="max samples returned")] = DEFAULT_SAMPLE_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
    order: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
) -> SessionDetailResponse:
    session = await to_thread(repository.get_session, db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session {session_id!r} not found")
    samples, latest, count = await to_thread(
        _load_samples, db, session_id, limit=limit, offset=offset, order=order
    )
    return SessionDetailResponse(
        session=SessionOut(**session),
        samples=[MeasurementOut(**s) for s in samples],
        latest=MeasurementOut(**latest) if latest else None,
        count=count,
    )


def _load_samples(
    db: Database, session_id: str, *, limit: int, offset: int, order: str
) -> tuple[list[dict], dict | None, int]:
    """One blocking unit of repository work (executed in a worker thread)."""
    samples = repository.list_measurements(db, session_id, limit=limit, offset=offset, order=order)
    latest = repository.latest_measurement(db, session_id)
    count = repository.count_measurements(db, session_id)
    return samples, latest, count


__all__ = ["router"]
