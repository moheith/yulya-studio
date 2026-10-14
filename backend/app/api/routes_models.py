"""
Model registry diagnostics and API key onboarding routes for Yulya Studio V2.
Follows Section 14 & Section 38 of Master Prompt.
"""

from typing import Dict, Any
from fastapi import APIRouter, Depends

from backend.app.core.errors import AppError, ErrorCategory
from backend.app.core.security import enforce_rate_limit
from backend.app.models.schemas import SaveApiKeyRequest, SetModelPreferenceRequest
from backend.app.models.registry import (
    get_registry_summary,
    validate_live_model,
    validate_code_model
)
from backend.app.api.routes_auth import require_auth
from backend.app.database import repositories

router = APIRouter(prefix="/api", tags=["Models"])


@router.get("/models")
async def api_get_models():
    """Returns the complete, authoritative list of supported Live and Code models."""
    return {
        "success": True,
        **get_registry_summary()
    }


@router.post("/save-key")
async def api_save_key(
    req: SaveApiKeyRequest,
    user: dict = Depends(require_auth)
):
    """
    Verifies user's personal Google AI Studio API key and encrypts it at rest with Fernet.
    Key is NEVER returned in response or logged.
    """
    user_id = user["id"]
    username = user["username"]
    enforce_rate_limit("save_key", str(user_id), max_req=5, window_sec=60)

    res = await repositories.save_user_api_key(
        user_id=user_id,
        api_key=req.api_key,
        username=username
    )

    if not res.get("success"):
        raise AppError(
            ErrorCategory.INVALID_INPUT,
            res.get("error", "Failed to verify Google AI Studio API key.")
        )

    return {
        "success": True,
        "message": "Google AI Studio API key verified and securely saved."
    }


@router.post("/preferences/live-model")
async def api_set_preferred_live_model(
    req: SetModelPreferenceRequest,
    user: dict = Depends(require_auth)
):
    """Sets creator's preferred Gemini Live voice model."""
    if not validate_live_model(req.model):
        raise AppError(ErrorCategory.INVALID_INPUT, f"Model '{req.model}' is not a valid or supported Live voice model.")

    await repositories.save_user_preference(user["id"], "preferred_live_model", req.model)
    return {
        "success": True,
        "preferred_live_model": req.model
    }


@router.post("/preferences/code-model")
async def api_set_preferred_code_model(
    req: SetModelPreferenceRequest,
    user: dict = Depends(require_auth)
):
    """Sets creator's preferred Antigravity code generation model."""
    if not validate_code_model(req.model):
        raise AppError(ErrorCategory.INVALID_INPUT, f"Model '{req.model}' is not a valid or supported code generation model.")

    await repositories.save_user_preference(user["id"], "preferred_code_model", req.model)
    return {
        "success": True,
        "preferred_code_model": req.model
    }
