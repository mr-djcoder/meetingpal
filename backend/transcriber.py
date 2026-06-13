"""faster-whisper transcription pipeline — single worker thread."""
from __future__ import annotations

import queue
import threading
import uuid
from datetime import datetime
from typing import Callable, Literal

import numpy as np
from faster_whisper import WhisperModel

from backend.diarizer import get_speaker
from backend.models import TranscriptSegment
from backend.vad import SileroVAD

DownloadProgressCallback = Callable[[float], None]


class WhisperTranscriber:
    def __init__(
        self,
        model_name: str = "base.en",
        emit_callback: Callable[[TranscriptSegment], None] | None = None,
        download_progress_cb: DownloadProgressCallback | None = None,
    ) -> None:
        self._model_name = model_name
        self._emit_callback = emit_callback
        self._download_progress_cb = download_progress_cb
        self._model: WhisperModel | None = None
        self._model_loaded = False
        self._queue: queue.Queue[tuple[np.ndarray, float, float, str, datetime, float] | None] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._vad: SileroVAD | None = None  # lazy-loaded in load_model()
        self._last_text = ""
        self._session_started_at: datetime | None = None
        self._session_id: str = ""

    @property
    def model_loaded(self) -> bool:
        return self._model_loaded

    def load_model(self, name: str | None = None) -> None:
        """Load (or reload) the Whisper model. Blocks until ready."""
        if name:
            self._model_name = name
        self._model_loaded = False
        # Stop existing worker if any
        if self._worker and self._worker.is_alive():
            self._queue.put(None)
            self._worker.join(timeout=5)

        # Lazy-load VAD on first model load
        if self._vad is None:
            self._vad = SileroVAD()

        try:
            self._model = WhisperModel(
                self._model_name,
                device="cuda",
                compute_type="float16",
            )
        except Exception:
            self._model = WhisperModel(
                self._model_name,
                device="cpu",
                compute_type="int8",
            )
        self._model_loaded = True

    def start(self, session_id: str, session_started_at: datetime) -> None:
        """Start the worker thread for a new session."""
        self._session_id = session_id
        self._session_started_at = session_started_at
        self._last_text = ""
        self._vad.reset()
        self._stop_event.clear()
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()

    def stop(self) -> None:
        """Signal the worker to stop and wait for it to drain the queue."""
        self._stop_event.set()
        self._queue.put(None)  # sentinel
        if self._worker:
            self._worker.join(timeout=10)

    def enqueue(self, chunk: np.ndarray, mic_rms: float, loopback_rms: float) -> None:
        """Enqueue a 3s audio chunk for transcription."""
        now = datetime.now()
        offset = 0.0
        if self._session_started_at:
            offset = (now - self._session_started_at).total_seconds()
        self._queue.put((chunk, mic_rms, loopback_rms, self._session_id, now, offset))

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                item = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue
            if item is None:
                break
            chunk, mic_rms, loopback_rms, session_id, wall_clock, offset = item
            self._process_chunk(chunk, mic_rms, loopback_rms, session_id, wall_clock, offset)
            self._queue.task_done()

    def _process_chunk(
        self,
        chunk: np.ndarray,
        mic_rms: float,
        loopback_rms: float,
        session_id: str,
        wall_clock: datetime,
        offset: float,
    ) -> None:
        if self._model is None:
            return
        # VAD gate
        if self._vad is None or not self._vad.is_speech(chunk):
            return
        # Transcribe
        try:
            segments, _info = self._model.transcribe(
                chunk,
                beam_size=5,
                vad_filter=True,
                condition_on_previous_text=True,
                temperature=0.0,
                word_timestamps=False,
            )
            text = " ".join(s.text.strip() for s in segments).strip()
        except Exception:
            return
        if not text or text == self._last_text:
            return
        self._last_text = text
        confidence = 1.0  # faster-whisper doesn't expose no_speech_prob directly in this path
        speaker = get_speaker(mic_rms, loopback_rms)
        seg = TranscriptSegment(
            id=str(uuid.uuid4()),
            session_id=session_id,
            speaker=speaker,
            wall_clock_time=wall_clock,
            session_offset_seconds=offset,
            text=text,
            is_final=True,
            audio_source="mixed",
            confidence=confidence,
        )
        if self._emit_callback:
            self._emit_callback(seg)
