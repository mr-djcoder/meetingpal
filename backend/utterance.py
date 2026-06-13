"""Caption-style utterance assembler — pure state machine, audio-time driven."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Callable, Literal

import numpy as np

from backend.models import TranscriptSegment

SAMPLE_RATE = 16000
SENTENCE_END: frozenset[str] = frozenset({".", "?", "!"})

TranscribeFn = Callable[[np.ndarray, int], str]
EmitFn = Callable[[TranscriptSegment], None]


def clean_text(text: str) -> str:
    """Strip and drop empty / pure-punctuation hallucination tails (e.g. '// // //')."""
    t = text.strip()
    if not t:
        return ""
    if not t.replace("/", "").replace(".", "").replace(" ", "").strip():
        return ""
    return t


class UtteranceAssembler:
    def __init__(
        self,
        transcribe_fn: TranscribeFn,
        emit_fn: EmitFn,
        session_id: str,
        *,
        partial_interval_s: float = 1.5,
        silence_finalize_s: float = 0.7,
        max_utterance_s: float = 15.0,
        partial_beam: int = 1,
        final_beam: int = 5,
    ) -> None:
        self._transcribe_fn = transcribe_fn
        self._emit_fn = emit_fn
        self._session_id = session_id
        self._partial_interval_s = partial_interval_s
        self._silence_finalize_s = silence_finalize_s
        self._max_utterance_s = max_utterance_s
        self._partial_beam = partial_beam
        self._final_beam = final_beam

        self._chunks: list[np.ndarray] = []
        self._current_id: str | None = None
        self._speaker: Literal["You", "Them"] = "You"
        self._silence_run_s = 0.0
        self._audio_since_partial_s = 0.0
        self._last_wall_clock: datetime | None = None
        self._last_offset = 0.0

    def process(
        self,
        frame: np.ndarray,
        is_speech: bool,
        mic_rms: float,
        lb_rms: float,
        wall_clock: datetime,
        offset: float,
    ) -> None:
        self._last_wall_clock = wall_clock
        self._last_offset = offset
        frame_s = len(frame) / SAMPLE_RATE

        if is_speech:
            if self._current_id is None:
                self._start_utterance(mic_rms, lb_rms)
            self._chunks.append(frame)
            self._silence_run_s = 0.0
            self._audio_since_partial_s += frame_s

            if self._buffered_s() >= self._max_utterance_s:
                self._finalize()
                return

            if self._audio_since_partial_s >= self._partial_interval_s:
                text = self._transcribe(self._partial_beam)
                self._audio_since_partial_s = 0.0
                if text and text[-1] in SENTENCE_END:
                    self._finalize_with(text)
                elif text:
                    self._emit_segment(text, is_final=False)
        else:
            if self._current_id is not None:
                self._silence_run_s += frame_s
                if self._silence_run_s >= self._silence_finalize_s:
                    self._finalize()

    def flush(self) -> None:
        """Finalize any in-progress utterance; call at session end."""
        if self._current_id is not None:
            self._finalize()

    def _buffered_s(self) -> float:
        return sum(len(c) for c in self._chunks) / SAMPLE_RATE

    def _start_utterance(self, mic_rms: float, lb_rms: float) -> None:
        self._current_id = str(uuid.uuid4())
        self._speaker = "You" if mic_rms >= lb_rms else "Them"
        self._chunks = []
        self._silence_run_s = 0.0
        self._audio_since_partial_s = 0.0

    def _transcribe(self, beam: int) -> str:
        if not self._chunks:
            return ""
        buffer = np.concatenate(self._chunks)
        return clean_text(self._transcribe_fn(buffer, beam))

    def _finalize(self) -> None:
        self._finalize_with(self._transcribe(self._final_beam))

    def _finalize_with(self, text: str) -> None:
        if text:
            self._emit_segment(text, is_final=True)
        self._reset()

    def _reset(self) -> None:
        self._current_id = None
        self._chunks = []
        self._silence_run_s = 0.0
        self._audio_since_partial_s = 0.0

    def _emit_segment(self, text: str, is_final: bool) -> None:
        assert self._current_id is not None, "_emit_segment called outside an active utterance"
        seg = TranscriptSegment(
            id=self._current_id,
            session_id=self._session_id,
            speaker=self._speaker,
            wall_clock_time=self._last_wall_clock or datetime.now(),
            session_offset_seconds=self._last_offset,
            text=text,
            is_final=is_final,
            audio_source="mixed",
            confidence=1.0,
        )
        self._emit_fn(seg)
