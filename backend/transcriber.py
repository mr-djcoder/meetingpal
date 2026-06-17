"""faster-whisper transcription pipeline — single worker thread."""
from __future__ import annotations

import queue
import threading
from datetime import datetime
from typing import Callable

import numpy as np
from faster_whisper import WhisperModel

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
        self._queue: queue.Queue[tuple | None] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._stop_event = threading.Event()
        # One shared VAD: is_speech_frame analyses each 0.5s frame independently
        # (no cross-call state), so a single instance is safe for both sources and
        # halves native (torch) init vs one-per-source.
        self._vad: SileroVAD | None = None  # lazy-loaded in load_model()
        self._session_started_at: datetime | None = None
        self._session_id: str = ""
        self._mic_assembler: UtteranceAssembler | None = None
        self._lb_assembler: UtteranceAssembler | None = None

    @property
    def model_loaded(self) -> bool:
        return self._model_loaded

    def load_model(self, name: str | None = None) -> None:
        """Load (or reload) the Whisper model. Blocks until ready."""
        if name:
            self._model_name = name
        self._model_loaded = False
        if self._worker and self._worker.is_alive():
            self._queue.put(None)
            self._worker.join(timeout=5)

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
                vad_filter=False,  # Silero already gated each frame; skip whisper's VAD (faster)
                condition_on_previous_text=False,  # avoid latency from carrying context
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
        # Drop any frames left over from a previous session so the new one never
        # transcribes stale audio "after the fact" on stop/restart.
        self._drain_queue()
        if self._vad:
            self._vad.reset()
        emit = self._emit_callback if self._emit_callback else (lambda _seg: None)
        self._mic_assembler = UtteranceAssembler(self.transcribe, emit, session_id, speaker="You")
        self._lb_assembler = UtteranceAssembler(self.transcribe, emit, session_id, speaker="Them")
        self._stop_event.clear()
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()

    def stop(self) -> None:
        """Signal the worker to stop, wait for it to drain, then flush a final utterance."""
        self._stop_event.set()
        self._queue.put(None)  # sentinel
        if self._worker:
            self._worker.join(timeout=10)
        self._drain_queue()
        # Flush AFTER the worker has exited so the Whisper model is only ever accessed
        # by one thread at a time (WhisperModel is not thread-safe).
        if self._mic_assembler:
            self._mic_assembler.flush()
        if self._lb_assembler:
            self._lb_assembler.flush()

    def _drain_queue(self) -> None:
        """Discard all pending items in the queue without processing them."""
        try:
            while True:
                self._queue.get_nowait()
                self._queue.task_done()
        except queue.Empty:
            pass

    def enqueue(self, source: str, frame: np.ndarray, rms: float) -> None:
        """Enqueue a 0.5s audio frame for a source ('mic' or 'loopback')."""
        now = datetime.now()
        offset = 0.0
        if self._session_started_at:
            offset = (now - self._session_started_at).total_seconds()
        self._queue.put((source, frame, rms, self._session_id, now, offset))

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                item = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue
            if item is None:
                break
            source, frame, rms, session_id, wall_clock, offset = item
            self._process_chunk(source, frame, rms, session_id, wall_clock, offset)
            self._queue.task_done()

    def _process_chunk(
        self,
        source: str,
        frame: np.ndarray,
        rms: float,
        session_id: str,
        wall_clock: datetime,
        offset: float,
    ) -> None:
        if self._model is None or self._vad is None:
            return
        assembler = self._mic_assembler if source == "mic" else self._lb_assembler
        if assembler is None:
            return
        is_speech = self._vad.is_speech_frame(frame)
        assembler.process(frame, is_speech, wall_clock, offset)
