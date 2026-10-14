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


def _get_encryption_fernet() -> Fernet:
    """Derives a deterministic 32-byte Fernet key from settings.SESSION_SECRET."""
    secret_bytes = settings.SESSION_SECRET.encode("utf-8")
    key_32 = hashlib.sha256(secret_bytes).digest()
    fernet_key = base64.urlsafe_b64encode(key_32)
    return Fernet(fernet_key)


def encrypt_secret(plaintext: str) -> str:
    """Encrypts sensitive credentials (like Google AI Studio API keys) at rest."""
    if not plaintext:
        return ""
    fernet = _get_encryption_fernet()
    token = fernet.encrypt(plaintext.encode("utf-8"))
    return f"enc_v1:{token.decode('utf-8')}"


def decrypt_secret(encrypted_text: str) -> str:
    """Decrypts credentials stored at rest. Handles legacy plaintext gracefully."""
    if not encrypted_text:
        return ""
    if not encrypted_text.startswith("enc_v1:"):
        # Legacy plaintext key
        return encrypted_text
    ciphertext = encrypted_text[len("enc_v1:"):]
    fernet = _get_encryption_fernet()
    decrypted_bytes = fernet.decrypt(ciphertext.encode("utf-8"))
    return decrypted_bytes.decode("utf-8")


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
