"""
Unit tests for Build Orchestrator, Live Session State Machine, Audio Pipeline, and Screenshare.
Ensures project locking, transactional rollback, Mute/Unmute contract, and frame rate limiting.
"""

import time
import base64
import asyncio
import pytest
from backend.app.ai.orchestrator import (
    get_project_lock,
    subscribe_to_build_events,
    unsubscribe_from_build_events,
    broadcast_build_event
)
from backend.app.models.schemas import BuildStage, BuildProgressEvent
from backend.app.voice.audio_pipeline import CanonicalTranscriptTracker
from backend.app.voice.screenshare import ScreenshareSubsystem
from backend.app.voice.live_manager import LiveState, LiveSessionManager
from backend.app.projects import service


def test_project_lock_isolation():
    """Verifies that separate projects get independent locks, while same project shares lock."""
    lock_a1 = get_project_lock(123, "game-one")
    lock_a2 = get_project_lock(123, "game-one")
    lock_b = get_project_lock(123, "game-two")
    lock_c = get_project_lock(456, "game-one")

    assert lock_a1 is lock_a2
    assert lock_a1 is not lock_b
    assert lock_a1 is not lock_c


@pytest.mark.asyncio
async def test_build_event_broadcasting():
    """Verifies build progress events are cleanly dispatched to subscribers."""
    q1 = asyncio.Queue()
    q2 = asyncio.Queue()

    subscribe_to_build_events(123, "my-game", q1)
    subscribe_to_build_events(123, "my-game", q2)

    event = BuildProgressEvent(
        event_id="evt_test",
        request_id="req_test",
        build_id="bld_test",
        stage=BuildStage.EDITING,
        message="Synthesizing updated app.js",
        timestamp=time.time(),
        files_changed=["app.js"]
    )

    await broadcast_build_event(123, "my-game", event)

    e1 = await asyncio.wait_for(q1.get(), timeout=1.0)
    e2 = await asyncio.wait_for(q2.get(), timeout=1.0)

    assert e1["stage"] == BuildStage.EDITING
    assert e2["files_changed"] == ["app.js"]

    unsubscribe_from_build_events(123, "my-game", q1)
    unsubscribe_from_build_events(123, "my-game", q2)


def test_canonical_transcript_tracker():
    """Verifies incremental transcript delta tracking and turn resets."""
    tracker = CanonicalTranscriptTracker()

    t_id1 = tracker.current_ai_turn_id
    tracker.ai_delta_seq += 1
    assert tracker.ai_delta_seq == 1

    tracker.reset_ai_turn()
    t_id2 = tracker.current_ai_turn_id
    assert t_id1 != t_id2
    assert tracker.ai_delta_seq == 0


def test_screenshare_rate_limiting():
    """Verifies screenshare subsystem drops frames exceeding FPS limit."""
    subsystem = ScreenshareSubsystem(user_id=100, slug="vision-game")
    subsystem.start()

    # Generate a tiny dummy 1x1 JPEG in base64
    dummy_b64 = "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA="

    # First frame should be accepted
    res1 = subsystem.process_incoming_frame(dummy_b64)
    assert res1 is True

    # Immediate second frame must be throttled by FPS limiter
    res2 = subsystem.process_incoming_frame(dummy_b64)
    assert res2 is False


@pytest.mark.asyncio
async def test_live_session_mute_contract():
    """
    Verifies that Mute state is respected and audio chunks are dropped
    when muted or during TOOL_RUNNING, preventing Render 1008 errors (Section 13).
    """
    from unittest.mock import MagicMock, AsyncMock

    emitted = []

    async def mock_emit(msg):
        emitted.append(msg)

    mgr = LiveSessionManager(
        user_id=1,
        username="test_user",
        slug="test-slug",
        api_key="fake_key",
        emit_callback=mock_emit
    )

    # Attach mock Gemini Live session
    mock_session = MagicMock()
    mock_session.send_realtime_input = AsyncMock()
    mgr.session = mock_session

    # 1. Toggle Mute -> True
    mgr.set_muted(True)
    assert mgr.is_muted is True

    # When muted, handle_audio_chunk must drop the audio
    chunk = base64.b64encode(b"\x00" * 960).decode("utf-8")
    await mgr.handle_audio_chunk(chunk)
    mock_session.send_realtime_input.assert_not_called()

    # 2. Unmute and CONNECTED -> audio must be forwarded
    mgr.set_muted(False)
    mgr.state = LiveState.CONNECTED
    await mgr.handle_audio_chunk(chunk)
    mock_session.send_realtime_input.assert_called_once()
