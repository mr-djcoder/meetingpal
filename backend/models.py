"""Shared data model dataclasses used across the backend."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


@dataclass
class TranscriptSegment:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    speaker: Literal["You", "Them"] = "You"
    wall_clock_time: datetime = field(default_factory=datetime.now)
    session_offset_seconds: float = 0.0
    text: str = ""
    is_final: bool = True
    audio_source: Literal["mic", "loopback", "mixed"] = "mixed"
    confidence: float = 1.0

    def to_ws_dict(self) -> dict:
        return {
            "type": "transcript_segment",
            "id": self.id,
            "session_id": self.session_id,
            "speaker": self.speaker,
            "wall_clock_time": self.wall_clock_time.isoformat() + "Z",
            "session_offset_seconds": self.session_offset_seconds,
            "text": self.text,
            "is_final": self.is_final,
            "confidence": self.confidence,
        }


@dataclass
class ChatMessage:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    role: Literal["user", "assistant"] = "user"
    content: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    transcript_snapshot_count: int = 0


@dataclass
class RecordingSession:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    started_at: datetime = field(default_factory=datetime.now)
    stopped_at: datetime | None = None
    status: Literal["recording", "stopped"] = "recording"
    save_path: str | None = None
    segments: list[TranscriptSegment] = field(default_factory=list)
    chat_messages: list[ChatMessage] = field(default_factory=list)


@dataclass
class AudioDevice:
    index: int
    name: str
    device_type: Literal["microphone", "loopback"]
    channels: int
    default_sample_rate: float
    is_default: bool
