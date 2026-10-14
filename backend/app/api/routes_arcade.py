"""
Community Arcade and Creator Portfolio API routes for Yulya Studio V2.
Follows Section 61 of Master Prompt.
"""

from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Query

from backend.app.core.errors import AppError, ErrorCategory
from backend.app.database import repositories

router = APIRouter(prefix="/api", tags=["Arcade"])


@router.get("/community-projects")
async def api_get_community_projects(
    limit: int = Query(50, ge=1, le=100),
    skip: int = Query(0, ge=0)
):
    """Retrieves published public games for the community arcade."""
    projects = await repositories.list_community_projects(limit=limit, skip=skip)
    return {
        "success": True,
        "count": len(projects),
        "projects": projects
    }


@router.get("/profile/{username}")
async def api_get_public_profile(username: str):
    """Retrieves public creator profile and portfolio games."""
    profile = await repositories.get_profile_by_username(username)
    if not profile:
        raise AppError(ErrorCategory.INVALID_INPUT, f"Creator @{username} not found.", status_code=404)

    return {
        "success": True,
        "profile": profile
    }
