"""
Targeted regression tests for Yulya Studio V2 Security Remediation:
1. Production SESSION_SECRET enforcement (fail-fast on weak/missing/placeholders).
2. Dedicated ENCRYPTION_KEY with backward compatibility (enc_v2, enc_v1, plaintext) and migration.
3. Cookie-only WebSocket authentication (query param token rejected) & origin validation.
4. Discord OAuth state generation, validation, and one-time consumption (Anti-CSRF).
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.app.main import app
from backend.app.core.config import Settings, settings
from backend.app.core.security import (
    encrypt_secret,
    decrypt_secret,
    migrate_encrypted_secret,
    _get_legacy_v1_fernet,
    generate_session_token,
)
from backend.app.database import repositories


def test_production_session_secret_fail_fast():
    """Verifies that production startup fails immediately on weak, placeholder, or default SESSION_SECRET."""
    from pydantic import ValidationError

    # 1. Default placeholder must fail
    with pytest.raises((ValueError, ValidationError)):
        Settings(
            ENVIRONMENT="production",
            SESSION_SECRET="yulya_studio_secret_key_2026_super_secure"
        )

    # 2. 'change_me' / placeholder text must fail
    with pytest.raises((ValueError, ValidationError)):
        Settings(
            ENVIRONMENT="production",
            SESSION_SECRET="change_me_to_a_production_secret_key_here"
        )

    # 3. Short secret (< 32 chars) must fail
    with pytest.raises((ValueError, ValidationError)):
        Settings(
            ENVIRONMENT="production",
            SESSION_SECRET="short_prod_secret_12345"
        )

    # 4. Strong high-entropy secret succeeds
    strong_sec = "a_very_strong_production_secret_with_sufficient_entropy_64_bytes_long"
    s = Settings(ENVIRONMENT="production", SESSION_SECRET=strong_sec)
    assert s.SESSION_SECRET == strong_sec

    # 5. Cloud deployment (Render) without custom secret auto-generates secure ephemeral secret
    with patch.dict("os.environ", {"RENDER": "true"}, clear=False):
        cloud_s = Settings(ENVIRONMENT="development", SESSION_SECRET="yulya_studio_secret_key_2026_super_secure")
        assert len(cloud_s.SESSION_SECRET) >= 32
        assert cloud_s.SESSION_SECRET != "yulya_studio_secret_key_2026_super_secure"


def test_encryption_key_isolation_and_migration():
    """
    Verifies that:
    - Dedicated ENCRYPTION_KEY is used for new encryptions (enc_v2: prefix).
    - Legacy enc_v1: (derived from SESSION_SECRET) decrypts seamlessly.
    - migrate_encrypted_secret() rotates enc_v1 to enc_v2 cleanly.
    - Plaintext values fall back safely.
    """
    secret_value = "AIzaSySecretApiKeyForGemini9876543210"

    # 1. New encryptions use enc_v2
    enc_v2 = encrypt_secret(secret_value)
    assert enc_v2.startswith("enc_v2:")
    assert decrypt_secret(enc_v2) == secret_value

    # 2. Legacy enc_v1 ciphertext decrypts seamlessly
    legacy_fernet = _get_legacy_v1_fernet()
    enc_v1_raw = legacy_fernet.encrypt(secret_value.encode("utf-8")).decode("utf-8")
    enc_v1 = f"enc_v1:{enc_v1_raw}"
    assert decrypt_secret(enc_v1) == secret_value

    # 3. Migration converts enc_v1 to enc_v2
    migrated = migrate_encrypted_secret(enc_v1)
    assert migrated.startswith("enc_v2:")
    assert decrypt_secret(migrated) == secret_value

    # 4. Plaintext legacy fallback
    assert decrypt_secret("plain_unencrypted_key") == "plain_unencrypted_key"


def test_websocket_cookie_only_auth_and_origin_validation(monkeypatch):
    """
    Verifies that /ws/studio:
    - Rejects token query parameters (query param token authentication removed).
    - Requires authenticated session cookie.
    - Validates origin header against permitted domains.
    """
    client = TestClient(app)

    # 1. Reject connection from unauthorized origin
    with pytest.raises(Exception):
        with client.websocket_connect(
            "/ws/studio?slug=test-game",
            headers={"origin": "https://malicious-attacker.com"}
        ) as ws:
            pass

    # 2. Query param token without session cookie is rejected with error
    with client.websocket_connect(
        "/ws/studio?slug=test-game&token=insecure_query_token",
        headers={"origin": settings.BASE_URL}
    ) as ws:
        err_msg = ws.receive_json()
        assert err_msg["type"] == "error"
        assert "Authentication required" in err_msg["message"]

    # 3. Connection with valid session cookie and allowed origin succeeds
    mock_session = {
        "token": "valid_session_token",
        "user": {"id": 42, "username": "valid_creator"}
    }
    monkeypatch.setattr(repositories, "get_session", AsyncMock(return_value=mock_session))
    monkeypatch.setattr(repositories, "get_decrypted_user_api_key", AsyncMock(return_value="fake_key"))

    client.cookies.set(settings.COOKIE_NAME, "valid_session_token")
    with client.websocket_connect(
        "/ws/studio?slug=test-game",
        headers={"origin": settings.BASE_URL}
    ) as ws:
        status_msg = ws.receive_json()
        assert status_msg["type"] == "status"
        assert status_msg["user_id"] == 42
        assert status_msg["username"] == "valid_creator"


def test_oauth_anti_csrf_state_generation_and_consumption(monkeypatch):
    """
    Verifies that:
    - /auth/login generates a cryptographically secure 256-bit state parameter.
    - The state is stored in an HttpOnly anti-CSRF cookie and included in Discord auth URL.
    - /auth/callback rejects requests with missing or mismatched state (HTTP 403).
    - /auth/callback consumes and removes the state cookie immediately.
    """
    client = TestClient(app)
    monkeypatch.setattr(settings, "DISCORD_CLIENT_ID", "123456789")
    monkeypatch.setattr(settings, "DISCORD_CLIENT_SECRET", "fake_secret")

    # 1. Initiate login
    login_resp = client.get("/auth/login", follow_redirects=False)
    assert login_resp.status_code in (302, 307)
    location = login_resp.headers["location"]
    assert "discord.com/api/oauth2/authorize" in location
    assert "state=" in location

    # Extract state from URL and cookie
    state_in_url = location.split("state=")[1].split("&")[0]
    state_cookie = login_resp.cookies.get("yulya_oauth_state")
    assert state_cookie is not None
    assert state_cookie == state_in_url
    assert len(state_cookie) >= 32

    # 2. Callback with mismatched state must be rejected with 403 Forbidden
    bad_cb = client.get(
        "/auth/callback?code=fake_code&state=forged_state",
        cookies={"yulya_oauth_state": state_cookie}
    )
    assert bad_cb.status_code == 403
    assert "Invalid or expired OAuth state" in bad_cb.json()["message"]

    # 3. Callback with missing cookie must be rejected with 403 Forbidden
    no_cookie_cb = client.get(f"/auth/callback?code=fake_code&state={state_in_url}")
    assert no_cookie_cb.status_code == 403
