"""
Pydantic v2 schemas for request validation, responses, events, and tool execution contracts.
Follows Section 18 & Section 40 of Master Prompt.
"""

from enum import Enum
from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field


# --- User & Auth Schemas ---

class UserSession(BaseModel):
    id: int
    username: str
    avatar: Optional[str] = None
    display_name: Optional[str] = None


class SaveApiKeyRequest(BaseModel):
    api_key: str = Field(..., min_length=15, description="Google AI Studio API key")


class SetModelPreferenceRequest(BaseModel):
    model: str = Field(..., min_length=2, description="Target model ID")


# --- Project Schemas ---

class CreateProjectRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=100)
    slug: Optional[str] = Field(None, max_length=60)
    description: Optional[str] = Field("", max_length=500)
    tags: Optional[List[str]] = Field(default_factory=lambda: ["game", "canvas"])


class ModifyProjectRequest(BaseModel):
    slug: str = Field(..., min_length=1, max_length=60)
    prompt: str = Field(..., min_length=1, max_length=8000)
    requested_model: Optional[str] = None


class DeleteProjectRequest(BaseModel):
    slug: str = Field(..., min_length=1, max_length=60)


class ProjectOverview(BaseModel):
    slug: str
    title: str
    description: str
    files: List[str]
    tags: List[str]
    is_public: bool
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    views: Optional[int] = 0
    plays: Optional[int] = 0


# --- Publishing & Releases (Section 59) ---

class PublishReleaseRequest(BaseModel):
    slug: str = Field(..., min_length=1, max_length=60)
    title: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    changelog: Optional[str] = Field("", max_length=2000)


class ReleaseSummary(BaseModel):
    version: int
    slug: str
    title: str
    description: str
    changelog: str
    is_active: bool
    published_at: str


# --- Tool Execution Contract (Section 18) ---

class ToolExecutionResult(BaseModel):
    success: bool
    tool_name: str
    request_id: Optional[str] = None
    build_id: Optional[str] = None
    data: Optional[Any] = None
    error_type: Optional[str] = None
    message: Optional[str] = None
    recoverable: bool = False
    duration_ms: float = 0.0


# --- Build Status & Lifecycle ---

class BuildStage(str, Enum):
    ACCEPTED = "ACCEPTED"
    INSPECTING = "INSPECTING"
    PLANNING = "PLANNING"
    EDITING = "EDITING"
    VALIDATING = "VALIDATING"
    PREVIEW_READY = "PREVIEW_READY"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class BuildProgressEvent(BaseModel):
    event_id: str
    request_id: str
    build_id: str
    stage: BuildStage
    message: str
    timestamp: float
    files_changed: Optional[List[str]] = None
    diffs: Optional[Dict[str, str]] = None
    actual_model: Optional[str] = None
    error: Optional[str] = None
