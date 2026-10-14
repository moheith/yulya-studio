"""
Workspace discovery, inspection, and file editing tools for Yulya Studio V2.
Follows Section 17 of Master Prompt.
"""

import difflib
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
from backend.app.projects.manifest import load_manifest, merge_manifest_updates


async def handle_get_overview(context: Dict[str, Any]) -> Dict[str, Any]:
    user_id = context["user_id"]
    slug = context["slug"]
    manifest = load_manifest(service.resolve_project_path(user_id, slug))
    files = service.list_project_files(user_id, slug)
    total_size = sum(f["size"] for f in files if not f["is_dir"])
    return {
        "slug": slug,
        "title": manifest.get("title", slug),
        "genre": manifest.get("genre", "arcade"),
        "engine": manifest.get("engine", "canvas2d"),
        "entrypoint": manifest.get("entrypoint", "index.html"),
        "file_count": len([f for f in files if not f["is_dir"]]),
        "total_size_bytes": total_size,
        "systems": manifest.get("systems", []),
        "controls": manifest.get("controls", []),
        "build_status": manifest.get("build_status", "READY")
    }


async def handle_list_files(context: Dict[str, Any]) -> List[Dict[str, Any]]:
    user_id = context["user_id"]
    slug = context["slug"]
    return service.list_project_files(user_id, slug)


async def handle_read_file(file_path: str, context: Dict[str, Any]) -> Dict[str, Any]:
    user_id = context["user_id"]
    slug = context["slug"]
    content = service.read_project_file(user_id, slug, file_path)
    return {
        "file_path": file_path,
        "content": content,
        "size_bytes": len(content.encode("utf-8"))
    }


async def handle_search(query: str, context: Dict[str, Any]) -> List[Dict[str, Any]]:
    user_id = context["user_id"]
    slug = context["slug"]
    return service.search_project_files(user_id, slug, query)


async def handle_get_file_metadata(file_path: str, context: Dict[str, Any]) -> Dict[str, Any]:
    user_id = context["user_id"]
    slug = context["slug"]
    project_dir = service.resolve_project_path(user_id, slug)
    target = service.resolve_file_path(project_dir, file_path)
    if not target.exists():
        raise AppError(ErrorCategory.INVALID_INPUT, f"File '{file_path}' does not exist.")
    stat = target.stat()
    return {
        "file_path": file_path,
        "size_bytes": stat.st_size,
        "is_file": target.is_file(),
        "extension": target.suffix.lower(),
        "modified_timestamp": stat.st_mtime
    }


async def handle_get_manifest(context: Dict[str, Any]) -> Dict[str, Any]:
    user_id = context["user_id"]
    slug = context["slug"]
    project_dir = service.resolve_project_path(user_id, slug)
    return load_manifest(project_dir)


async def handle_apply_patch(file_path: str, search_string: str, replace_string: str, context: Dict[str, Any]) -> Dict[str, Any]:
    user_id = context["user_id"]
    slug = context["slug"]
    service.apply_patch(user_id, slug, file_path, search_string, replace_string)
    return {
        "file_path": file_path,
        "applied": True,
        "message": f"Successfully applied patch to '{file_path}'."
    }


async def handle_create_file(file_path: str, content: str, context: Dict[str, Any]) -> Dict[str, Any]:
    user_id = context["user_id"]
    slug = context["slug"]
    service.write_project_file(user_id, slug, file_path, content)
    return {
        "file_path": file_path,
        "created": True,
        "size_bytes": len(content.encode("utf-8"))
    }


async def handle_write_file(file_path: str, content: str, context: Dict[str, Any]) -> Dict[str, Any]:
    user_id = context["user_id"]
    slug = context["slug"]
    service.write_project_file(user_id, slug, file_path, content)
    return {
        "file_path": file_path,
        "updated": True,
        "size_bytes": len(content.encode("utf-8"))
    }


async def handle_delete_file(file_path: str, confirm: bool = False, context: Dict[str, Any] = None) -> Dict[str, Any]:
    if not confirm:
        raise AppError(ErrorCategory.PERMISSION_DENIED, "Explicit confirmation (confirm=True) required to delete files.")
    user_id = context["user_id"]
    slug = context["slug"]
    service.delete_project_file(user_id, slug, file_path)
    return {
        "file_path": file_path,
        "deleted": True
    }


async def handle_get_diff(file_path: str, new_content: str, context: Dict[str, Any]) -> Dict[str, Any]:
    user_id = context["user_id"]
    slug = context["slug"]
    try:
        old_content = service.read_project_file(user_id, slug, file_path)
    except Exception:
        old_content = ""
    diff_lines = list(difflib.unified_diff(
        old_content.splitlines(keepends=True),
        new_content.splitlines(keepends=True),
        fromfile=f"a/{file_path}",
        tofile=f"b/{file_path}"
    ))
    return {
        "file_path": file_path,
        "diff": "".join(diff_lines),
        "has_changes": len(diff_lines) > 0
    }


async def handle_save_design_decision(decision: str, context: Dict[str, Any]) -> Dict[str, Any]:
    user_id = context["user_id"]
    slug = context["slug"]
    project_dir = service.resolve_project_path(user_id, slug)
    updated = merge_manifest_updates(project_dir, {"design_decisions": [decision]})
    return {
        "decision": decision,
        "all_decisions": updated.get("design_decisions", [])
    }


async def handle_save_known_issue(issue: str, context: Dict[str, Any]) -> Dict[str, Any]:
    user_id = context["user_id"]
    slug = context["slug"]
    project_dir = service.resolve_project_path(user_id, slug)
    manifest = load_manifest(project_dir)
    bugs = manifest.get("known_bugs", [])
    if issue not in bugs:
        bugs.append(issue)
    updated = merge_manifest_updates(project_dir, {"known_bugs": bugs})
    return {
        "issue": issue,
        "known_bugs": updated.get("known_bugs", [])
    }


def register_workspace_tools() -> None:
    tool_registry.register(ToolDefinition(
        name="workspace.get_overview",
        description="Returns an overview of the current game project: slug, title, engine, entrypoint, systems, and file count.",
        parameters_schema={"type": "OBJECT", "properties": {}},
        handler=handle_get_overview,
        access=ToolAccess.BOTH,
        impact=ToolImpact.READ_ONLY
    ))

    tool_registry.register(ToolDefinition(
        name="workspace.list_files",
        description="Lists all files and directories in the current game repository.",
        parameters_schema={"type": "OBJECT", "properties": {}},
        handler=handle_list_files,
        access=ToolAccess.BOTH,
        impact=ToolImpact.READ_ONLY
    ))

    tool_registry.register(ToolDefinition(
        name="workspace.read_file",
        description="Reads the complete UTF-8 content of a specific file inside the game workspace.",
        parameters_schema={
            "type": "OBJECT",
            "properties": {
                "file_path": {"type": "STRING", "description": "Relative path to file (e.g. 'app.js', 'style.css')"}
            },
            "required": ["file_path"]
        },
        handler=handle_read_file,
        access=ToolAccess.BOTH,
        impact=ToolImpact.READ_ONLY
    ))

    tool_registry.register(ToolDefinition(
        name="workspace.search",
        description="Searches source files in the project for a query string or symbol.",
        parameters_schema={
            "type": "OBJECT",
            "properties": {
                "query": {"type": "STRING", "description": "Text or identifier to search for"}
            },
            "required": ["query"]
        },
        handler=handle_search,
        access=ToolAccess.BOTH,
        impact=ToolImpact.READ_ONLY
    ))

    tool_registry.register(ToolDefinition(
        name="workspace.get_file_metadata",
        description="Retrieves file size, extension, and modification timestamp for a project file.",
        parameters_schema={
            "type": "OBJECT",
            "properties": {
                "file_path": {"type": "STRING", "description": "Relative path to file"}
            },
            "required": ["file_path"]
        },
        handler=handle_get_file_metadata,
        access=ToolAccess.BOTH,
        impact=ToolImpact.READ_ONLY
    ))

    tool_registry.register(ToolDefinition(
        name="workspace.get_manifest",
        description="Retrieves the persistent project memory (project_manifest.json) recording engine, systems, and design decisions.",
        parameters_schema={"type": "OBJECT", "properties": {}},
        handler=handle_get_manifest,
        access=ToolAccess.BOTH,
        impact=ToolImpact.READ_ONLY
    ))

    tool_registry.register(ToolDefinition(
        name="workspace.apply_patch",
        description="Applies an exact search-and-replace patch to modify a specific block of code within a file.",
        parameters_schema={
            "type": "OBJECT",
            "properties": {
                "file_path": {"type": "STRING", "description": "Target relative file path"},
                "search_string": {"type": "STRING", "description": "Exact text block to replace"},
                "replace_string": {"type": "STRING", "description": "New replacement code block"}
            },
            "required": ["file_path", "search_string", "replace_string"]
        },
        handler=handle_apply_patch,
        access=ToolAccess.AGENT_ONLY,
        impact=ToolImpact.MUTATING
    ))

    tool_registry.register(ToolDefinition(
        name="workspace.create_file",
        description="Creates a new file with specified content inside the project directory.",
        parameters_schema={
            "type": "OBJECT",
            "properties": {
                "file_path": {"type": "STRING", "description": "Relative path for the new file"},
                "content": {"type": "STRING", "description": "UTF-8 text content"}
            },
            "required": ["file_path", "content"]
        },
        handler=handle_create_file,
        access=ToolAccess.AGENT_ONLY,
        impact=ToolImpact.MUTATING
    ))

    tool_registry.register(ToolDefinition(
        name="workspace.write_file",
        description="Writes or replaces the full content of an authorized file in the project.",
        parameters_schema={
            "type": "OBJECT",
            "properties": {
                "file_path": {"type": "STRING", "description": "Target file path"},
                "content": {"type": "STRING", "description": "Complete new content"}
            },
            "required": ["file_path", "content"]
        },
        handler=handle_write_file,
        access=ToolAccess.AGENT_ONLY,
        impact=ToolImpact.MUTATING
    ))

    tool_registry.register(ToolDefinition(
        name="workspace.delete_file",
        description="Deletes a file within the project. Requires explicit confirm=True.",
        parameters_schema={
            "type": "OBJECT",
            "properties": {
                "file_path": {"type": "STRING", "description": "Path of file to delete"},
                "confirm": {"type": "BOOLEAN", "description": "Must be true to authorize deletion"}
            },
            "required": ["file_path", "confirm"]
        },
        handler=handle_delete_file,
        access=ToolAccess.AGENT_ONLY,
        impact=ToolImpact.DESTRUCTIVE,
        requires_confirmation=True
    ))

    tool_registry.register(ToolDefinition(
        name="workspace.get_diff",
        description="Generates a unified diff comparing current file content against proposed content.",
        parameters_schema={
            "type": "OBJECT",
            "properties": {
                "file_path": {"type": "STRING", "description": "Relative path to file"},
                "new_content": {"type": "STRING", "description": "Proposed new file content"}
            },
            "required": ["file_path", "new_content"]
        },
        handler=handle_get_diff,
        access=ToolAccess.BOTH,
        impact=ToolImpact.READ_ONLY
    ))

    tool_registry.register(ToolDefinition(
        name="workspace.save_design_decision",
        description="Appends a key design decision or architectural pattern to the project's permanent manifest.",
        parameters_schema={
            "type": "OBJECT",
            "properties": {
                "decision": {"type": "STRING", "description": "Engineering or visual design decision to record"}
            },
            "required": ["decision"]
        },
        handler=handle_save_design_decision,
        access=ToolAccess.BOTH,
        impact=ToolImpact.MUTATING
    ))

    tool_registry.register(ToolDefinition(
        name="workspace.save_known_issue",
        description="Records an identified bug or limitation in the project manifest.",
        parameters_schema={
            "type": "OBJECT",
            "properties": {
                "issue": {"type": "STRING", "description": "Bug description or edge case"}
            },
            "required": ["issue"]
        },
        handler=handle_save_known_issue,
        access=ToolAccess.BOTH,
        impact=ToolImpact.MUTATING
    ))


register_workspace_tools()
