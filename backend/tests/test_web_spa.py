"""Production static hosting: FastAPI serving the built React SPA.

The Pi has no Node runtime, so one process must answer the API, the WebSocket
and the browser. These tests pin the routing contract, including the two ways it
is easy to get wrong: an unknown ``/api/...`` path must not be swallowed into
``index.html``, and ``/ws/live`` must not be captured by the SPA fallback.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import get_settings
from app.web import mount_spa

INDEX_HTML = (
    "<!doctype html><html><head><title>RIC</title></head>"
    '<body><div id="root"></div><script src="/assets/app.js"></script></body></html>'
)


@pytest.fixture()
def web_dir(tmp_path):
    """A stand-in for deploy/pi/web produced by scripts\\package-pi-web.bat."""
    root = tmp_path / "web"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    (root / "assets" / "app.js").write_text("console.log('ric')", encoding="utf-8")
    (root / "favicon.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
    return root


@pytest.fixture()
def prod_client(web_dir, tmp_path):
    settings = replace(get_settings(), web_dir=web_dir, database_path=tmp_path / "web-test.db")
    app = create_app(settings)
    with TestClient(app) as client:
        yield client


@pytest.fixture()
def dev_client(tmp_path):
    """No build present - the Windows/Vite dev case."""
    settings = replace(
        get_settings(),
        web_dir=tmp_path / "does-not-exist",
        database_path=tmp_path / "dev-test.db",
    )
    with TestClient(create_app(settings)) as client:
        yield client


# ------------------------------------------------------------ SPA responses
@pytest.mark.parametrize("path", ["/", "/history", "/settings", "/analytics", "/anomalies"])
def test_client_routes_serve_the_spa(prod_client, path):
    """Every frontend route returns the app shell, not a 404."""
    response = prod_client.get(path)

    assert response.status_code == 200, path
    assert "text/html" in response.headers["content-type"]
    assert '<div id="root">' in response.text


def test_bundled_assets_are_served(prod_client):
    js = prod_client.get("/assets/app.js")
    assert js.status_code == 200
    assert "javascript" in js.headers["content-type"]
    assert "ric" in js.text

    icon = prod_client.get("/favicon.svg")
    assert icon.status_code == 200
    assert "svg" in icon.headers["content-type"]


def test_unknown_deep_link_still_loads_the_app(prod_client):
    """A refreshed deep link must fall back to the shell, not 404."""
    response = prod_client.get("/history/S260922-091952")

    assert response.status_code == 200
    assert '<div id="root">' in response.text


# ------------------------------------------------------- backend precedence
def test_api_health_is_json(prod_client):
    response = prod_client.get("/api/health")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["status"] == "ok"


def test_unknown_api_path_is_json_404_not_the_spa(prod_client):
    """The failure mode this guards: a broken endpoint rendering index.html."""
    response = prod_client.get("/api/does-not-exist")

    assert response.status_code == 404
    assert "application/json" in response.headers["content-type"]
    assert response.json() == {"detail": "Not Found"}
    assert "<div id=" not in response.text


def test_root_api_prefix_variants_are_json(prod_client):
    for path in ("/api", "/api/", "/api/sessions/nope"):
        response = prod_client.get(path)
        assert "application/json" in response.headers["content-type"], path
        assert response.status_code in (404, 422), path


def test_websocket_route_is_not_captured(prod_client):
    with prod_client.websocket_connect("/ws/live") as ws:
        envelope = ws.receive_json()

    assert envelope["type"] == "laser.snapshot"
    assert envelope["source"] == "dhj9"
    assert set(envelope) == {"type", "source", "timestamp", "payload"}


def test_docs_and_openapi_still_work(prod_client):
    assert prod_client.get("/docs").status_code == 200
    schema = prod_client.get("/openapi.json")
    assert schema.status_code == 200
    # the SPA catch-all must not pollute the API contract
    assert "/{full_path}" not in schema.json()["paths"]


# ------------------------------------------------------------------- safety
def test_path_traversal_cannot_escape_the_build(prod_client, web_dir):
    for path in ("/../secrets.txt", "/..%2Fsecrets.txt", "/%2e%2e/etc/passwd", "/./../../windows/win.ini"):
        response = prod_client.get(path)
        assert "root:" not in response.text
        assert "[version]" not in response.text
        assert response.status_code in (200, 404)
    assert (web_dir / "secrets.txt").exists() is False


# ---------------------------------------------------------------- dev paths
def test_dev_mode_without_build_keeps_json_root(dev_client):
    """Windows dev must be unaffected: no build -> API-only root."""
    response = dev_client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["health"] == "/api/health"


def test_mount_spa_reports_disabled_for_missing_dir(tmp_path):
    app = create_app(replace(get_settings(), web_dir=tmp_path / "nope"))

    assert mount_spa(app, tmp_path / "nope") is False
    assert mount_spa(app, None) is False


def test_mount_spa_needs_an_index_file(tmp_path):
    (tmp_path / "assets").mkdir()

    assert mount_spa(create_app(), tmp_path) is False
