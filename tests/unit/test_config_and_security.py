"""
Unit tests for Core Configuration and Security utilities in Yulya Studio V2.
Tests Settings, boundary values, Fernet envelope encryption, rate limiting, and token generation.
"""

import time
import pytest
from backend.app.core.config import Settings
from backend.app.core.security import (
    encrypt_secret,
    decrypt_secret,
    generate_session_token,
    enforce_rate_limit,
    RATE_LIMIT_BUCKETS
)
from backend.app.core.errors import AppError, ErrorCategory


def test_settings_initialization(tmp_path):
    """Verifies settings load safe defaults, paths, and extension boundaries."""
    s = Settings(
        PORT=10001,
        BASE_URL="https://project.yulya.me",
        DATA_DIR=tmp_path / "data",
        PROJECTS_DIR=tmp_path / "data" / "projects",
        STATIC_DIR=tmp_path / "static",
        FRONTEND_DIST_DIR=tmp_path / "frontend" / "dist"
    )
    assert s.PORT == 10001
    assert s.COOKIE_SECURE is True
    assert s.PROJECTS_DIR.exists()
    assert ".html" in s.ALLOWED_GAME_EXTENSIONS
    assert ".js" in s.ALLOWED_GAME_EXTENSIONS
    assert ".py" in s.DISALLOWED_EXTENSIONS
    assert ".env" in s.PROTECTED_FILENAMES
    assert "requirements.txt" in s.PROTECTED_FILENAMES


def test_fernet_envelope_encryption_roundtrip():
    """Verifies that API keys and secrets encrypt and decrypt accurately at rest."""
    raw_key = "AIzaSyFakeGoogleApiKey1234567890abcdef"

    encrypted = encrypt_secret(raw_key)
    assert encrypted != raw_key
    assert encrypted.startswith("enc_v1:")
    assert len(encrypted) > 20

    decrypted = decrypt_secret(encrypted)
    assert decrypted == raw_key


def test_fernet_legacy_plaintext_compatibility():
    """Verifies that legacy unencrypted keys are returned without crashing."""
    raw_key = "AIzaSyLegacyKey"
    assert decrypt_secret(raw_key) == raw_key


def test_fernet_empty_secret():
    """Verifies empty secret handling."""
    assert encrypt_secret("") == ""
    assert decrypt_secret("") == ""


def test_session_token_generation():
    """Verifies session tokens are cryptographically secure, url-safe, and unique."""
    tokens = {generate_session_token() for _ in range(100)}
    assert len(tokens) == 100
    for tok in tokens:
        assert len(tok) >= 40
        assert "/" not in tok
        assert "+" not in tok


def test_sliding_window_rate_limiter():
    """Verifies rate limiter enforces bounds and raises 429 when quota is exceeded."""
    RATE_LIMIT_BUCKETS.clear()
    action = "test_action"
    key = "user_123"

    # Should allow 3 requests
    enforce_rate_limit(action, key, max_req=3, window_sec=10)
    enforce_rate_limit(action, key, max_req=3, window_sec=10)
    enforce_rate_limit(action, key, max_req=3, window_sec=10)

    # 4th request must be rejected with RATE_LIMIT
    with pytest.raises(AppError) as exc_info:
        enforce_rate_limit(action, key, max_req=3, window_sec=10)

    assert exc_info.value.category == ErrorCategory.RATE_LIMIT
    assert exc_info.value.status_code == 429
