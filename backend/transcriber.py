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
from backend.utterance import UtteranceAssembler
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
        self._assembler: UtteranceAssembler | None = None

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

    def transcribe(self, buffer: np.ndarray, beam_size: int) -> str:
        """Transcribe a complete audio buffer to text. Called from the worker thread."""
        if self._model is None:
            return ""
        try:
            segments, _info = self._model.transcribe(
                buffer,
                beam_size=beam_size,
                vad_filter=True,
                condition_on_previous_text=False,
                temperature=0.0,
                word_timestamps=False,
            )
            return " ".join(s.text.strip() for s in segments).strip()
        except Exception:
            return ""

    def start(self, session_id: str, session_started_at: datetime) -> None:
        """Start the worker thread for a new session."""
        self._session_id = session_id
        self._session_started_at = session_started_at
        self._last_text = ""
        self._vad.reset()
        self._assembler = UtteranceAssembler(
            transcribe_fn=self.transcribe,
            emit_fn=self._emit_callback if self._emit_callback else (lambda _seg: None),
            session_id=session_id,
        )
        self._stop_event.clear()
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()

    def stop(self) -> None:
        """Signal the worker to stop and wait for it to drain the queue."""
        # Flush the assembler first so any in-progress utterance is finalized and
        # emitted before the worker is torn down.  flush() runs synchronously in the
        # calling thread; emit_callback merely schedules a broadcast so it is safe to
        # call here even though the worker is still running.
        if self._assembler:
            self._assembler.flush()
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
        if self._model is None or self._vad is None or self._assembler is None:
            return
        is_speech = self._vad.is_speech_frame(chunk)
        self._assembler.process(chunk, is_speech, mic_rms, loopback_rms, wall_clock, offset)
