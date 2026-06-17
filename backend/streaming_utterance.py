"""LocalAgreement-2 streaming utterance assembler.

Only the trailing uncommitted audio window is re-transcribed each partial; words
that two consecutive hypotheses agree on are committed (locked) and their audio is
dropped. This removes the O(n^2) re-transcription of the legacy assembler.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Callable, Literal

import numpy as np

from backend.models import TranscriptSegment
from backend.utterance import clean_text

SAMPLE_RATE = 16000

TranscribeFn = Callable[..., str]  # (buffer, beam, initial_prompt="") -> str
EmitFn = Callable[[TranscriptSegment], None]


def _common_prefix(a: list[str], b: list[str]) -> list[str]:
    out: list[str] = []
    for x, y in zip(a, b):
        if x == y:
            out.append(x)
        else:
            break
    return out


class StreamingUtteranceAssembler:
    def __init__(
        self,
        transcribe_fn: TranscribeFn,
        emit_fn: EmitFn,
        session_id: str,
        *,
        speaker: Literal["You", "Them"],
        partial_interval_s: float = 1.0,
        silence_finalize_s: float = 4.0,
        max_utterance_s: float = 30.0,
        min_window_s: float = 1.0,
        beam: int = 1,
    ) -> None:
        self._transcribe_fn = transcribe_fn
        self._emit_fn = emit_fn
        self._session_id = session_id
        self._speaker = speaker
        self._partial_interval_s = partial_interval_s
        self._silence_finalize_s = silence_finalize_s
        self._max_utterance_s = max_utterance_s
        self._min_window_s = min_window_s
        self._beam = beam

        self._current_id: str | None = None
        self._committed_words: list[str] = []     # locked prefix
        self._window: list[np.ndarray] = []        # uncommitted trailing audio
        self._prev_tail_words: list[str] = []      # last hypothesis tail (for agreement)
        self._silence_run_s = 0.0
        self._audio_since_partial_s = 0.0
        self._committed_audio_s = 0.0
        self._last_wall_clock: datetime | None = None
        self._last_offset = 0.0

    def flush(self) -> None:
        if self._current_id is not None:
            self._finalize()

    def committed_text(self) -> str:
        return " ".join(self._committed_words).strip()

    def _window_s(self) -> float:
        return sum(len(c) for c in self._window) / SAMPLE_RATE

    def _start_utterance(self) -> None:
        self._current_id = str(uuid.uuid4())
        self._committed_words = []
        self._window = []
        self._prev_tail_words = []
        self._committed_audio_s = 0.0
        self._silence_run_s = 0.0
        self._audio_since_partial_s = 0.0

    def process(self, frame, is_speech, wall_clock, offset) -> None:
        self._last_wall_clock = wall_clock
        self._last_offset = offset
        frame_s = len(frame) / SAMPLE_RATE

        if is_speech:
            if self._current_id is None:
                self._start_utterance()
            self._window.append(frame)
            self._silence_run_s = 0.0
            self._audio_since_partial_s += frame_s

            if self._committed_audio_s + self._window_s() >= self._max_utterance_s:
                self._finalize()
                return
            if (self._audio_since_partial_s >= self._partial_interval_s
                    and self._window_s() >= self._min_window_s):
                self._audio_since_partial_s = 0.0
                self._run_partial()
        else:
            if self._current_id is not None:
                self._silence_run_s += frame_s
                if self._silence_run_s >= self._silence_finalize_s:
                    self._finalize()

    def _run_partial(self) -> None:
        buf = np.concatenate(self._window)
        hyp = clean_text(self._transcribe_fn(buf, self._beam, initial_prompt=self.committed_text()))
        words = hyp.split()
        agreed = _common_prefix(words, self._prev_tail_words)
        if agreed:
            self._commit_words(agreed, words)
            tail_words = words[len(agreed):]
            self._prev_tail_words = []   # window changed; restart agreement
        else:
            tail_words = words
            self._prev_tail_words = words
        text = (self.committed_text() + " " + " ".join(tail_words)).strip()
        if text:
            self._emit_segment(text, is_final=False)

    def _commit_words(self, agreed: list[str], hyp_words: list[str]) -> None:
        self._committed_words.extend(agreed)
        if not self._window:
            return
        merged = np.concatenate(self._window)
        frac = min(1.0, len(agreed) / len(hyp_words)) if hyp_words else 1.0
        drop = int(frac * merged.size)
        kept = merged[drop:]
        self._committed_audio_s += drop / SAMPLE_RATE
        self._window = [kept] if kept.size else []

    def _finalize(self) -> None:
        text = self.committed_text()
        if self._window:
            buf = np.concatenate(self._window)
            tail = clean_text(self._transcribe_fn(buf, self._beam, initial_prompt=text))
            text = (text + " " + tail).strip()
        if text:
            self._emit_segment(text, is_final=True)
        self._reset()

    def _reset(self) -> None:
        self._current_id = None
        self._committed_words = []
        self._window = []
        self._prev_tail_words = []
        self._committed_audio_s = 0.0
        self._silence_run_s = 0.0
        self._audio_since_partial_s = 0.0

    def _emit_segment(self, text: str, is_final: bool) -> None:
        assert self._current_id is not None
        seg = TranscriptSegment(
            id=self._current_id,
            session_id=self._session_id,
            speaker=self._speaker,
            wall_clock_time=self._last_wall_clock or datetime.now(),
            session_offset_seconds=self._last_offset,
            text=text,
            is_final=is_final,
            audio_source="mic" if self._speaker == "You" else "loopback",
            confidence=1.0,
        )
        self._emit_fn(seg)
