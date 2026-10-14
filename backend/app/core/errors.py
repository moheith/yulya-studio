"""
Standard Error Taxonomy and Application Exceptions for Yulya Studio V2.
Follows Section 64 of Master Prompt for safe, structured failure reporting.
"""

from enum import Enum
from typing import Optional, Dict, Any
from fastapi import HTTPException


class ErrorCategory(str, Enum):
    AUTHENTICATION = "authentication"
    PERMISSION_DENIED = "permission_denied"
    INVALID_INPUT = "invalid_input"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PROVIDER_QUOTA = "provider_quota"
    TIMEOUT = "timeout"
    STALE_VERSION = "stale_version"
    BUILD_VALIDATION = "build_validation"
    PREVIEW_RUNTIME = "preview_runtime"
    STORAGE_FAILURE = "storage_failure"
    CONFLICT = "conflict"
    RATE_LIMIT = "rate_limit"
    INTERNAL_ERROR = "internal_error"


class AppError(Exception):
    """Base application exception with structured error categories and safe messaging."""

    def __init__(
        self,
        category: ErrorCategory,
        message: str,
        status_code: int = 400,
        correlation_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        recoverable: bool = False
    ):
        super().__init__(message)
        self.category = category
        self.message = message
        self.status_code = status_code
        self.correlation_id = correlation_id
        self.details = details or {}
        self.recoverable = recoverable

    def to_dict(self) -> Dict[str, Any]:
        res: Dict[str, Any] = {
            "success": False,
            "error_category": self.category.value,
            "message": self.message,
            "recoverable": self.recoverable
        }
        if self.correlation_id:
            res["correlation_id"] = self.correlation_id
        if self.details:
            res["details"] = self.details
        return res

    def to_http_exception(self) -> HTTPException:
        return HTTPException(
            status_code=self.status_code,
            detail=self.to_dict()
        )
