"""
Sandboxed game preview and static asset serving for Yulya Studio V2.
Enforces strict origin isolation, secure CSP headers, path traversal protection,
and immutable release serving (Sections 27, 29, 30, 59).
"""

import mimetypes
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Response, Request, Depends
from fastapi.responses import FileResponse, RedirectResponse

from backend.app.core.config import settings
from backend.app.core.errors import AppError, ErrorCategory
from backend.app.database import repositories
from backend.app.projects import service
from backend.app.projects.sanitizer import (
    resolve_project_path,
    resolve_file_path,
    validate_slug
)
from backend.app.api.routes_auth import get_current_user

router = APIRouter(prefix="", tags=["Preview"])

# Restrictive Content Security Policy for game previews (no unsafe-eval, no wildcard origins)
PREVIEW_CSP = (
    "default-src 'self' data: blob: https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; "
    "script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' data: https://fonts.gstatic.com; "
    "img-src 'self' data: blob: https:; "
    "media-src 'self' data: blob: https:; "
    "connect-src 'self' data: blob:; "
    f"frame-ancestors 'self' {settings.BASE_URL};"
)


def _apply_preview_security_headers(response: Response, mode: str = "published", version: Optional[int] = None) -> None:
    """Applies strict security headers preventing parent frame tampering."""
    response.headers["Content-Security-Policy"] = PREVIEW_CSP
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["X-Yulya-Preview-Mode"] = mode
    if version:
        response.headers["X-Yulya-Release-Version"] = str(version)


RESERVED_ROOT_PATHS = {
    "api", "static", "assets", "studio", "auth", "ws", "docs", "redoc", "openapi.json", "favicon.ico", "arcade", "profile", "settings", "releases"
}


@router.get("/{username}/{slug}")
async def handle_game_redirect(username: str, slug: str):
    """Redirects /{username}/{slug} to /{username}/{slug}/ for proper relative path resolution."""
    if username.lower() in RESERVED_ROOT_PATHS:
        raise AppError(ErrorCategory.INVALID_INPUT, f"Reserved system route: '{username}'", status_code=404)
    return RedirectResponse(url=f"/{username}/{slug}/", status_code=301)


@router.get("/{username}/{slug}/")
async def handle_game_index(request: Request, username: str, slug: str):
    """
    Serves the game entrypoint index.html.
    If an active published release exists, serves from the immutable release snapshot.
    If no release exists, only the authenticated project owner can access the draft.
    """
    if username.lower() in RESERVED_ROOT_PATHS:
        raise AppError(ErrorCategory.INVALID_INPUT, f"Reserved system route: '{username}'", status_code=404)

    safe_slug = validate_slug(slug)
    project = await repositories.get_project_by_username_and_slug(username, safe_slug)
    if not project:
        raise AppError(ErrorCategory.INVALID_INPUT, "Game not found.", status_code=404)

    user_id = project["user_id"]

    # 1. Check for active immutable published release
    active_release = await repositories.get_active_release(username, safe_slug)
    if active_release:
        version = active_release["version"]
        target_file = service.resolve_release_file_path(user_id, safe_slug, version, "index.html")
        if not target_file.exists():
            raise AppError(ErrorCategory.BUILD_VALIDATION, "Release entrypoint 'index.html' not found.", status_code=404)
        content = target_file.read_text(encoding="utf-8")
        resp = Response(content=content, media_type="text/html; charset=utf-8")
        _apply_preview_security_headers(resp, mode="published", version=version)
        return resp

    # 2. No active release: Only authenticated project owner can preview private draft
    current_user = await get_current_user(request)
    if not current_user or current_user.get("id") != user_id:
        raise AppError(
            ErrorCategory.PERMISSION_DENIED,
            "This game draft is private and has not yet been published by the creator.",
            status_code=403
        )

    project_dir = service.resolve_project_path(user_id, safe_slug)
    index_file = service.resolve_file_path(project_dir, "index.html")
    if not index_file.exists():
        raise AppError(ErrorCategory.BUILD_VALIDATION, "Game entrypoint 'index.html' not found.", status_code=404)

    content = index_file.read_text(encoding="utf-8")
    resp = Response(content=content, media_type="text/html; charset=utf-8")
    _apply_preview_security_headers(resp, mode="draft")
    return resp


@router.get("/{username}/{slug}/{file_path:path}")
async def handle_game_asset(request: Request, username: str, slug: str, file_path: str):
    """
    Serves game assets (JS, CSS, images, audio, GLTF).
    If an active release exists, serves from the immutable release snapshot.
    If no release exists, only the authenticated project owner can access draft assets.
    """
    if username.lower() in RESERVED_ROOT_PATHS:
        raise AppError(ErrorCategory.INVALID_INPUT, f"Reserved system route: '{username}'", status_code=404)

    safe_slug = validate_slug(slug)
    project = await repositories.get_project_by_username_and_slug(username, safe_slug)
    if not project:
        raise AppError(ErrorCategory.INVALID_INPUT, "Game not found.", status_code=404)

    user_id = project["user_id"]

    # 1. Check for active immutable published release
    active_release = await repositories.get_active_release(username, safe_slug)
    if active_release:
        version = active_release["version"]
        target_file = service.resolve_release_file_path(user_id, safe_slug, version, file_path)
        mode = "published"
    else:
        # Check authentication for draft
        current_user = await get_current_user(request)
        if not current_user or current_user.get("id") != user_id:
            raise AppError(
                ErrorCategory.PERMISSION_DENIED,
                "This game draft is private and has not yet been published.",
                status_code=403
            )
        project_dir = service.resolve_project_path(user_id, safe_slug)
        target_file = service.resolve_file_path(project_dir, file_path)
        mode = "draft"

    if not target_file.exists() or not target_file.is_file():
        raise AppError(ErrorCategory.INVALID_INPUT, f"Asset '{file_path}' not found.", status_code=404)

    mime_type, _ = mimetypes.guess_type(target_file.name)
    if not mime_type:
        ext = target_file.suffix.lower()
        if ext in {".js", ".mjs"}:
            mime_type = "application/javascript"
        elif ext == ".css":
            mime_type = "text/css"
        elif ext == ".gltf":
            mime_type = "model/gltf+json"
        elif ext == ".glb":
            mime_type = "model/gltf-binary"
        else:
            mime_type = "application/octet-stream"

    resp = FileResponse(target_file, media_type=mime_type)
    _apply_preview_security_headers(resp, mode=mode, version=active_release.get("version") if active_release else None)
    return resp


@router.get("/releases/{username}/{slug}/v{version}/{file_path:path}")
@router.get("/releases/{username}/{slug}/v{version}/")
async def handle_historical_release(username: str, slug: str, version: int, file_path: str = "index.html"):
    """Serves a specific historical immutable release version."""
    safe_slug = validate_slug(slug)
    project = await repositories.get_project_by_username_and_slug(username, safe_slug)
    if not project:
        raise AppError(ErrorCategory.INVALID_INPUT, "Game not found.", status_code=404)

    user_id = project["user_id"]
    clean_path = file_path if file_path and file_path != "/" else "index.html"
    target_file = service.resolve_release_file_path(user_id, safe_slug, version, clean_path)

    if not target_file.exists() or not target_file.is_file():
        raise AppError(ErrorCategory.INVALID_INPUT, f"Release v{version} asset '{clean_path}' not found.", status_code=404)

    mime_type, _ = mimetypes.guess_type(target_file.name)
    if not mime_type:
        mime_type = "text/html; charset=utf-8" if target_file.suffix.lower() == ".html" else "application/octet-stream"

    resp = FileResponse(target_file, media_type=mime_type)
    _apply_preview_security_headers(resp, mode="historical", version=version)
    return resp
