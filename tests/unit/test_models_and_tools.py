"""
Unit tests for Model Registry, Tool Registry, and Workspace Tools in Yulya Studio V2.
Verifies authoritative model declarations, tool execution boundaries, and schema conversion.
"""

import pytest
from backend.app.models.registry import (
    validate_live_model,
    validate_code_model,
    get_default_live_model,
    get_default_code_model,
    get_live_fallback_candidates,
    get_code_fallback_candidates,
    LIVE_MODELS,
    CODE_MODELS
)
from backend.app.ai.tools import (
    tool_registry,
    ToolAccess,
    ToolDefinition
)
from backend.app.projects import service


def test_model_registry_authoritative_models():
    """Verifies that only real, supported models are in the authoritative registry."""
    assert validate_live_model("gemini-3.8-live") is True
    assert validate_live_model("gemini-3.8-live-extended-thinking") is True
    assert validate_live_model("gemini-3.1-flash-live-preview") is True
    assert validate_live_model("gemini-2.0-flash-exp") is False  # deprecated/unsupported
    assert validate_live_model("gpt-4o") is False

    assert validate_code_model("gemini-3.8-flash") is True
    assert validate_code_model("gemini-3.7-flash") is True
    assert validate_code_model("gemini-3.6-flash") is True
    assert validate_code_model("claude-3-5-sonnet") is False


def test_model_waterfall_fallbacks():
    """Verifies waterfall candidate resolution with user preference."""
    candidates = get_live_fallback_candidates("gemini-3.8-live-extended-thinking")
    assert len(candidates) >= 2
    assert candidates[0].id == "gemini-3.8-live-extended-thinking"

    code_candidates = get_code_fallback_candidates("gemini-3.8-flash")
    assert len(code_candidates) >= 2
    assert code_candidates[0].id == "gemini-3.8-flash"


def test_tool_registry_registration_and_filtering():
    """Verifies tool registry enforces role separation (VOICE_ONLY vs AGENT_ONLY vs BOTH)."""
    voice_tools = {t.name for t in tool_registry.list_tools(ToolAccess.VOICE_ONLY)}
    agent_tools = {t.name for t in tool_registry.list_tools(ToolAccess.AGENT_ONLY)}

    # workspace.apply_patch must only be accessible to Code Agent, never Voice Architect
    assert "workspace.apply_patch" in agent_tools
    assert "workspace.apply_patch" not in voice_tools

    # build.submit_task must be accessible to Voice Architect
    assert "build.submit_task" in voice_tools
    assert "build.submit_task" not in agent_tools

    # workspace.read_file should be accessible to both
    assert "workspace.read_file" in voice_tools
    assert "workspace.read_file" in agent_tools


@pytest.mark.asyncio
async def test_workspace_tools_execution(tmp_path, monkeypatch):
    """Verifies workspace tool operations against isolated project directory."""
    projects_root = tmp_path / "projects"
    projects_root.mkdir()

    from backend.app.core.config import settings
    monkeypatch.setattr(settings, "PROJECTS_DIR", projects_root)

    user_id = 999
    slug = "tool-test-game"

    service.init_starter_project(user_id, slug, "Tool Test Game")
    ctx = {"user_id": user_id, "slug": slug}

    # 1. Test workspace.list_files
    res = await tool_registry.execute("workspace.list_files", {}, context=ctx)
    assert res.success is True
    assert any(f["name"] == "index.html" for f in res.data)

    # 2. Test workspace.read_file
    read_res = await tool_registry.execute("workspace.read_file", {"file_path": "index.html"}, context=ctx)
    assert read_res.success is True
    assert "<!DOCTYPE html>" in read_res.data["content"]

    # 3. Test workspace.search
    search_res = await tool_registry.execute("workspace.search", {"query": "gameCanvas"}, context=ctx)
    assert search_res.success is True
    assert len(search_res.data) >= 1

    # 4. Test workspace.apply_patch
    patch_res = await tool_registry.execute(
        "workspace.apply_patch",
        {
            "file_path": "app.js",
            "search_string": "const canvas = document.getElementById('gameCanvas');",
            "replace_string": "// Custom patch test\nconst canvas = document.getElementById('gameCanvas');"
        },
        context=ctx
    )
    assert patch_res.success is True

    # Verify change was written
    verify_read = await tool_registry.execute("workspace.read_file", {"file_path": "app.js"}, context=ctx)
    assert "// Custom patch test" in verify_read.data["content"]
