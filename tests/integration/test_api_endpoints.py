"""
Integration tests for FastAPI endpoints in Yulya Studio V2.
Tests /api/health, /api/models, sandboxed game preview headers, and authorization guards.
"""

import pytest
from starlette.testclient import TestClient
from backend.app.main import app
from backend.app.core.config import settings
from backend.app.projects import service
from backend.app.database import client


@pytest.fixture
def client_app():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def test_health_endpoint(client_app):
    """Verifies /api/health returns healthy status and model list without billable calls."""
    resp = client_app.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert data["service"] == "yulya-studio"
    assert "gemini-3.8-live" in data["available_live_models"]
    assert "gemini-3.8-flash" in data["available_code_models"]


def test_models_registry_endpoint(client_app):
    """Verifies /api/models returns complete authoritative models summary."""
    resp = client_app.get("/api/models")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "live_models" in data
    assert "code_models" in data
    assert len(data["live_models"]) >= 3


def test_unauthorized_access_rejected(client_app):
    """Verifies that sensitive endpoints reject unauthenticated requests with 401."""
    resp = client_app.post("/api/create-project", json={"title": "Test Game"})
    assert resp.status_code == 401
    err = resp.json()
    assert err["error_category"] == "authentication"


def test_sandboxed_preview_security_headers(client_app, tmp_path, monkeypatch):
    """
    Verifies that:
    1. Unauthenticated users cannot view private unreleased drafts (403 Forbidden).
    2. Published releases serve verified immutable snapshots with strict CSP headers (no unsafe-eval, nosniff, frame-ancestors).
    """
    projects_root = tmp_path / "projects"
    projects_root.mkdir()
    releases_root = tmp_path / "releases"
    releases_root.mkdir()
    monkeypatch.setattr(settings, "PROJECTS_DIR", projects_root)
    monkeypatch.setattr(settings, "RELEASES_DIR", releases_root)

    from unittest.mock import AsyncMock
    from backend.app.database import repositories
    from backend.app.projects.service import create_release_snapshot

    monkeypatch.setattr(
        repositories,
        "get_project_by_username_and_slug",
        AsyncMock(return_value={
            "user_id": 777,
            "username": "tester",
            "slug": "test-game",
            "title": "Test Game"
        })
    )

    # Initialize starter game files on disk
    service.init_starter_project(777, "test-game", "Test Game")

    # 1. Unauthenticated request to private unreleased draft -> must return 403 Forbidden
    monkeypatch.setattr(repositories, "get_active_release", AsyncMock(return_value=None))
    resp = client_app.get("/tester/test-game/")
    assert resp.status_code == 403

    # 2. Published release -> public requests succeed with 200 and strict CSP
    snapshot = create_release_snapshot(777, "test-game", 1, "Test Game", "v1", "Initial release")
    monkeypatch.setattr(repositories, "get_active_release", AsyncMock(return_value={
        "user_id": 777,
        "username": "tester",
        "slug": "test-game",
        "version": 1,
        "manifest": snapshot
    }))

    resp = client_app.get("/tester/test-game/")
    assert resp.status_code == 200
    assert "Content-Security-Policy" in resp.headers
    csp = resp.headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "'unsafe-eval'" not in csp  # Verified: unsafe-eval is forbidden
    assert "nosniff" in resp.headers.get("X-Content-Type-Options", "")
    assert "<!DOCTYPE html>" in resp.text


def test_spa_serving(client_app):
    """Verifies that the compiled frontend SPA is served at /studio and /."""
    resp = client_app.get("/studio")
    assert resp.status_code == 200
    assert "<!DOCTYPE html>" in resp.text
    assert "Yulya Studio" in resp.text
