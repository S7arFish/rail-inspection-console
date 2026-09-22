"""API routers. Every module here is thin: validate input, delegate, return models."""

from __future__ import annotations

from fastapi import APIRouter

from . import live, serial, sessions, system

api_router = APIRouter()
api_router.include_router(system.router)
api_router.include_router(serial.router)
api_router.include_router(sessions.router)
api_router.include_router(live.router)

__all__ = ["api_router", "live", "serial", "sessions", "system"]
