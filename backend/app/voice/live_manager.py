"""
Persistent Gemini Live Voice Session Manager for Yulya Studio V2.
Implements the persistent conversational architect contract with Mute/Unmute audio streaming,
native turn detection, non-blocking tool calling, and waterfall fallback (Sections 11, 12, 13, 14).
"""

import time
import base64
import asyncio
from enum import Enum
from pathlib import Path
from typing import Dict, Any, Optional, Callable, Coroutine
from google import genai
from google.genai import types
from google.genai.errors import APIError

from backend.app.core.config import settings
from backend.app.core.logging import logger, log_event
from backend.app.core.errors import AppError, ErrorCategory
from backend.app.models.registry import (
    get_live_fallback_candidates,
    get_default_live_model
)
from backend.app.voice.audio_pipeline import CanonicalTranscriptTracker
from backend.app.voice.screenshare import ScreenshareSubsystem
from backend.app.ai.tools.registry import tool_registry, ToolAccess


class LiveState(str, Enum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    LISTENING = "LISTENING"
    SPEAKING = "SPEAKING"
    THINKING = "THINKING"
    TOOL_RUNNING = "TOOL_RUNNING"
    INTERRUPTED = "INTERRUPTED"
    FALLING_BACK = "FALLING_BACK"
    ERROR = "ERROR"


VOICE_ARCHITECT_PROMPT_PATH = Path(__file__).resolve().parent.parent / "ai" / "prompts" / "voice_architect.md"


def _load_voice_prompt() -> str:
    if VOICE_ARCHITECT_PROMPT_PATH.exists():
        return VOICE_ARCHITECT_PROMPT_PATH.read_text(encoding="utf-8")
    return "You are Yulya, the conversational game architect. Talk naturally with the creator."


class LiveSessionManager:
    """
    Manages the authoritative Gemini Live session for a single open studio workspace.
    """

    def __init__(
        self,
        user_id: int,
        username: str,
        slug: str,
        api_key: str,
        emit_callback: Callable[[Dict[str, Any]], Coroutine[Any, Any, None]]
    ):
        self.user_id = user_id
        self.username = username
        self.slug = slug
        self.api_key = api_key
        self.emit = emit_callback

        self.state: LiveState = LiveState.DISCONNECTED
        self.is_muted: bool = False
        self.active_model_id: Optional[str] = None
        self.session_id: str = f"sess_{int(time.time()*1000)}_{slug}"
        self.generation: int = 0

        self.session: Optional[Any] = None
        self.context_manager: Optional[Any] = None
        self.receive_task: Optional[asyncio.Task] = None
        self.client: Optional[genai.Client] = None

        self.transcript_tracker = CanonicalTranscriptTracker()
        self.screenshare = ScreenshareSubsystem(user_id, slug)

    async def transition_to(self, new_state: LiveState, reason: Optional[str] = None) -> None:
        """Transitions state and broadcasts update to client."""
        self.state = new_state
        await self.emit({
            "type": "live_session_state",
            "state": new_state.value,
            "model_id": self.active_model_id or get_default_live_model(),
            "is_muted": self.is_muted,
            "reason": reason
        })

    def set_muted(self, muted: bool) -> None:
        """
        Mutes or unmutes microphone input.
        The ongoing Live session remains connected while muted (Section 13).
        """
        self.is_muted = muted
        log_event(f"Microphone mute state changed to: {muted}", channel="voice", user_id=self.user_id, slug=self.slug)

    async def connect(self, preferred_model_id: Optional[str] = None) -> bool:
        """
        Establishes one authoritative persistent Live session with bounded timeout
        and automatic waterfall fallback across candidates.
        """
        await self.transition_to(LiveState.CONNECTING)
        candidates = get_live_fallback_candidates(preferred_model_id)

        system_instruction = _load_voice_prompt()
        toolset = tool_registry.get_gemini_toolset(ToolAccess.VOICE_ONLY)

        for candidate in candidates:
            self.active_model_id = candidate.id
            log_event(f"Connecting to Gemini Live with model {candidate.id}...", channel="voice")

            try:
                self.client = genai.Client(api_key=self.api_key)

                # Configure Live session
                config = types.LiveConnectConfig(
                    response_modalities=[types.LiveModality.AUDIO],
                    system_instruction=types.Content(
                        parts=[types.Part.from_text(text=system_instruction)]
                    ),
                    tools=[toolset],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Aoede")
                        )
                    )
                )

                # Bounded 10s handshake (Section 12)
                self.context_manager = self.client.aio.live.connect(
                    model=candidate.id,
                    config=config
                )

                self.session = await asyncio.wait_for(
                    self.context_manager.__aenter__(),
                    timeout=settings.MAX_LIVE_CONNECT_TIMEOUT_SEC
                )

                self.generation += 1
                await self.transition_to(LiveState.CONNECTED)
                self.receive_task = asyncio.create_task(self._receive_loop(self.generation))
                return True

            except asyncio.TimeoutError:
                logger.warning(f"[LIVE TIMEOUT] Connection to {candidate.id} timed out (10s). Trying fallback...")
                await self._cleanup_pending()
                await self.transition_to(LiveState.FALLING_BACK, reason=f"Timeout on {candidate.id}")
                continue
            except APIError as ae:
                logger.warning(f"[LIVE API ERROR] {candidate.id} failed: {ae}")
                await self._cleanup_pending()
                if ae.code in (401, 403):
                    await self.transition_to(LiveState.ERROR, reason="Invalid Google AI Studio API key.")
                    return False
                await self.transition_to(LiveState.FALLING_BACK, reason=f"{candidate.id} unavailable ({ae.code})")
                continue
            except Exception as e:
                logger.warning(f"[LIVE ERROR] {candidate.id} connection failed: {e}")
                await self._cleanup_pending()
                continue

        await self.transition_to(LiveState.ERROR, reason="All candidate Live models failed to connect.")
        return False

    async def _cleanup_pending(self) -> None:
        if self.context_manager:
            try:
                await self.context_manager.__aexit__(None, None, None)
            except Exception:
                pass
            self.context_manager = None
            self.session = None

    async def handle_audio_chunk(self, pcm_base64: str) -> None:
        """
        Receives 16kHz PCM audio chunk from browser.
        If muted or if Gemini Live is executing a tool, silently drops chunk to prevent 1008 errors!
        """
        if self.is_muted or self.state in (LiveState.TOOL_RUNNING, LiveState.FALLING_BACK, LiveState.DISCONNECTED, LiveState.ERROR):
            return

        if not self.session or not pcm_base64:
            return

        try:
            pcm_bytes = base64.b64decode(pcm_base64)
            await self.session.send_realtime_input(
                audio=types.Blob(data=pcm_bytes, mime_type="audio/pcm;rate=16000")
            )
        except Exception as e:
            logger.warning(f"[LIVE AUDIO SEND ERROR] {e}")

    async def handle_video_frame(self, frame_b64: str) -> None:
        """Processes display frame from screen sharing and forwards to active session."""
        if not self.session or self.state != LiveState.CONNECTED:
            return

        accepted = self.screenshare.process_incoming_frame(frame_b64)
        if accepted and self.screenshare.latest_frame_bytes:
            try:
                await self.session.send_realtime_input(
                    media=types.Blob(
                        data=self.screenshare.latest_frame_bytes,
                        mime_type="image/jpeg"
                    )
                )
            except Exception as e:
                logger.warning(f"[LIVE VIDEO SEND ERROR] {e}")

    async def _receive_loop(self, gen: int) -> None:
        """Authoritative receive loop consuming Gemini Live responses and tool requests."""
        try:
            async for response in self.session.receive():
                if gen != self.generation:
                    break

                server_content = getattr(response, "server_content", None)
                tool_call = getattr(response, "tool_call", None)

                # 1. Handle Assistant Spoken Audio and Transcripts
                if server_content:
                    model_turn = getattr(server_content, "model_turn", None)
                    interrupted = getattr(server_content, "interrupted", False)

                    if interrupted:
                        await self.transition_to(LiveState.INTERRUPTED)
                        await self.emit({"type": "ai_interrupted"})
                        self.transcript_tracker.reset_ai_turn()
                        continue

                    # Process authoritative output audio transcription
                    out_tx = getattr(server_content, "output_transcription", None)
                    if out_tx and hasattr(out_tx, "text") and out_tx.text:
                        self.transcript_tracker.ai_audio_transcript_emitted = True
                        self.transcript_tracker.ai_delta_seq += 1
                        await self.emit({
                            "type": "ai_transcript_delta",
                            "turn_id": self.transcript_tracker.current_ai_turn_id,
                            "speaker": "ai",
                            "delta": out_tx.text,
                            "sequence": self.transcript_tracker.ai_delta_seq,
                            "model_id": self.active_model_id
                        })

                    # Process audio PCM chunks
                    if model_turn:
                        for part in getattr(model_turn, "parts", []):
                            inline_data = getattr(part, "inline_data", None)
                            if inline_data and getattr(inline_data, "mime_type", "").startswith("audio/"):
                                raw_pcm = inline_data.data
                                b64_pcm = base64.b64encode(raw_pcm).decode("utf-8")
                                await self.emit({
                                    "type": "ai_audio_chunk",
                                    "pcm": b64_pcm,
                                    "rate": 24000
                                })

                    # Process authoritative user microphone transcription
                    in_tx = getattr(server_content, "input_transcription", None)
                    if in_tx and hasattr(in_tx, "text") and in_tx.text:
                        self.transcript_tracker.user_delta_seq += 1
                        await self.emit({
                            "type": "user_transcript_delta",
                            "turn_id": self.transcript_tracker.current_user_turn_id,
                            "speaker": "user",
                            "delta": in_tx.text,
                            "sequence": self.transcript_tracker.user_delta_seq
                        })

                    turn_complete = getattr(server_content, "turn_complete", False)
                    if turn_complete:
                        await self.emit({"type": "ai_turn_complete"})
                        self.transcript_tracker.reset_ai_turn()
                        self.transcript_tracker.reset_user_turn()

                # 2. Handle Non-Blocking Asynchronous Tool Calls (Section 16 & 21)
                if tool_call:
                    await self.transition_to(LiveState.TOOL_RUNNING)
                    function_calls = getattr(tool_call, "function_calls", [])
                    function_responses = []

                    for fc in function_calls:
                        tool_name = getattr(fc, "name", "").replace("_", ".")
                        call_id = getattr(fc, "id", "")
                        args = getattr(fc, "args", {})

                        log_event(f"Executing tool {tool_name} from Live voice", channel="tool")
                        await self.emit({
                            "type": "log",
                            "level": "thinking",
                            "message": f"[AI] Running {tool_name}..."
                        })

                        exec_context = {
                            "user_id": self.user_id,
                            "username": self.username,
                            "slug": self.slug,
                            "active_live_model": self.active_model_id
                        }

                        res = await tool_registry.execute(
                            tool_name=tool_name,
                            arguments=args,
                            context=exec_context
                        )

                        function_responses.append(types.FunctionResponse(
                            name=getattr(fc, "name", ""),
                            id=call_id,
                            response={"result": res.model_dump()}
                        ))

                    if self.session and function_responses:
                        try:
                            await self.session.send_tool_response(function_responses=function_responses)
                        except Exception as send_err:
                            logger.error(f"[LIVE TOOL RESPONSE ERROR] {send_err}")

                    await self.transition_to(LiveState.CONNECTED)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[LIVE RECEIVE LOOP ERROR] {e}", exc_info=True)
            await self.transition_to(LiveState.ERROR, reason=str(e))

    async def disconnect(self) -> None:
        """Closes the Live session and releases all resources cleanly."""
        if self.receive_task:
            self.receive_task.cancel()
            self.receive_task = None

        self.screenshare.stop()
        await self._cleanup_pending()
        await self.transition_to(LiveState.DISCONNECTED)
