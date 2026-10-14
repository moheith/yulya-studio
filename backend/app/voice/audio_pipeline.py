"""
Audio pipeline helpers, turn identification, and canonical transcript tracking.
Follows Section 13 of Master Prompt.
"""

import time
import secrets


def generate_user_turn_id() -> str:
    """Generates unique namespaced turn ID for user speech."""
    return f"turn_user_{int(time.time()*1000)}_{secrets.token_hex(3)}"


def generate_ai_turn_id() -> str:
    """Generates unique namespaced turn ID for assistant speech."""
    return f"turn_ai_{int(time.time()*1000)}_{secrets.token_hex(3)}"


class CanonicalTranscriptTracker:
    """
    Enforces the single canonical transcript pipeline across Gemini Live (Section 13).
    Prevents duplicate text events and suppresses fallback raw part.text when audio transcript is present.
    """

    def __init__(self):
        self.current_user_turn_id: str = generate_user_turn_id()
        self.current_ai_turn_id: str = generate_ai_turn_id()
        self.ai_audio_transcript_emitted: bool = False
        self.user_delta_seq: int = 0
        self.ai_delta_seq: int = 0

    def reset_ai_turn(self) -> str:
        self.current_ai_turn_id = generate_ai_turn_id()
        self.ai_audio_transcript_emitted = False
        self.ai_delta_seq = 0
        return self.current_ai_turn_id

    def reset_user_turn(self) -> str:
        self.current_user_turn_id = generate_user_turn_id()
        self.user_delta_seq = 0
        return self.current_user_turn_id
