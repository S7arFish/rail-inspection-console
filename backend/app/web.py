"""Production hosting of the built React SPA beside the API.

On the Raspberry Pi there is no Vite dev server and no Node runtime: FastAPI
serves the API, the WebSocket and the pre-built frontend from one origin, so the
kiosk browser only ever needs ``http://127.0.0.1:8000``.

On a Windows dev machine the build directory normally does not exist, so this
module stays inactive and everything keeps working exactly as before (Vite on
5173 proxying ``/api`` and ``/ws`` to 8000).

Routing rules that must hold:
* ``/`` and any unknown non-API path -> ``index.html`` (client-side router)
* ``/api/...`` unknown -> JSON 404, never ``index.html``
* ``/ws/live`` -> the WebSocket route, never captured by the SPA fallback
* real build files (``/assets/...``, favicons) are served directly
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger(__name__)

# First path segment that belongs to the backend. Checked on the segment, not a
# prefix, so `/api` and `/api/anything` are both excluded from the SPA while a
# page named e.g. `/apiary` still reaches the router.
BACKEND_SEGMENTS = frozenset({"api", "ws"})
PROTECTED_PREFIXES = ("api/", "ws/")

INDEX_FILE = "index.html"


def resolve_web_root(web_dir: Path | str | None) -> Path | None:
    """Return the directory if it holds a real build, otherwise ``None``."""
    if not web_dir:
        return None
    root = Path(web_dir)
    index = root / INDEX_FILE
    if not index.is_file():
        return None
    return root


def mount_spa(app: FastAPI, web_dir: Path | str | None) -> bool:
    """Attach static SPA hosting to ``app``; report whether it was enabled."""
    root = resolve_web_root(web_dir)
    if root is None:
        logger.info("web build not found at %s; serving API only", web_dir or "<unset>")
        return False

    root = root.resolve()
    assets = root / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="ric-assets")

    index = root / INDEX_FILE

    def _within_root(candidate: Path) -> bool:
        try:
            return candidate.is_relative_to(root)
        except AttributeError:  # pragma: no cover - Python < 3.9
            return str(candidate).startswith(str(root))

    @app.get(
        "/{full_path:path}",
        response_model=None,  # returns a Response, so there is no body model
        include_in_schema=False,
        name="ric-spa-fallback",
    )
    async def spa_fallback(full_path: str) -> FileResponse | JSONResponse:
        normalised = full_path.strip("/")
        if normalised.partition("/")[0] in BACKEND_SEGMENTS:
            # An unmatched API/WS path is a JSON 404: returning index.html here
            # would make a broken endpoint look like a working page.
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        if normalised:
            candidate = (root / normalised).resolve()
            if _within_root(candidate) and candidate.is_file():
                return FileResponse(candidate)
        return FileResponse(index)

    logger.info("serving React build from %s", root)
    return True


__all__ = [
    "BACKEND_SEGMENTS",
    "INDEX_FILE",
    "PROTECTED_PREFIXES",
    "mount_spa",
    "resolve_web_root",
]
