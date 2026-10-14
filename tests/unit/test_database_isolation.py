"""
Unit tests for Database Client Test Isolation and Repository Safety.
Guarantees tests NEVER touch production MongoDB Atlas, verifies RuntimeError protections,
and tests repository data manipulation via mock collections.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from backend.app.database import client, repositories
from backend.app.core.config import settings


@pytest.mark.asyncio
async def test_test_isolation_refuses_without_test_uri(monkeypatch):
    """Verifies that init_db(is_test=True) strictly refuses to run if TEST_MONGO_URI is missing."""
    monkeypatch.setattr(settings, "TEST_MONGO_URI", None)
    with pytest.raises(RuntimeError) as exc_info:
        await client.init_db(is_test=True)

    assert "Refusing to run tests: TEST_MONGO_URI is not set" in str(exc_info.value)


@pytest.mark.asyncio
async def test_test_isolation_refuses_production_db_name(monkeypatch):
    """Verifies that init_db(is_test=True) refuses to target 'yulya_bot_db'."""
    monkeypatch.setattr(settings, "TEST_MONGO_URI", "mongodb://localhost:27017")
    monkeypatch.setattr(settings, "TEST_MONGO_DB_NAME", "yulya_bot_db")

    with pytest.raises(RuntimeError) as exc_info:
        await client.init_db(is_test=True)

    assert "Test database name cannot be 'yulya_bot_db'" in str(exc_info.value)


@pytest.mark.asyncio
async def test_repository_session_mock():
    """Verifies session storage and retrieval using mock collections."""
    mock_sessions = AsyncMock()
    mock_sessions.insert_one = AsyncMock()
    mock_sessions.find_one = AsyncMock(return_value={
        "token": "tok_12345",
        "user": {"id": 100, "username": "creator_alice"}
    })

    client.sessions_col = mock_sessions

    # Save session
    token = "tok_12345"
    await repositories.save_session(token, {"id": 100, "username": "creator_alice"})
    assert token is not None

    # Get session
    s = await repositories.get_session("tok_12345")
    assert s is not None
    assert s["user"]["username"] == "creator_alice"


@pytest.mark.asyncio
async def test_repository_project_mock():
    """Verifies project registration and listing with mock collection."""
    mock_projects = AsyncMock()
    mock_projects.update_one = AsyncMock()
    mock_cursor = MagicMock()
    mock_cursor.to_list = AsyncMock(return_value=[
        {"slug": "neon-dodge", "title": "Neon Dodge", "user_id": 100}
    ])
    mock_cursor.sort = MagicMock(return_value=mock_cursor)
    mock_projects.find = MagicMock(return_value=mock_cursor)

    client.projects_col = mock_projects

    doc = await repositories.save_project(
        user_id=100,
        username="alice",
        slug="neon-dodge",
        title="Neon Dodge",
        description="Retro runner",
        files=["index.html", "style.css", "app.js"]
    )
    assert doc["slug"] == "neon-dodge"

    projects = await repositories.list_user_projects(100)
    assert len(projects) == 1
    assert projects[0]["slug"] == "neon-dodge"
