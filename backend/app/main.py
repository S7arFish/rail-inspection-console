"""Application factory + lifespan for the Rail Inspection Console backend.

Run it with::

    uvicorn app.main:app --host 127.0.0.1 --port 8100

Startup order (lifespan): logging -> SQLite schema -> event-loop capture for the
thread-safe WS bridge -> ``SerialService`` ready (port stays **closed** until a
``POST /api/serial/connect``, which is what makes booting without hardware
safe). Shutdown reverses it: reader thread stopped, port closed, sessions
finalized, sockets closed.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api import api_router
from .db.database import DatabaseUnavailable
from .deps import Container, build_container
from .services.serial_service import SerialService
from .settings import Settings, get_settings
from .web import mount_spa

LOGGER_NAME = "app"

__all__ = ["app", "create_app", "health_payload"]


def configure_logging(level: int = logging.INFO) -> None:
    """One-shot root logging setup (stderr, timestamped, no secret leakage)."""
    root = logging.getLogger()
    if root.handlers:
        root.setLevel(level)
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s | %(message)s"))
    root.addHandler(handler)
    root.setLevel(level)
    logging.getLogger("watchfiles").setLevel(logging.WARNING)


def create_app(settings: Settings | None = None, *, container: Container | None = None) -> FastAPI:
    """Build the FastAPI app. Importing this module must never need a COM port."""
    settings = settings or get_settings()
    configure_logging()
    logger = logging.getLogger(LOGGER_NAME)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        state_container: Container = application.state.container
        service: SerialService = state_container.serial
        loop = asyncio.get_running_loop()

        # 1. storage first: nothing else is useful without the schema
        try:
            await asyncio.to_thread(state_container.database.init_schema)
        except DatabaseUnavailable as exc:
            # Health still answers so the console can *show* the problem.
            logger.error("database unavailable at startup: %s", exc)
            application.state.database_ready = False
        else:
            application.state.database_ready = True

        # 2. bridge the worker thread -> event loop boundary
        # worker thread -> event loop hand-off for every realtime envelope
        state_container.bridge.bind_loop(loop)
        service.bind_loop(loop)

        logger.info(
            "RIC backend %s ready | db=%s parser=%s fields=%s | serial state=%s",
            settings.app_version,
            settings.db_path_str,
            settings.parser_config_path.name,
            len(state_container.parser.config.fields),
            service.state.value,
        )
        try:
            yield
        finally:
            logger.info("shutting down: stopping the serial service")
            # the reader thread is a daemon, but stop it politely anyway
            await asyncio.to_thread(service.stop)
            await state_container.manager.close_all(reason="server shutdown")

    application = FastAPI(
        title="Rail Inspection Console API",
        version=settings.app_version,
        summary="Backend for the rail-inspection-car serial data console.",
        description=(
            "Serial line capture for the inspection car with a **configurable** line parser "
            "(config/parser.yaml). Most measurement field names are still unconfirmed "
            "placeholders; each field carries a `confirmed` flag. Anomaly detection and "
            "thresholds are out of scope in this phase."
        ),
        lifespan=lifespan,
    )

    # --- container on state (available even without the lifespan, e.g. tests)
    application.state.container = container or build_container(settings)
    application.state.database_ready = False
    application.state.started = True

    # --- CORS for the Vite dev server
    origins = list(settings.cors_origins)
    allow_all = "*" in origins
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if allow_all else origins,
        # credentials are incompatible with a wildcard origin, so they are only
        # enabled for explicit origins (the Vite dev server case)
        allow_credentials=not allow_all,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
    )

    @application.exception_handler(DatabaseUnavailable)
    async def _database_unavailable(_: Request, exc: DatabaseUnavailable) -> JSONResponse:
        logger.error("database unavailable: %s", exc)
        return JSONResponse(status_code=503, content={"detail": f"database unavailable: {exc}"})

    application.include_router(api_router)

    # Production (Pi kiosk): FastAPI also serves the pre-built React SPA, so the
    # browser only needs one origin. With no build present - i.e. on a dev
    # machine where Vite serves the frontend - the root stays a JSON pointer.
    if mount_spa(application, settings.web_dir):
        return application

    @application.get("/", include_in_schema=False)
    async def index() -> dict[str, object]:
        return {
            "name": settings.app_name,
            "version": settings.app_version,
            "docs": "/docs",
            "health": "/api/health",
            "live": "/ws/live",
        }

    return application


def health_payload(service: SerialService, settings: Settings) -> dict[str, object]:
    """Non-route helper, reused by smoke tests."""
    status = service.status()
    return {
        "status": "ok",
        "version": settings.app_version,
        "db_path": settings.db_path_str,
        "serial_state": status["state"],
    }


app = create_app()
