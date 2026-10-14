"""
Health and readiness diagnostics for Yulya Studio V2.
Follows Section 45 of Master Prompt.
"""

from typing import Dict, Any
from fastapi import APIRouter
from google import genai

from backend.app.core.config import settings
from backend.app.database import client
from backend.app.models.registry import (
    DEFAULT_LIVE_MODEL_ID,
    DEFAULT_CODE_MODEL_ID,
    get_live_models,
    get_code_models
)

router = APIRouter(prefix="/api", tags=["Health"])


@router.get("/health")
async def api_health() -> Dict[str, Any]:
    """
    Returns application process health, database connectivity, and model configuration.
    Never initiates billable provider requests on polling (Section 45).
    """
    db_connected = client.db is not None
    sdk_version = getattr(genai, "__version__", "unknown")

    return {
        "status": "healthy",
        "service": "yulya-studio",
        "version": "2.0.0",
        "database_connected": db_connected,
        "google_genai_version": sdk_version,
        "default_live_model": DEFAULT_LIVE_MODEL_ID,
        "default_code_model": DEFAULT_CODE_MODEL_ID,
        "available_live_models": [m.id for m in get_live_models()],
        "available_code_models": [m.id for m in get_code_models()],
        "storage_ready": settings.PROJECTS_DIR.exists()
    }
