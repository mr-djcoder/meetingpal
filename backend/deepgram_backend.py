# backend/deepgram_backend.py
"""Deepgram cloud transcription backend — two WS connections, one per source."""
from __future__ import annotations

import numpy as np


def pcm_float32_to_int16(frame: np.ndarray) -> bytes:
    """Convert float32 [-1, 1] mono audio to little-endian int16 PCM bytes."""
    clipped = np.clip(frame, -1.0, 1.0)
    return (clipped * 32767.0).astype("<i2").tobytes()


import uuid
from datetime import datetime
from typing import Callable

from backend.models import TranscriptSegment

EmitFn = Callable[[TranscriptSegment], None]


class DeepgramStreamMapper:
    """Maps one source's Deepgram results to TranscriptSegments with stable ids."""

    def __init__(self, source: str, session_id: str, emit: EmitFn,
                 started_at: datetime | None = None) -> None:
        self._source = source
        self._speaker = "You" if source == "mic" else "Them"
        self._session_id = session_id
        self._emit = emit
        self._started_at = started_at or datetime.now()
        self._current_id: str | None = None

    def handle(self, result: dict) -> None:
        alts = result.get("channel", {}).get("alternatives", [{}])
        text = (alts[0].get("transcript") or "").strip()
        if not text:
            return
        if self._current_id is None:
            self._current_id = str(uuid.uuid4())
        is_final = bool(result.get("is_final"))
        now = datetime.now()
        seg = TranscriptSegment(
            id=self._current_id,
            session_id=self._session_id,
            speaker=self._speaker,
            wall_clock_time=now,
            session_offset_seconds=(now - self._started_at).total_seconds(),
            text=text,
            is_final=is_final,
            audio_source=self._source,
            confidence=1.0,
        )
        self._emit(seg)
        if is_final:
            self._current_id = None  # next result starts a new utterance
