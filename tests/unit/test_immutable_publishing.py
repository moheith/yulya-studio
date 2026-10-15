"""
Targeted tests for Immutable Release Publishing, Versioned Snapshots, Rollback,
and Draft Isolation in Yulya Studio V2 (Section 5 of Master Prompt).
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from starlette.testclient import TestClient
from pathlib import Path

from backend.app.main import app
from backend.app.core.config import settings
from backend.app.core.errors import AppError
from backend.app.projects import service
from backend.app.database import repositories


def test_create_release_snapshot_and_manifest(tmp_path, monkeypatch):
    """
    Verifies that create_release_snapshot copies project files to versioned snapshot
    and generates a release_manifest.json containing SHA-256 file hashes.
    """
    projects_dir = tmp_path / "projects"
    releases_dir = tmp_path / "releases"
    projects_dir.mkdir()
    releases_dir.mkdir()
    monkeypatch.setattr(settings, "PROJECTS_DIR", projects_dir)
    monkeypatch.setattr(settings, "RELEASES_DIR", releases_dir)

    user_id = 999
    username = "publisher"
    slug = "pixel-runner"

    # 1. Initialize starter project
    service.init_starter_project(user_id, slug, "Pixel Runner")

    # 2. Create release snapshot v1
    manifest = service.create_release_snapshot(
        user_id=user_id,
        slug=slug,
        version=1,
        title="Pixel Runner",
        description="First public release",
        changelog="Initial playable release"
    )

    assert manifest["version"] == 1
    assert manifest["slug"] == slug
    assert "file_hashes" in manifest
    assert "index.html" in manifest["file_hashes"]
    assert "app.js" in manifest["file_hashes"]
    assert "style.css" in manifest["file_hashes"]

    # Verify SHA-256 hash length
    app_js_hash = manifest["file_hashes"]["app.js"]
    assert len(app_js_hash) == 64

    # Verify files on disk in release directory
    v1_dir = releases_dir / str(user_id) / slug / "v1"
    assert v1_dir.exists()
    assert (v1_dir / "app.js").exists()
    assert (v1_dir / "release_manifest.json").exists()


def test_draft_mutation_isolation_from_published_release(tmp_path, monkeypatch):
    """
    Verifies that modifying draft files in data/projects does NOT alter previously
    published release snapshots in data/releases.
    """
    projects_dir = tmp_path / "projects"
    releases_dir = tmp_path / "releases"
    projects_dir.mkdir()
    releases_dir.mkdir()
    monkeypatch.setattr(settings, "PROJECTS_DIR", projects_dir)
    monkeypatch.setattr(settings, "RELEASES_DIR", releases_dir)

    user_id = 101
    slug = "space-drift"

    service.init_starter_project(user_id, slug, "Space Drift")
    service.create_release_snapshot(user_id, slug, 1, "Space Drift", "v1", "Initial")

    # Snapshot content before draft change
    v1_app_js = releases_dir / str(user_id) / slug / "v1" / "app.js"
    v1_content_initial = v1_app_js.read_text(encoding="utf-8")

    # Mutate draft app.js in projects directory
    draft_app_js = projects_dir / str(user_id) / slug / "app.js"
    draft_app_js.write_text("// MUTATED DRAFT CODE", encoding="utf-8")

    # Published release snapshot MUST be identical and untainted
    v1_content_after = v1_app_js.read_text(encoding="utf-8")
    assert v1_content_after == v1_content_initial
    assert "// MUTATED DRAFT CODE" not in v1_content_after


def test_public_serving_uses_published_release_never_draft(tmp_path, monkeypatch):
    """
    Verifies that public requests to /{username}/{slug}/ serve the active published release snapshot,
    never the editable working draft.
    """
    client = TestClient(app)
    projects_dir = tmp_path / "projects"
    releases_dir = tmp_path / "releases"
    projects_dir.mkdir()
    releases_dir.mkdir()
    monkeypatch.setattr(settings, "PROJECTS_DIR", projects_dir)
    monkeypatch.setattr(settings, "RELEASES_DIR", releases_dir)

    user_id = 303
    username = "gamemaker"
    slug = "tank-battle"

    service.init_starter_project(user_id, slug, "Tank Battle")
    snapshot = service.create_release_snapshot(user_id, slug, 1, "Tank Battle", "v1", "Launch")

    # Mutate draft index.html
    draft_index = projects_dir / str(user_id) / slug / "index.html"
    draft_index.write_text("<html><body>MUTATED DRAFT ONLY</body></html>", encoding="utf-8")

    # Mock DB active release as v1
    monkeypatch.setattr(repositories, "get_project_by_username_and_slug", AsyncMock(return_value={
        "user_id": user_id,
        "username": username,
        "slug": slug,
        "title": "Tank Battle"
    }))
    monkeypatch.setattr(repositories, "get_active_release", AsyncMock(return_value={
        "user_id": user_id,
        "username": username,
        "slug": slug,
        "version": 1,
        "manifest": snapshot
    }))

    # Request public game URL
    resp = client.get(f"/{username}/{slug}/")
    assert resp.status_code == 200
    # Must NOT contain mutated draft content
    assert "MUTATED DRAFT ONLY" not in resp.text
    # Must contain starter game published snapshot
    assert "Neon Dodge" in resp.text


def test_private_draft_unauthenticated_rejection(tmp_path, monkeypatch):
    """
    Verifies that accessing an unreleased private draft without authentication
    returns 403 Forbidden.
    """
    client = TestClient(app)
    projects_dir = tmp_path / "projects"
    monkeypatch.setattr(settings, "PROJECTS_DIR", projects_dir)

    user_id = 505
    username = "secretdev"
    slug = "unreleased-game"

    service.init_starter_project(user_id, slug, "Secret Game")

    monkeypatch.setattr(repositories, "get_project_by_username_and_slug", AsyncMock(return_value={
        "user_id": user_id,
        "username": username,
        "slug": slug,
        "title": "Secret Game"
    }))
    monkeypatch.setattr(repositories, "get_active_release", AsyncMock(return_value=None))

    # Unauthenticated visitor must receive 403
    resp = client.get(f"/{username}/{slug}/")
    assert resp.status_code == 403
    assert "private" in resp.text.lower()


@pytest.mark.asyncio
async def test_release_rollback(tmp_path, monkeypatch):
    """
    Verifies that release rollback changes the active version pointer to the requested
    previous version both via repository and via API endpoint.
    """
    from backend.app.database import client as db_module

    user_id = 707
    slug = "retro-arcade"

    # 1. Test repositories.rollback_release logic with mocked collection
    mock_col = MagicMock()
    mock_col.find_one = AsyncMock(return_value={
        "_id": "507f1f77bcf86cd799439011",
        "user_id": user_id,
        "slug": slug,
        "version": 1,
        "is_active": False
    })
    mock_col.update_many = AsyncMock()
    mock_col.update_one = AsyncMock()
    monkeypatch.setattr(db_module, "releases_col", mock_col)

    res = await repositories.rollback_release(user_id, slug, 1)
    assert res is not None
    assert res["is_active"] is True
    assert res["version"] == 1
    mock_col.update_many.assert_called_once()
    mock_col.update_one.assert_called_once()

    # 2. Test POST /api/releases/rollback endpoint
    client = TestClient(app)
    mock_session = {"token": "valid_token", "user": {"id": user_id, "username": "rollback_user"}}
    monkeypatch.setattr(repositories, "get_session", AsyncMock(return_value=mock_session))
    monkeypatch.setattr(repositories, "rollback_release", AsyncMock(return_value={
        "user_id": user_id,
        "slug": slug,
        "version": 1,
        "is_active": True
    }))

    client.cookies.set(settings.COOKIE_NAME, "valid_token")
    resp = client.post("/api/releases/rollback", json={"slug": slug, "target_version": 1})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["active_version"] == 1
