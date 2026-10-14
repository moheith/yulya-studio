"""
Project management and editing API routes for Yulya Studio V2.
Follows Section 18 of Master Prompt.
"""

from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import StreamingResponse

from backend.app.core.config import settings
from backend.app.core.errors import AppError, ErrorCategory
from backend.app.core.security import enforce_rate_limit
from backend.app.models.schemas import (
    CreateProjectRequest,
    ModifyProjectRequest,
    DeleteProjectRequest
)
from backend.app.api.routes_auth import require_auth
from backend.app.database import repositories
from backend.app.projects import service
from backend.app.projects.sanitizer import validate_slug
from backend.app.ai import orchestrator

router = APIRouter(prefix="/api", tags=["Projects"])


@router.post("/create-project")
async def api_create_project(
    req: CreateProjectRequest,
    user: dict = Depends(require_auth)
):
    """Creates a new game repository with standard playable starter files."""
    user_id = user["id"]
    username = user["username"]
    enforce_rate_limit("create_project", str(user_id), max_req=5, window_sec=60)

    slug = req.slug or req.title.lower().replace(" ", "-")
    safe_slug = validate_slug(slug)

    # Check if project already exists for this user
    existing = await repositories.get_project(user_id, safe_slug)
    if existing:
        raise AppError(
            ErrorCategory.CONFLICT,
            f"A project with slug '{safe_slug}' already exists in your account.",
            status_code=409
        )

    # Initialize filesystem starter files
    service.init_starter_project(user_id, safe_slug, req.title)

    # Register project in database
    files = list(service.get_project_files(user_id, safe_slug).keys())
    project_doc = await repositories.save_project(
        user_id=user_id,
        username=username,
        slug=safe_slug,
        title=req.title,
        description=req.description or "",
        files=files,
        tags=req.tags or ["game", "canvas"]
    )

    return {
        "success": True,
        "message": f"Project '{safe_slug}' created successfully.",
        "project": project_doc
    }


@router.post("/modify-project")
async def api_modify_project(
    req: ModifyProjectRequest,
    user: dict = Depends(require_auth)
):
    """Triggers the autonomous Game Coding Agent to modify an existing project."""
    user_id = user["id"]
    username = user["username"]
    safe_slug = validate_slug(req.slug)
    enforce_rate_limit("modify_project", f"{user_id}:{safe_slug}", max_req=10, window_sec=60)

    # Enforce ownership check
    project = await repositories.get_project(user_id, safe_slug)
    if not project:
        raise AppError(ErrorCategory.PERMISSION_DENIED, "Project not found or not owned by you.", status_code=404)

    # Dispatch to orchestrator
    result = await orchestrator.execute_build_task(
        user_id=user_id,
        username=username,
        slug=safe_slug,
        prompt=req.prompt,
        requested_model=req.requested_model,
        source="api"
    )
    return result


@router.post("/delete-project")
async def api_delete_project(
    req: DeleteProjectRequest,
    user: dict = Depends(require_auth)
):
    """Deletes a game project and its files completely."""
    user_id = user["id"]
    safe_slug = validate_slug(req.slug)

    deleted = await repositories.delete_project(user_id, safe_slug)
    if not deleted:
        raise AppError(ErrorCategory.INVALID_INPUT, "Project not found or could not be deleted.", status_code=404)

    # Remove project directory
    try:
        project_dir = service.resolve_project_path(user_id, safe_slug)
        import shutil
        if project_dir.exists():
            shutil.rmtree(project_dir)
    except Exception:
        pass

    return {
        "success": True,
        "message": f"Project '{safe_slug}' deleted successfully."
    }


@router.get("/project-files/{slug}")
async def api_get_project_files(
    slug: str,
    user: dict = Depends(require_auth)
):
    """Retrieves all source code and files for editing in Monaco."""
    user_id = user["id"]
    safe_slug = validate_slug(slug)

    # Ensure starter project exists if user is accessing project for first time
    project_dir = service.resolve_project_path(user_id, safe_slug)
    if not project_dir.exists():
        service.init_starter_project(user_id, safe_slug)

    files = service.get_project_files(user_id, safe_slug)
    file_tree = service.list_project_files(user_id, safe_slug)
    manifest = service.load_manifest(project_dir)

    return {
        "success": True,
        "slug": safe_slug,
        "files": files,
        "tree": file_tree,
        "manifest": manifest
    }


@router.post("/save-file")
async def api_save_file(
    payload: Dict[str, Any],
    user: dict = Depends(require_auth)
):
    """Saves direct code edits made by the creator in Monaco Editor."""
    user_id = user["id"]
    slug = payload.get("slug")
    file_path = payload.get("file_path")
    content = payload.get("content")

    if not slug or not file_path or content is None:
        raise AppError(ErrorCategory.INVALID_INPUT, "Missing slug, file_path, or content.")

    safe_slug = validate_slug(slug)
    service.write_project_file(user_id, safe_slug, file_path, content)

    return {
        "success": True,
        "file_path": file_path,
        "message": "File saved successfully."
    }


@router.get("/my-projects")
async def api_list_my_projects(user: dict = Depends(require_auth)):
    """Lists all projects owned by the currently authenticated creator."""
    projects = await repositories.list_user_projects(user["id"])
    return {
        "success": True,
        "projects": projects
    }


@router.get("/download-zip/{username}/{slug}")
async def api_download_zip(username: str, slug: str):
    """Exports a validated ZIP archive of the public project files."""
    safe_slug = validate_slug(slug)
    project = await repositories.get_project_by_username_and_slug(username, safe_slug)
    if not project:
        raise AppError(ErrorCategory.INVALID_INPUT, "Project not found.", status_code=404)

    user_id = project["user_id"]
    zip_buffer = service.export_project_zip(user_id, safe_slug)

    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={safe_slug}.zip"}
    )
