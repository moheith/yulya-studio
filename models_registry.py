"""
Central Model Registry for Yulya Studio.
Authoritative source for all Live voice and Antigravity coding models.
Used across server.py, ai_engine.py, health endpoints, studio UI, and test suites.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any


@dataclass
class ModelEntry:
    id: str
    display_name: str
    family: str
    description: str
    enabled: bool = True
    deprecated: bool = False
    supports_live: bool = False
    supports_audio: bool = False
    supports_video: bool = False
    supports_thinking: bool = False
    supports_tools: bool = False
    supports_non_blocking_tools: bool = False
    supports_code_generation: bool = False
    fallback_priority: int = 100  # Lower number = higher priority in waterfall
    recommended: bool = False
    capabilities: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "family": self.family,
            "description": self.description,
            "enabled": self.enabled,
            "deprecated": self.deprecated,
            "supports_live": self.supports_live,
            "supports_audio": self.supports_audio,
            "supports_video": self.supports_video,
            "supports_thinking": self.supports_thinking,
            "supports_tools": self.supports_tools,
            "supports_non_blocking_tools": self.supports_non_blocking_tools,
            "supports_code_generation": self.supports_code_generation,
            "fallback_priority": self.fallback_priority,
            "recommended": self.recommended,
            "capabilities": list(self.capabilities)
        }


# Authoritative Registry of all supported models in Yulya Studio
MODEL_REGISTRY: Dict[str, ModelEntry] = {
    # --- Live Voice Models ---
    "gemini-3.8-live": ModelEntry(
        id="gemini-3.8-live",
        display_name="Gemini 3.8 Live",
        family="gemini-3.8",
        description="Fast, reliable real-time voice with native audio streaming and non-blocking tool calling",
        enabled=True,
        deprecated=False,
        supports_live=True,
        supports_audio=True,
        supports_video=True,
        supports_thinking=False,
        supports_tools=True,
        supports_non_blocking_tools=True,
        supports_code_generation=False,
        fallback_priority=1,
        recommended=True,
        capabilities=["live", "audio", "video", "tools", "non_blocking_tools"]
    ),
    "gemini-3.8-live-extended-thinking": ModelEntry(
        id="gemini-3.8-live-extended-thinking",
        display_name="Gemini 3.8 Live Extended Thinking (High)",
        family="gemini-3.8",
        description="Deep reasoning with thinking level HIGH, multimodal vision, and asynchronous tool calling",
        enabled=True,
        deprecated=False,
        supports_live=True,
        supports_audio=True,
        supports_video=True,
        supports_thinking=True,
        supports_tools=True,
        supports_non_blocking_tools=True,
        supports_code_generation=False,
        fallback_priority=2,
        recommended=False,
        capabilities=["live", "audio", "video", "thinking", "tools", "non_blocking_tools"]
    ),
    "gemini-3.1-flash-live-preview": ModelEntry(
        id="gemini-3.1-flash-live-preview",
        display_name="Gemini 3.1 Live Preview",
        family="gemini-3.1",
        description="Lightweight preview fallback voice model",
        enabled=True,
        deprecated=False,
        supports_live=True,
        supports_audio=True,
        supports_video=True,
        supports_thinking=False,
        supports_tools=True,
        supports_non_blocking_tools=True,
        supports_code_generation=False,
        fallback_priority=3,
        recommended=False,
        capabilities=["live", "audio", "video", "tools", "non_blocking_tools"]
    ),

    # --- Antigravity Code Generation Models ---
    "gemini-3.8-flash": ModelEntry(
        id="gemini-3.8-flash",
        display_name="Gemini 3.8 Flash",
        family="gemini-3.8",
        description="Fast, powerful 2026 flagship code generation engine",
        enabled=True,
        deprecated=False,
        supports_live=False,
        supports_audio=False,
        supports_video=False,
        supports_thinking=False,
        supports_tools=True,
        supports_non_blocking_tools=False,
        supports_code_generation=True,
        fallback_priority=1,
        recommended=True,
        capabilities=["code_generation", "tools", "structured_json"]
    ),
    "gemini-3.7-flash": ModelEntry(
        id="gemini-3.7-flash",
        display_name="Gemini 3.7 Flash",
        family="gemini-3.7",
        description="Advanced reasoning and game development architecture",
        enabled=True,
        deprecated=False,
        supports_live=False,
        supports_audio=False,
        supports_video=False,
        supports_thinking=False,
        supports_tools=True,
        supports_non_blocking_tools=False,
        supports_code_generation=True,
        fallback_priority=2,
        recommended=False,
        capabilities=["code_generation", "tools", "structured_json"]
    ),
    "gemini-3.6-flash": ModelEntry(
        id="gemini-3.6-flash",
        display_name="Gemini 3.6 Flash",
        family="gemini-3.6",
        description="High-speed balanced code generation",
        enabled=True,
        deprecated=False,
        supports_live=False,
        supports_audio=False,
        supports_video=False,
        supports_thinking=False,
        supports_tools=True,
        supports_non_blocking_tools=False,
        supports_code_generation=True,
        fallback_priority=3,
        recommended=False,
        capabilities=["code_generation", "tools", "structured_json"]
    ),
    "gemini-3.5-flash": ModelEntry(
        id="gemini-3.5-flash",
        display_name="Gemini 3.5 Flash",
        family="gemini-3.5",
        description="Stable high-throughput production engine",
        enabled=True,
        deprecated=False,
        supports_live=False,
        supports_audio=False,
        supports_video=False,
        supports_thinking=False,
        supports_tools=True,
        supports_non_blocking_tools=False,
        supports_code_generation=True,
        fallback_priority=4,
        recommended=False,
        capabilities=["code_generation", "tools", "structured_json"]
    ),
    "gemini-3.1-flash-lite": ModelEntry(
        id="gemini-3.1-flash-lite",
        display_name="Gemini 3.1 Flash Lite",
        family="gemini-3.1",
        description="Ultra-fast low-quota code generator",
        enabled=True,
        deprecated=False,
        supports_live=False,
        supports_audio=False,
        supports_video=False,
        supports_thinking=False,
        supports_tools=True,
        supports_non_blocking_tools=False,
        supports_code_generation=True,
        fallback_priority=5,
        recommended=False,
        capabilities=["code_generation", "tools", "structured_json"]
    ),
    "gemini-3.5-flash-lite": ModelEntry(
        id="gemini-3.5-flash-lite",
        display_name="Gemini 3.5 Flash Lite",
        family="gemini-3.5",
        description="Lightweight low-latency fallback model",
        enabled=True,
        deprecated=False,
        supports_live=False,
        supports_audio=False,
        supports_video=False,
        supports_thinking=False,
        supports_tools=True,
        supports_non_blocking_tools=False,
        supports_code_generation=True,
        fallback_priority=6,
        recommended=False,
        capabilities=["code_generation", "tools", "structured_json"]
    ),
    "gemini-2.5-flash": ModelEntry(
        id="gemini-2.5-flash",
        display_name="Gemini 2.5 Flash",
        family="gemini-2.5",
        description="Legacy reliable baseline code engine",
        enabled=True,
        deprecated=False,
        supports_live=False,
        supports_audio=False,
        supports_video=False,
        supports_thinking=False,
        supports_tools=True,
        supports_non_blocking_tools=False,
        supports_code_generation=True,
        fallback_priority=7,
        recommended=False,
        capabilities=["code_generation", "tools", "structured_json"]
    ),
}

DEFAULT_LIVE_MODEL_ID = "gemini-3.8-live"
DEFAULT_CODE_MODEL_ID = "gemini-3.8-flash"


def get_model(model_id: str) -> Optional[ModelEntry]:
    """Retrieves a model entry by ID (case-insensitive)."""
    if not model_id:
        return None
    clean = model_id.strip().lower()
    for mid, entry in MODEL_REGISTRY.items():
        if mid.lower() == clean:
            return entry
    return None


def get_live_models(include_disabled: bool = False) -> List[ModelEntry]:
    """Returns all models that support Gemini Live, sorted by fallback priority."""
    res = [
        m for m in MODEL_REGISTRY.values()
        if m.supports_live and (include_disabled or (m.enabled and not m.deprecated))
    ]
    res.sort(key=lambda m: m.fallback_priority)
    return res


def get_code_models(include_disabled: bool = False) -> List[ModelEntry]:
    """Returns all models that support Antigravity code generation, sorted by fallback priority."""
    res = [
        m for m in MODEL_REGISTRY.values()
        if m.supports_code_generation and (include_disabled or (m.enabled and not m.deprecated))
    ]
    res.sort(key=lambda m: m.fallback_priority)
    return res


def get_live_fallback_candidates(preferred_model_id: Optional[str] = None) -> List[ModelEntry]:
    """
    Returns ordered live model candidates for connection waterfall.
    Places preferred model at index 0 if valid and enabled, followed by other live models by priority.
    """
    candidates = get_live_models(include_disabled=False)
    if preferred_model_id and preferred_model_id.strip():
        pref_clean = preferred_model_id.strip().lower()
        candidates.sort(key=lambda c: (0 if c.id.lower() == pref_clean else 1, c.fallback_priority))
    return candidates


def get_code_fallback_candidates(preferred_model_id: Optional[str] = None) -> List[ModelEntry]:
    """
    Returns ordered code generation model candidates for waterfall.
    Places preferred model at index 0 if valid and enabled, followed by other code models by priority.
    """
    candidates = get_code_models(include_disabled=False)
    if preferred_model_id and preferred_model_id.strip():
        pref_clean = preferred_model_id.strip().lower()
        candidates.sort(key=lambda c: (0 if c.id.lower() == pref_clean else 1, c.fallback_priority))
    return candidates


def validate_live_model(model_id: str) -> bool:
    """Validates that a model ID is a valid, enabled, non-deprecated live model."""
    m = get_model(model_id)
    return m is not None and m.supports_live and m.enabled and not m.deprecated


def validate_code_model(model_id: str) -> bool:
    """Validates that a model ID is a valid, enabled, non-deprecated code generation model."""
    m = get_model(model_id)
    return m is not None and m.supports_code_generation and m.enabled and not m.deprecated


def get_registry_summary() -> Dict[str, Any]:
    """Returns a full JSON-serializable dictionary for API endpoints and UI consumers."""
    return {
        "default_live_model": DEFAULT_LIVE_MODEL_ID,
        "default_code_model": DEFAULT_CODE_MODEL_ID,
        "live_models": [m.to_dict() for m in get_live_models(include_disabled=False)],
        "code_models": [m.to_dict() for m in get_code_models(include_disabled=False)],
        "all_models": {mid: m.to_dict() for mid, m in MODEL_REGISTRY.items()}
    }
