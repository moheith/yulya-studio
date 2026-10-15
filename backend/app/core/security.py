"""
Security, session management, credential encryption, and rate limiting for Yulya Studio V2.
Follows Section 36 & Section 38 of Master Prompt.
"""

import time
import base64
import hashlib
import secrets
from typing import Dict, List, Optional, Tuple
from cryptography.fernet import Fernet
from backend.app.core.config import settings
from backend.app.core.errors import AppError, ErrorCategory


def _derive_fernet_from_secret(secret: str) -> Fernet:
    secret_bytes = secret.encode("utf-8")
    key_32 = hashlib.sha256(secret_bytes).digest()
    return Fernet(base64.urlsafe_b64encode(key_32))


def _get_primary_fernet() -> Fernet:
    """Returns Fernet instance using dedicated ENCRYPTION_KEY if provided, falling back to SESSION_SECRET."""
    if settings.ENCRYPTION_KEY:
        return _derive_fernet_from_secret(settings.ENCRYPTION_KEY)
    return _derive_fernet_from_secret(settings.SESSION_SECRET)


def _get_legacy_v1_fernet() -> Fernet:
    """Returns Fernet instance derived from SESSION_SECRET for enc_v1 decryption."""
    return _derive_fernet_from_secret(settings.SESSION_SECRET)


def encrypt_secret(plaintext: str) -> str:
    """Encrypts sensitive credentials (like Google AI Studio API keys) at rest."""
    if not plaintext:
        return ""
    fernet = _get_primary_fernet()
    token = fernet.encrypt(plaintext.encode("utf-8"))
    return f"enc_v2:{token.decode('utf-8')}"


def decrypt_secret(encrypted_text: str) -> str:
    """
    Decrypts credentials stored at rest.
    Handles enc_v2 (primary), enc_v1 (legacy session secret), and plaintext.
    """
    if not encrypted_text:
        return ""
    if encrypted_text.startswith("enc_v2:"):
        ciphertext = encrypted_text[len("enc_v2:"):]
        try:
            return _get_primary_fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
        except Exception:
            return _get_legacy_v1_fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")

    if encrypted_text.startswith("enc_v1:"):
        ciphertext = encrypted_text[len("enc_v1:"):]
        try:
            return _get_legacy_v1_fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
        except Exception:
            return _get_primary_fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")

    # Legacy plaintext key
    return encrypted_text


def migrate_encrypted_secret(encrypted_text: str, old_key: Optional[str] = None, new_key: Optional[str] = None) -> str:
    """
    Safely migrates a single encrypted secret from old_key to new_key without touching production DB.
    """
    if not encrypted_text:
        return ""
    old_secret = old_key or settings.SESSION_SECRET
    new_secret = new_key or settings.ENCRYPTION_KEY or settings.SESSION_SECRET
    old_fernet = _derive_fernet_from_secret(old_secret)
    if encrypted_text.startswith("enc_v2:"):
        raw_token = encrypted_text[len("enc_v2:"):]
    elif encrypted_text.startswith("enc_v1:"):
        raw_token = encrypted_text[len("enc_v1:"):]
    else:
        raw_token = None

    if raw_token:
        plaintext = old_fernet.decrypt(raw_token.encode("utf-8")).decode("utf-8")
    else:
        plaintext = encrypted_text

    new_fernet = _derive_fernet_from_secret(new_secret)
    new_token = new_fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")
    return f"enc_v2:{new_token}"


def generate_session_token() -> str:
    """Generates a cryptographically secure 256-bit URL-safe token."""
    return secrets.token_urlsafe(32)


# In-memory sliding window rate limiter: { "action:key": [timestamps] }
_RATE_LIMIT_BUCKETS: Dict[str, List[float]] = {}
RATE_LIMIT_BUCKETS = _RATE_LIMIT_BUCKETS


def check_rate_limit(action: str, identifier: str, max_req: int, window_sec: int) -> Tuple[bool, int]:
    """
    Sliding window rate limiter (Section 30).
    Returns (is_allowed, seconds_to_wait).
    """
    now = time.time()
    bucket_key = f"{action}:{identifier}"
    timestamps = _RATE_LIMIT_BUCKETS.get(bucket_key, [])
    # Evict timestamps older than the window
    timestamps = [t for t in timestamps if now - t < window_sec]

    if len(timestamps) >= max_req:
        oldest = timestamps[0]
        retry_after = int(window_sec - (now - oldest)) + 1
        _RATE_LIMIT_BUCKETS[bucket_key] = timestamps
        return False, max(1, retry_after)

    timestamps.append(now)
    _RATE_LIMIT_BUCKETS[bucket_key] = timestamps
    return True, 0


def enforce_rate_limit(action: str, identifier: str, max_req: int, window_sec: int) -> None:
    """Enforces rate limit and raises AppError with ErrorCategory.RATE_LIMIT if exceeded."""
    allowed, retry_after = check_rate_limit(action, identifier, max_req, window_sec)
    if not allowed:
        raise AppError(
            category=ErrorCategory.RATE_LIMIT,
            message=f"Rate limit exceeded. Please wait {retry_after} seconds before retrying.",
            status_code=429,
            details={"retry_after": retry_after}
        )
