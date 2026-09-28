"""
Live Session Architecture for Yulya Studio.
Implements the authoritative Live Session State Machine, Failure Classification,
Tool Execution Contract with Observability, and Screenshare/Vision Subsystem.
"""

import time
import base64
import asyncio
from enum import Enum
from typing import Optional, Dict, Any, Callable, Coroutine
from google.genai.errors import APIError
import models_registry


class LiveState(str, Enum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    LISTENING = "LISTENING"
    SPEAKING = "SPEAKING"
    THINKING = "THINKING"
    TOOL_RUNNING = "TOOL_RUNNING"
    INTERRUPTED = "INTERRUPTED"
    DEGRADED = "DEGRADED"
    FALLING_BACK = "FALLING_BACK"
    RECONNECTING = "RECONNECTING"
    ERROR = "ERROR"


class FailureClass(str, Enum):
    AUTH = "AUTH"
    INVALID_REQUEST = "INVALID_REQUEST"
    QUOTA = "QUOTA"
    TIMEOUT = "TIMEOUT"
    TRANSIENT_TRANSPORT = "TRANSIENT_TRANSPORT"
    TOOL_EXECUTION = "TOOL_EXECUTION"
    SERIALIZATION = "SERIALIZATION"
    USER_INTERRUPTION = "USER_INTERRUPTION"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


def classify_failure(err: Exception) -> FailureClass:
    """Classifies an exception into a FailureClass to determine if model fallback is justified."""
    if isinstance(err, asyncio.CancelledError):
        return FailureClass.USER_INTERRUPTION
    if isinstance(err, (asyncio.TimeoutError, TimeoutError)):
        return FailureClass.TIMEOUT

    err_str = str(err).lower()
    
    if "api_key_invalid" in err_str or "unauthenticated" in err_str or "invalid api key" in err_str:
        return FailureClass.AUTH
    if "resource_exhausted" in err_str or "quota" in err_str or "429" in err_str:
        return FailureClass.QUOTA
    if "not found" in err_str or "unsupported by the model" in err_str or "unknown model" in err_str or "404" in err_str:
        return FailureClass.MODEL_UNAVAILABLE
    if "invalid_argument" in err_str or "bad request" in err_str or "400" in err_str:
        return FailureClass.INVALID_REQUEST
    if "connection" in err_str or "transport" in err_str or "disconnect" in err_str or "closed" in err_str or "socket" in err_str:
        return FailureClass.TRANSIENT_TRANSPORT
    if "json" in err_str or "serialization" in err_str or "protocol" in err_str or "format" in err_str:
        return FailureClass.SERIALIZATION

    if isinstance(err, APIError):
        if err.code in (401, 403):
            return FailureClass.AUTH
        elif err.code == 429:
            return FailureClass.QUOTA
        elif err.code == 404:
            return FailureClass.MODEL_UNAVAILABLE
        elif err.code == 400:
            return FailureClass.INVALID_REQUEST
        elif err.code in (500, 502, 503, 504):
            return FailureClass.TRANSIENT_TRANSPORT

    return FailureClass.UNKNOWN


def is_fallback_eligible(failure: FailureClass) -> bool:
    """Determines if a failure is eligible for model waterfall shifting."""
    return failure in (
        FailureClass.QUOTA,
        FailureClass.MODEL_UNAVAILABLE,
        FailureClass.TRANSIENT_TRANSPORT,
        FailureClass.TIMEOUT
    )


class ScreenshareSubsystem:
    """
    Stateful Screenshare subsystem.
    Tracks frame metrics, validates JPEG payloads, and enforces a recent-frame policy.
    """
    def __init__(self):
        self.active: bool = False
        self.latest_frame_bytes: Optional[bytes] = None
        self.latest_timestamp: float = 0.0
        self.latest_width: int = 0
        self.latest_height: int = 0
        self.latest_size_bytes: int = 0
        self.last_frame_sent_to_gemini: float = 0.0
        self.frames_received: int = 0
        self.frames_sent: int = 0
        self.frames_dropped: int = 0

    def validate_and_record_frame(self, frame_b64: str) -> Optional[bytes]:
        """
        Validates incoming base64 frame:
        - Decodes base64 safely
        - Verifies non-empty bytes and reasonable size (100 B to 1.5 MB)
        - Verifies JPEG SOI marker (0xFF, 0xD8)
        - Records timestamp and metrics
        Returns raw bytes if valid, else None.
        """
        self.frames_received += 1
        if not frame_b64 or len(frame_b64) > 2_000_000:
            self.frames_dropped += 1
            return None

        try:
            raw_bytes = base64.b64decode(frame_b64)
            size = len(raw_bytes)
            if size < 100 or size > 1_500_000:
                self.frames_dropped += 1
                return None

            # Verify JPEG Start Of Image marker
            if not (raw_bytes.startswith(b'\xff\xd8')):
                self.frames_dropped += 1
                return None

            now = time.time()
            self.latest_frame_bytes = raw_bytes
            self.latest_timestamp = now
            self.latest_size_bytes = size
            self.frames_sent += 1

            # Quick JPEG dimension extraction if available
            w, h = self._extract_jpeg_dimensions(raw_bytes)
            if w and h:
                self.latest_width = w
                self.latest_height = h

            return raw_bytes
        except Exception:
            self.frames_dropped += 1
            return None

    def should_attach_to_turn(self, freshness_sec: float = 2.5) -> bool:
        """
        Recent-frame policy:
        Only attach frame to a client turn if screenshare is active, a valid frame exists,
        and it hasn't been sent to Gemini within the freshness threshold.
        """
        if not self.active or not self.latest_frame_bytes:
            return False
        now = time.time()
        # If never sent or older than threshold, attach it
        if now - self.last_frame_sent_to_gemini >= freshness_sec:
            return True
        return False

    def mark_frame_sent_to_gemini(self):
        """Records timestamp when a frame was delivered to Gemini."""
        self.last_frame_sent_to_gemini = time.time()

    def get_stats(self) -> Dict[str, Any]:
        """Returns diagnostic metrics for health checks and UI state."""
        now = time.time()
        age_ms = int((now - self.latest_timestamp) * 1000) if self.latest_timestamp > 0 else None
        res_str = f"{self.latest_width}x{self.latest_height}" if (self.latest_width and self.latest_height) else "Unknown"
        return {
            "active": self.active,
            "last_frame_age_ms": age_ms,
            "resolution": res_str,
            "size_bytes": self.latest_size_bytes,
            "frames_received": self.frames_received,
            "frames_sent": self.frames_sent,
            "frames_dropped": self.frames_dropped
        }

    def reset(self):
        """Resets the screenshare state when streaming stops."""
        self.active = False
        self.latest_frame_bytes = None
        self.latest_timestamp = 0.0

    @staticmethod
    def _extract_jpeg_dimensions(data: bytes) -> tuple[int, int]:
        """Parses JPEG SOF marker to extract width and height without heavy dependencies."""
        try:
            idx = 2
            length = len(data)
            while idx < length - 8:
                if data[idx] == 0xFF:
                    marker = data[idx + 1]
                    # SOF0 through SOF2 markers containing dimensions
                    if marker in (0xC0, 0xC1, 0xC2):
                        h = (data[idx + 5] << 8) + data[idx + 6]
                        w = (data[idx + 7] << 8) + data[idx + 8]
                        return w, h
                    elif marker not in (0xFF, 0x00, 0xD9):
                        seg_len = (data[idx + 2] << 8) + data[idx + 3]
                        idx += 2 + seg_len
                        continue
                idx += 1
        except Exception:
            pass
        return 0, 0


class LiveSessionContext:
    """
    Server-authoritative state tracker for an active Gemini Live session on a WebSocket.
    Manages state transitions, fallbacks, tool observability, and turn sequencing.
    """
    def __init__(self, ws, slug: str, user_id: int, username: str, requested_model_id: str):
        self.ws = ws
        self.slug = slug
        self.user_id = user_id
        self.username = username
        self.requested_model_id = requested_model_id
        self.actual_model_id = requested_model_id
        self.actual_model_display = requested_model_id
        self.state: LiveState = LiveState.DISCONNECTED
        self.session = None  # AsyncSession from google-genai
        self.cm = None       # Context manager from client.aio.live.connect
        self.receive_task = None
        self.client = None
        self.is_extended_thinking = False
        self.last_state_change: float = time.time()
        self.fallback_count: int = 0
        self.fallback_chain: list[str] = []
        self.fallback_reason: Optional[str] = None
        self.current_turn_id: int = 1
        self.screenshare = ScreenshareSubsystem()

    async def transition_to(self, new_state: LiveState, reason: Optional[str] = None):
        """
        Transitions the session to a new state and broadcasts the state change to the WebSocket.
        """
        old_state = self.state
        self.state = new_state
        self.last_state_change = time.time()

        display_name = self.actual_model_display
        m_entry = models_registry.get_model(self.actual_model_id)
        if m_entry:
            display_name = m_entry.display_name

        payload = {
            "type": "live_session_state",
            "state": new_state.value,
            "old_state": old_state.value,
            "requested_model": self.requested_model_id,
            "actual_model": self.actual_model_id,
            "model_display": display_name,
            "timestamp": int(self.last_state_change),
            "reason": reason
        }

        # Backwards compatibility event for existing UI elements
        compat_payload = {
            "type": "live_status",
            "status": new_state.value.lower(),
            "state": new_state.value,
            "model": display_name,
            "model_id": self.actual_model_id,
            "requested_model": self.requested_model_id,
            "actual_model": self.actual_model_id,
            "extended_thinking": self.is_extended_thinking,
            "timestamp": int(self.last_state_change),
            "reason": reason
        }

        if not self.ws.closed:
            try:
                await self.ws.send_json(payload)
                await self.ws.send_json(compat_payload)
            except Exception:
                pass


async def safe_execute_tool(
    tool_name: str,
    call_id: str,
    handler_coro: Coroutine,
    timeout_sec: float = 20.0,
    broadcast_log_fn: Optional[Callable] = None
) -> Dict[str, Any]:
    """
    Tool Execution Contract:
    - Wraps tool execution in a strict timeout.
    - Emits observability logs: tool_started, tool_completed, tool_failed.
    - Catches all exceptions and converts them into structured responses:
      { "success": False, "error_type": "...", "message": "...", "recoverable": True }
    - On success:
      { "success": True, "data": ... }
    - NEVER allows an unhandled exception to escape or kill the Live receive loop.
    - Never logs sensitive keys or secrets.
    """
    t0 = time.time()
    if broadcast_log_fn:
        try:
            await broadcast_log_fn(f"[TOOL_START] {tool_name} (id={call_id})", "tool")
        except Exception:
            pass

    try:
        res = await asyncio.wait_for(handler_coro, timeout=timeout_sec)
        dur_ms = int((time.time() - t0) * 1000)
        if broadcast_log_fn:
            try:
                await broadcast_log_fn(f"[TOOL_COMPLETE] {tool_name} ({dur_ms}ms)", "tool")
            except Exception:
                pass

        if isinstance(res, dict) and "success" in res:
            return res
        return {"success": True, "data": res}

    except asyncio.TimeoutError:
        dur_ms = int((time.time() - t0) * 1000)
        err_msg = f"Tool '{tool_name}' timed out after {timeout_sec}s."
        if broadcast_log_fn:
            try:
                await broadcast_log_fn(f"[TOOL_TIMEOUT] {tool_name} ({dur_ms}ms)", "error")
            except Exception:
                pass
        return {
            "success": False,
            "error_type": "TIMEOUT",
            "message": err_msg,
            "recoverable": True
        }

    except Exception as e:
        dur_ms = int((time.time() - t0) * 1000)
        err_type = type(e).__name__
        err_msg = str(e)[:200]
        if broadcast_log_fn:
            try:
                await broadcast_log_fn(f"[TOOL_ERROR] {tool_name} ({err_type}: {err_msg})", "error")
            except Exception:
                pass
        return {
            "success": False,
            "error_type": err_type,
            "message": err_msg,
            "recoverable": True
        }
