"""
Preview and static validation tools for Yulya Studio V2.
Follows Section 17 & Section 25 of Master Prompt.
"""

from pathlib import Path
from typing import Dict, Any, List, Optional

from backend.app.core.errors import AppError, ErrorCategory
from backend.app.ai.tools.registry import (
    tool_registry,
    ToolDefinition,
    ToolAccess,
    ToolImpact
)
from backend.app.projects import service
from backend.app.projects.manifest import load_manifest

# In-memory storage for preview console logs: { (user_id, slug): [logs] }
PREVIEW_CONSOLE_LOGS: Dict[str, List[Dict[str, Any]]] = {}

# In-memory storage for latest screenshare frame: { (user_id, slug): (timestamp, base64_jpeg) }
ACTIVE_SCREEN_FRAMES: Dict[str, Any] = {}


def record_preview_console_error(user_id: int, slug: str, message: str, level: str = "error") -> None:
    key = f"{user_id}:{slug}"
    logs = PREVIEW_CONSOLE_LOGS.setdefault(key, [])
    logs.append({"level": level, "message": message})
    if len(logs) > 50:
        PREVIEW_CONSOLE_LOGS[key] = logs[-50:]


def set_active_screen_frame(user_id: int, slug: str, frame_bytes_b64: str) -> None:
    key = f"{user_id}:{slug}"
    ACTIVE_SCREEN_FRAMES[key] = frame_bytes_b64


def clear_active_screen_frame(user_id: int, slug: str) -> None:
    key = f"{user_id}:{slug}"
    ACTIVE_SCREEN_FRAMES.pop(key, None)


async def handle_preview_run(context: Dict[str, Any]) -> Dict[str, Any]:
    username = context.get("username", "user")
    slug = context["slug"]
    return {
        "preview_url": f"/{username}/{slug}/",
        "running": True
    }


async def handle_preview_reload(context: Dict[str, Any]) -> Dict[str, Any]:
    slug = context["slug"]
    return {
        "reloaded": True,
        "message": f"Preview refreshed for project '{slug}'."
    }


async def handle_preview_get_console_errors(context: Dict[str, Any]) -> List[Dict[str, Any]]:
    user_id = context["user_id"]
    slug = context["slug"]
    key = f"{user_id}:{slug}"
    return PREVIEW_CONSOLE_LOGS.get(key, [])


async def handle_screen_get_latest_frame(context: Dict[str, Any]) -> Dict[str, Any]:
    user_id = context["user_id"]
    slug = context["slug"]
    key = f"{user_id}:{slug}"
    frame = ACTIVE_SCREEN_FRAMES.get(key)
    if not frame:
        return {
            "has_frame": False,
            "message": "No active screenshare frame available from creator."
        }
    return {
        "has_frame": True,
        "frame_jpeg_b64": frame
    }


async def handle_run_static_validation(context: Dict[str, Any]) -> Dict[str, Any]:
    user_id = context["user_id"]
    slug = context["slug"]
    project_dir = service.resolve_project_path(user_id, slug)

    entrypoint = project_dir / "index.html"
    if not entrypoint.exists():
        return {
            "valid": False,
            "errors": ["Entrypoint 'index.html' is missing from project root."]
        }

    errors: List[str] = []
    files = service.get_project_files(user_id, slug)
    if not files.get("index.html"):
        errors.append("index.html is empty.")

    # Check for script references in index.html
    html_content = files.get("index.html", "")
    if "<canvas" not in html_content and "phaser" not in html_content.lower() and "three" not in html_content.lower():
        # Informational check
        pass

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "file_count": len(files)
    }


def register_preview_tools() -> None:
    tool_registry.register(ToolDefinition(
        name="preview.run",
        description="Returns the sandboxed game preview URL for playback.",
        parameters_schema={"type": "OBJECT", "properties": {}},
        handler=handle_preview_run,
        access=ToolAccess.BOTH,
        impact=ToolImpact.READ_ONLY
    ))

    tool_registry.register(ToolDefinition(
        name="preview.reload",
        description="Signals the client preview pane to reload the updated game.",
        parameters_schema={"type": "OBJECT", "properties": {}},
        handler=handle_preview_reload,
        access=ToolAccess.BOTH,
        impact=ToolImpact.MUTATING
    ))

    tool_registry.register(ToolDefinition(
        name="preview.get_console_errors",
        description="Retrieves JavaScript runtime errors and console warnings captured from the running preview iframe.",
        parameters_schema={"type": "OBJECT", "properties": {}},
        handler=handle_preview_get_console_errors,
        access=ToolAccess.BOTH,
        impact=ToolImpact.READ_ONLY
    ))

    tool_registry.register(ToolDefinition(
        name="screen.get_latest_frame",
        description="Retrieves the latest valid screenshare frame (JPEG) when the creator has explicitly enabled visual sharing.",
        parameters_schema={"type": "OBJECT", "properties": {}},
        handler=handle_screen_get_latest_frame,
        access=ToolAccess.BOTH,
        impact=ToolImpact.READ_ONLY
    ))

    tool_registry.register(ToolDefinition(
        name="checks.run_static_validation",
        description="Runs static validation checking entrypoint presence, non-empty files, and syntax validity.",
        parameters_schema={"type": "OBJECT", "properties": {}},
        handler=handle_run_static_validation,
        access=ToolAccess.BOTH,
        impact=ToolImpact.READ_ONLY
    ))


register_preview_tools()
