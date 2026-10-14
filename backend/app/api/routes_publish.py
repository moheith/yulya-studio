"""
Publishing and release management API routes for Yulya Studio V2.
Enforces the explicit separation between working drafts and published public releases (Section 59).
"""

from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends

from backend.app.core.errors import AppError, ErrorCategory
from backend.app.core.security import enforce_rate_limit
from backend.app.models.schemas import PublishReleaseRequest
from backend.app.api.routes_auth import require_auth
from backend.app.database import repositories
from backend.app.projects import service
from backend.app.projects.sanitizer import validate_slug

router = APIRouter(prefix="/api/releases", tags=["Publishing"])


@router.post("/publish")
async def api_publish_release(
    req: PublishReleaseRequest,
    user: dict = Depends(require_auth)
):
    """
    Explicitly publishes an immutable public game release.
    Draft edits do not automatically affect the public URL until published here.
    """
    user_id = user["id"]
    username = user["username"]
    safe_slug = validate_slug(req.slug)
    enforce_rate_limit("publish_release", f"{user_id}:{safe_slug}", max_req=10, window_sec=60)

    project = await repositories.get_project(user_id, safe_slug)
    if not project:
        raise AppError(ErrorCategory.PERMISSION_DENIED, "Project not found or not owned by you.", status_code=404)

    # 1. Verify project has valid index.html
    files = service.get_project_files(user_id, safe_slug)
    if not files.get("index.html"):
        raise AppError(
            ErrorCategory.BUILD_VALIDATION,
            "Cannot publish: game entrypoint 'index.html' is missing or empty."
        )

    # 2. Record immutable release in database
    title = req.title or project.get("title", safe_slug)
    description = req.description or project.get("description", "")
    all_files_list = list(files.keys())

    release = await repositories.publish_release(
        user_id=user_id,
        username=username,
        slug=safe_slug,
        title=title,
        description=description,
        files=all_files_list,
        changelog=req.changelog or "Initial release"
    )

    return {
        "success": True,
        "message": f"Version {release['version']} of '{safe_slug}' published successfully.",
        "release": release,
        "public_url": f"/{username}/{safe_slug}/"
    }


@router.get("/{slug}")
async def api_get_project_releases(
    slug: str,
    user: dict = Depends(require_auth)
):
    """Lists all release versions and deployment history for a project."""
    user_id = user["id"]
    safe_slug = validate_slug(slug)
    releases = await repositories.list_releases(user_id, safe_slug)
    return {
        "success": True,
        "slug": safe_slug,
        "releases": releases
    }
