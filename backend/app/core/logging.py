"""
Structured logging and secret redaction for Yulya Studio V2.
Enforces audit logging, correlation IDs, and absolute credential redaction.
"""

import re
import sys
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

# Secret redaction patterns
REDACTION_PATTERNS = [
    re.compile(r'(?i)(AIza[0-9A-Za-z\-_]{35})'),
    re.compile(r'(?i)(AQ\.[0-9A-Za-z\-_]{20,})'),
    re.compile(r'(?i)(bearer\s+[0-9a-zA-Z\-_.]+)', re.IGNORECASE),
    re.compile(r'(?i)(mongodb(?:\+srv)?:\/\/[^@]+@)'),
    re.compile(r'(?i)(session_secret["\']?\s*[:=]\s*["\']?[^"\'\s]+)'),
    re.compile(r'(?i)(client_secret["\']?\s*[:=]\s*["\']?[^"\'\s]+)'),
]

def redact_secrets(message: str) -> str:
    """Scrubs API keys, passwords, and tokens from any text string."""
    if not isinstance(message, str):
        message = str(message)
    sanitized = message
    for pattern in REDACTION_PATTERNS:
        sanitized = pattern.sub("[REDACTED_CREDENTIAL]", sanitized)
    return sanitized


class StructuredJsonFormatter(logging.Formatter):
    """Formats log records as structured JSON with automatic secret redaction."""

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_secrets(record.getMessage()),
        }

        # Attach custom contextual fields if provided
        for attr in ("channel", "request_id", "build_id", "session_id", "user_id", "slug", "event_id"):
            if hasattr(record, attr):
                payload[attr] = getattr(record, attr)

        if record.exc_info:
            payload["exception"] = redact_secrets(self.formatException(record.exc_info))

        return json.dumps(payload)


def setup_logger(name: str = "yulya_studio") -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(StructuredJsonFormatter())
        logger.addHandler(handler)
    return logger


logger = setup_logger()


def log_event(
    message: str,
    level: str = "info",
    channel: str = "system",
    request_id: Optional[str] = None,
    build_id: Optional[str] = None,
    session_id: Optional[str] = None,
    user_id: Optional[int] = None,
    slug: Optional[str] = None,
    **extra: Any
) -> None:
    """Convenience helper for emitting structured, secret-safe event logs."""
    lvl = getattr(logging, level.upper(), logging.INFO)
    extra_dict: Dict[str, Any] = {
        "channel": channel,
        "request_id": request_id,
        "build_id": build_id,
        "session_id": session_id,
        "user_id": user_id,
        "slug": slug,
        **extra
    }
    logger.log(lvl, redact_secrets(message), extra=extra_dict)
