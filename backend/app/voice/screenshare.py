"""
Screenshare and visual frame processing subsystem for Yulya Studio V2.
Follows Section 15 of Master Prompt.
"""

import time
import base64
from typing import Optional, Dict, Any
from backend.app.core.config import settings
from backend.app.core.logging import logger
from backend.app.ai.tools.preview_tools import set_active_screen_frame, clear_active_screen_frame


class ScreenshareSubsystem:
    """Manages display capture frames, rate limiting, and vision delivery."""

    def __init__(self, user_id: int, slug: str):
        self.user_id = user_id
        self.slug = slug
        self.is_active: bool = False
        self.last_frame_time: float = 0.0
        self.latest_frame_bytes: Optional[bytes] = None
        self.latest_frame_b64: Optional[str] = None
        self.frames_received: int = 0
        self.frames_dropped: int = 0

    def start(self) -> None:
        self.is_active = True
        self.last_frame_time = 0.0

    def stop(self) -> None:
        self.is_active = False
        self.latest_frame_bytes = None
        self.latest_frame_b64 = None
        clear_active_screen_frame(self.user_id, self.slug)

    def process_incoming_frame(self, data_b64: str) -> bool:
        """
        Validates, rate-limits (~1 FPS), and retains the newest valid JPEG frame.
        Returns True if the frame was accepted, False if dropped.
        """
        if not self.is_active or not data_b64:
            self.frames_dropped += 1
            return False

        now = time.time()
        # Rate limit to ~1 frame per second
        min_interval = 1.0 / settings.SCREENSHOT_MAX_FPS
        if (now - self.last_frame_time) < (min_interval * 0.85):
            self.frames_dropped += 1
            return False

        try:
            # Strip data URL prefix if present
            clean_b64 = data_b64
            if "," in clean_b64:
                clean_b64 = clean_b64.split(",", 1)[1]

            frame_bytes = base64.b64decode(clean_b64)
            if len(frame_bytes) > settings.SCREENSHOT_MAX_BYTES:
                self.frames_dropped += 1
                return False

            # Verify JPEG header bytes (0xFF, 0xD8)
            if len(frame_bytes) < 2 or frame_bytes[0] != 0xFF or frame_bytes[1] != 0xD8:
                self.frames_dropped += 1
                return False

            self.latest_frame_bytes = frame_bytes
            self.latest_frame_b64 = clean_b64
            self.last_frame_time = now
            self.frames_received += 1

            set_active_screen_frame(self.user_id, self.slug, clean_b64)
            return True
        except Exception as e:
            logger.warning(f"[SCREENSHARE] Error processing frame: {e}")
            self.frames_dropped += 1
            return False
