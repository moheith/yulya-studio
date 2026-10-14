"""
Central typed tool registry for Yulya Studio V2.
Follows Section 16, 17, and 18 of Master Prompt.
Single authoritative source of truth for both Voice Architect and Game Coding Agent.
"""

import time
import inspect
import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, Callable, Coroutine, Optional, List
from google.genai import types

from backend.app.core.logging import logger
from backend.app.core.errors import AppError, ErrorCategory
from backend.app.models.schemas import ToolExecutionResult


class ToolAccess(str, Enum):
    VOICE_ONLY = "voice_only"
    AGENT_ONLY = "agent_only"
    BOTH = "both"


class ToolImpact(str, Enum):
    READ_ONLY = "read_only"
    MUTATING = "mutating"
    DESTRUCTIVE = "destructive"


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters_schema: Dict[str, Any]
    handler: Callable[..., Coroutine[Any, Any, Any]]
    access: ToolAccess = ToolAccess.BOTH
    impact: ToolImpact = ToolImpact.READ_ONLY
    timeout_sec: float = 30.0
    requires_confirmation: bool = False

    def to_gemini_declaration(self) -> types.FunctionDeclaration:
        """Converts internal tool schema into Google GenAI FunctionDeclaration."""
        return types.FunctionDeclaration(
            name=self.name.replace(".", "_"),
            description=self.description,
            parameters=self.parameters_schema
        )


class ToolRegistry:
    """Authoritative registry containing all validated tools."""

    def __init__(self):
        self._tools: Dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        self._tools[tool.name] = tool
        # Also index with underscore alias for Gemini API compatibility
        underscore_name = tool.name.replace(".", "_")
        if underscore_name != tool.name:
            self._tools[underscore_name] = tool

    def get(self, name: str) -> Optional[ToolDefinition]:
        return self._tools.get(name)

    def list_tools(self, target: Optional[ToolAccess] = None) -> List[ToolDefinition]:
        unique_tools = {t.name: t for t in self._tools.values()}
        if target is None:
            return list(unique_tools.values())
        return [
            t for t in unique_tools.values()
            if t.access == ToolAccess.BOTH or t.access == target
        ]

    def get_gemini_toolset(self, target: Optional[ToolAccess] = None) -> types.Tool:
        """Returns a google.genai types.Tool instance with all matching function declarations."""
        decls = [t.to_gemini_declaration() for t in self.list_tools(target)]
        return types.Tool(function_declarations=decls)

    async def execute(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        request_id: Optional[str] = None,
        build_id: Optional[str] = None
    ) -> ToolExecutionResult:
        """Executes a tool with timeout enforcement, error classification, and timing."""
        tool = self.get(tool_name)
        start_time = time.time()

        if not tool:
            return ToolExecutionResult(
                success=False,
                tool_name=tool_name,
                request_id=request_id,
                build_id=build_id,
                error_type="UNKNOWN_TOOL",
                message=f"Tool '{tool_name}' is not recognized or not available in current execution context.",
                recoverable=False,
                duration_ms=(time.time() - start_time) * 1000
            )

        kwargs = dict(arguments or {})
        # Inject execution context (e.g. user_id, slug) if expected by handler
        sig = inspect.signature(tool.handler)
        if "context" in sig.parameters and context is not None:
            kwargs["context"] = context

        try:
            res_data = await asyncio.wait_for(
                tool.handler(**kwargs),
                timeout=tool.timeout_sec
            )
            return ToolExecutionResult(
                success=True,
                tool_name=tool.name,
                request_id=request_id,
                build_id=build_id,
                data=res_data,
                duration_ms=(time.time() - start_time) * 1000
            )
        except asyncio.TimeoutError:
            logger.error(f"[TOOL TIMEOUT] '{tool.name}' exceeded {tool.timeout_sec}s")
            return ToolExecutionResult(
                success=False,
                tool_name=tool.name,
                request_id=request_id,
                build_id=build_id,
                error_type="TIMEOUT",
                message=f"Execution of tool '{tool.name}' timed out after {tool.timeout_sec}s.",
                recoverable=True,
                duration_ms=(time.time() - start_time) * 1000
            )
        except AppError as ae:
            return ToolExecutionResult(
                success=False,
                tool_name=tool.name,
                request_id=request_id,
                build_id=build_id,
                error_type=ae.category.value,
                message=ae.message,
                recoverable=ae.recoverable,
                data=ae.details,
                duration_ms=(time.time() - start_time) * 1000
            )
        except Exception as e:
            logger.error(f"[TOOL ERROR] '{tool.name}' failed: {e}", exc_info=True)
            return ToolExecutionResult(
                success=False,
                tool_name=tool.name,
                request_id=request_id,
                build_id=build_id,
                error_type="INTERNAL_ERROR",
                message=str(e),
                recoverable=False,
                duration_ms=(time.time() - start_time) * 1000
            )


tool_registry = ToolRegistry()
