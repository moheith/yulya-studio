"""
Sandboxed game preview and static asset serving for Yulya Studio V2.
Enforces strict origin isolation, CSP headers, and path traversal protection (Sections 27, 29, 30).
"""

import mimetypes
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Response, Request
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

router = APIRouter(prefix="", tags=["Preview"])

# Restrictive Content Security Policy for game previews
PREVIEW_CSP = (
    "default-src 'self' data: blob: https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' data: https://fonts.gstatic.com; "
    "img-src 'self' data: blob: *; "
    "media-src 'self' data: blob: *; "
    "connect-src 'self' data: blob:; "
    "frame-ancestors 'self' *;"
)


def _apply_preview_security_headers(response: Response) -> None:
    """Applies strict security headers preventing parent frame tampering."""
    response.headers["Content-Security-Policy"] = PREVIEW_CSP
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"


@router.get("/{username}/{slug}")
async def handle_game_redirect(username: str, slug: str):
    """Redirects /{username}/{slug} to /{username}/{slug}/ for proper relative path resolution."""
    return RedirectResponse(url=f"/{username}/{slug}/", status_code=301)


@router.get("/{username}/{slug}/")
async def handle_game_index(username: str, slug: str):
    """Serves the game entrypoint index.html with sandboxed security headers."""
    safe_slug = validate_slug(slug)
    project = await repositories.get_project_by_username_and_slug(username, safe_slug)
    if not project:
        raise AppError(ErrorCategory.INVALID_INPUT, "Game not found.", status_code=404)

    user_id = project["user_id"]
    project_dir = service.resolve_project_path(user_id, safe_slug)
    index_file = service.resolve_file_path(project_dir, "index.html")

    if not index_file.exists():
        raise AppError(ErrorCategory.BUILD_VALIDATION, "Game entrypoint 'index.html' not found.", status_code=404)

    content = index_file.read_text(encoding="utf-8")
    resp = Response(content=content, media_type="text/html; charset=utf-8")
    _apply_preview_security_headers(resp)
    return resp


@router.get("/{username}/{slug}/{file_path:path}")
async def handle_game_asset(username: str, slug: str, file_path: str):
    """Serves static game assets (JS, CSS, images, audio, GLTF) with strict path traversal checking."""
    safe_slug = validate_slug(slug)
    project = await repositories.get_project_by_username_and_slug(username, safe_slug)
    if not project:
        raise AppError(ErrorCategory.INVALID_INPUT, "Game not found.", status_code=404)

    user_id = project["user_id"]
    project_dir = service.resolve_project_path(user_id, safe_slug)
    target_file = service.resolve_file_path(project_dir, file_path)

    if not target_file.exists() or not target_file.is_file():
        raise AppError(ErrorCategory.INVALID_INPUT, f"Asset '{file_path}' not found.", status_code=404)

    mime_type, _ = mimetypes.guess_type(target_file.name)
    if not mime_type:
        ext = target_file.suffix.lower()
        if ext == ".js" or ext == ".mjs":
            mime_type = "application/javascript"
        elif ext == ".css":
            mime_type = "text/css"
        elif ext == ".gltf":
            mime_type = "model/gltf+json"
        elif ext == ".glb":
            mime_type = "model/gltf-binary"
        else:
            mime_type = "application/octet-stream"

    resp = FileResponse(path=str(target_file), media_type=mime_type)
    _apply_preview_security_headers(resp)
    return resp
