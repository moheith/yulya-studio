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
    """Verifies that API keys and secrets encrypt and decrypt accurately at rest with enc_v2."""
    from backend.app.core.security import migrate_encrypted_secret, _get_legacy_v1_fernet
    raw_key = "AIzaSyFakeGoogleApiKey1234567890abcdef"

    encrypted = encrypt_secret(raw_key)
    assert encrypted != raw_key
    assert encrypted.startswith("enc_v2:")
    assert len(encrypted) > 20

    decrypted = decrypt_secret(encrypted)
    assert decrypted == raw_key

    # Test backward compatibility with legacy enc_v1 format
    legacy_fernet = _get_legacy_v1_fernet()
    enc_v1_ciphertext = "enc_v1:" + legacy_fernet.encrypt(raw_key.encode("utf-8")).decode("utf-8")
    assert decrypt_secret(enc_v1_ciphertext) == raw_key

    # Test migration from enc_v1 to enc_v2
    migrated = migrate_encrypted_secret(enc_v1_ciphertext)
    assert migrated.startswith("enc_v2:")
    assert decrypt_secret(migrated) == raw_key


def test_production_secret_enforcement():
    """Verifies that Settings rejects missing, weak or placeholder SESSION_SECRET in production."""
    from pydantic import ValidationError
    from backend.app.core.config import Settings

    # In production, default/placeholder secret must fail fast
    with pytest.raises((ValueError, ValidationError)):
        Settings(
            ENVIRONMENT="production",
            SESSION_SECRET="yulya_v2_default_secret_key_change_in_production"
        )

    with pytest.raises((ValueError, ValidationError)):
        Settings(
            ENVIRONMENT="production",
            SESSION_SECRET="short_secret"
        )

    # Valid >= 32 char production secret succeeds
    valid_prod = Settings(
        ENVIRONMENT="production",
        SESSION_SECRET="prod_strong_session_secret_with_sufficient_entropy_64chars"
    )
    assert valid_prod.ENVIRONMENT == "production"


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
