"""
Authoritative Studio WebSocket endpoint for Yulya Studio V2 (/ws/studio).
Coordinates real-time Live voice streaming, Mute/Unmute state, screenshare vision,
and build orchestrator progress events (Sections 12, 13, 21, 40).
"""

import json
import time
import asyncio
from typing import Optional, Dict, Any
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from backend.app.core.config import settings
from backend.app.core.logging import logger, log_event
from backend.app.database import repositories
from backend.app.voice.live_manager import LiveSessionManager
from backend.app.ai import orchestrator

router = APIRouter(prefix="", tags=["WebSocket"])


@router.websocket("/ws/studio")
async def websocket_studio_endpoint(
    websocket: WebSocket,
    slug: str = Query(...),
    token: Optional[str] = Query(None)
):
    """
    Authoritative Studio WebSocket connection.
    Authenticates creator via cookie or query token.
    """
    await websocket.accept()

    # 1. Authenticate session
    session_token = websocket.cookies.get(settings.COOKIE_NAME) or token
    if not session_token:
        await websocket.send_json({"type": "error", "message": "Authentication required for Studio."})
        await websocket.close(code=1008)
        return

    session_doc = await repositories.get_session(session_token)
    if not session_doc:
        await websocket.send_json({"type": "error", "message": "Invalid or expired session token."})
        await websocket.close(code=1008)
        return

    user = session_doc.get("user", {})
    user_id = user.get("id")
    username = user.get("username", "user")

    if not user_id:
        await websocket.close(code=1008)
        return

    # 2. Setup build event forwarder queue
    build_queue: asyncio.Queue = asyncio.Queue()
    orchestrator.subscribe_to_build_events(user_id, slug, build_queue)

    async def _emit_to_ws(msg: Dict[str, Any]) -> None:
        try:
            await websocket.send_json(msg)
        except Exception:
            pass

    # 3. Instantiate Live Session Manager
    api_key = await repositories.get_decrypted_user_api_key(user_id) or ""
    live_manager = LiveSessionManager(
        user_id=user_id,
        username=username,
        slug=slug,
        api_key=api_key,
        emit_callback=_emit_to_ws
    )

    # 4. Background task forwarding build events to client
    async def _build_event_forwarder():
        try:
            while True:
                event_dict = await build_queue.get()
                await websocket.send_json({
                    "type": "build_event",
                    "event": event_dict
                })
        except asyncio.CancelledError:
            pass

    forwarder_task = asyncio.create_task(_build_event_forwarder())

    # Send initial connection acknowledgment
    await websocket.send_json({
        "type": "status",
        "connected": True,
        "slug": slug,
        "user_id": user_id,
        "username": username
    })

    try:
        while True:
            raw_msg = await websocket.receive_text()
            try:
                data = json.loads(raw_msg)
            except Exception:
                continue

            msg_type = data.get("type")

            if msg_type == "heartbeat":
                await websocket.send_json({"type": "heartbeat_ack", "timestamp": time.time()})

            elif msg_type == "connect_live":
                pref_model = data.get("model")
                # Refresh user API key in case it was updated in settings
                live_manager.api_key = await repositories.get_decrypted_user_api_key(user_id) or ""
                if not live_manager.api_key:
                    await websocket.send_json({
                        "type": "live_error",
                        "message": "Google AI Studio API key not found. Please connect your API key in Settings."
                    })
                    continue

                asyncio.create_task(live_manager.connect(preferred_model_id=pref_model))

            elif msg_type == "disconnect_live":
                asyncio.create_task(live_manager.disconnect())

            elif msg_type == "mute_audio":
                live_manager.set_muted(True)
                await websocket.send_json({"type": "mic_state", "is_muted": True})

            elif msg_type == "unmute_audio":
                live_manager.set_muted(False)
                await websocket.send_json({"type": "mic_state", "is_muted": False})

            elif msg_type == "audio_chunk":
                pcm_data = data.get("pcm")
                if pcm_data:
                    await live_manager.handle_audio_chunk(pcm_data)

            elif msg_type == "video_frame":
                frame_data = data.get("data")
                if frame_data:
                    await live_manager.handle_video_frame(frame_data)

            elif msg_type == "command":
                prompt = data.get("prompt")
                if prompt:
                    asyncio.create_task(orchestrator.execute_build_task(
                        user_id=user_id,
                        username=username,
                        slug=slug,
                        prompt=prompt,
                        source="websocket_command"
                    ))

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning(f"[WS ERROR] Connection exception: {e}")
    finally:
        forwarder_task.cancel()
        orchestrator.unsubscribe_from_build_events(user_id, slug, build_queue)
        await live_manager.disconnect()
