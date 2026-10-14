"""
Build orchestration and model diagnostics tools for Yulya Studio V2.
Follows Section 17 & Section 21 of Master Prompt.
"""

from typing import Dict, Any, Optional

from backend.app.ai.tools.registry import (
    tool_registry,
    ToolDefinition,
    ToolAccess,
    ToolImpact
)
from backend.app.models.registry import (
    get_default_live_model,
    get_default_code_model,
    get_model
)


# In-memory build jobs state: build_id -> dict
ACTIVE_BUILDS: Dict[str, Dict[str, Any]] = {}


def record_build_state(build_id: str, data: Dict[str, Any]) -> None:
    ACTIVE_BUILDS[build_id] = data


def get_build_state(build_id: str) -> Optional[Dict[str, Any]]:
    return ACTIVE_BUILDS.get(build_id)


async def handle_submit_task(task_description: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Called by Voice Architect to delegate an authorized coding task to the Build Orchestrator.
    """
    user_id = context["user_id"]
    slug = context["slug"]
    username = context.get("username", "user")

    # Import orchestrator lazily to avoid circular imports
    from backend.app.ai import orchestrator

    res = await orchestrator.execute_build_task(
        user_id=user_id,
        username=username,
        slug=slug,
        prompt=task_description,
        source="voice_architect"
    )
    return res


async def handle_get_status(build_id: Optional[str] = None, context: Dict[str, Any] = None) -> Dict[str, Any]:
    if build_id and build_id in ACTIVE_BUILDS:
        return ACTIVE_BUILDS[build_id]
    return {
        "status": "IDLE",
        "message": "No active build currently running."
    }


async def handle_get_current_model_status(context: Dict[str, Any]) -> Dict[str, Any]:
    active_live = context.get("active_live_model") or get_default_live_model()
    active_code = context.get("active_code_model") or get_default_code_model()
    live_entry = get_model(active_live)
    code_entry = get_model(active_code)
    return {
        "live_model": live_entry.to_dict() if live_entry else {"id": active_live},
        "code_model": code_entry.to_dict() if code_entry else {"id": active_code},
        "fallback_active": context.get("fallback_active", False)
    }


def register_build_tools() -> None:
    tool_registry.register(ToolDefinition(
        name="build.submit_task",
        description="Delegates a game engineering or bug fix task to the autonomous Game Coding Agent.",
        parameters_schema={
            "type": "OBJECT",
            "properties": {
                "task_description": {"type": "STRING", "description": "Specific feature to build, repair, or refactor"}
            },
            "required": ["task_description"]
        },
        handler=handle_submit_task,
        access=ToolAccess.VOICE_ONLY,
        impact=ToolImpact.MUTATING,
        timeout_sec=240.0
    ))

    tool_registry.register(ToolDefinition(
        name="build.get_status",
        description="Returns the progress, current stage, and status of an active or recent build.",
        parameters_schema={
            "type": "OBJECT",
            "properties": {
                "build_id": {"type": "STRING", "description": "Optional build ID to query"}
            }
        },
        handler=handle_get_status,
        access=ToolAccess.BOTH,
        impact=ToolImpact.READ_ONLY
    ))

    tool_registry.register(ToolDefinition(
        name="models.get_current_status",
        description="Returns the active Gemini Live voice model and Antigravity code model, including fallback status.",
        parameters_schema={"type": "OBJECT", "properties": {}},
        handler=handle_get_current_model_status,
        access=ToolAccess.BOTH,
        impact=ToolImpact.READ_ONLY
    ))


register_build_tools()
