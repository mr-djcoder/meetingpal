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


import asyncio
import inspect
import threading
from collections import deque

MAX_QUEUED_FRAMES = 50  # ~25s at 0.5s frames; drop oldest beyond this (backpressure)


class DeepgramBackend:
    def __init__(self, api_key, session_id, emit, on_error,
                 conn_factory=None, started_at=None):
        self._api_key = api_key
        self._session_id = session_id
        self._emit = emit
        self._on_error = on_error
        self._conn_factory = conn_factory or self._default_conn_factory
        self._started_at = started_at
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._conns: dict[str, object] = {}
        self._queues: dict[str, deque] = {"mic": deque(), "loopback": deque()}
        self._mappers: dict[str, DeepgramStreamMapper] = {}

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def start(self, session_id: str, started_at: datetime) -> None:
        self._started_at = started_at
        self._thread.start()
        for source in ("mic", "loopback"):
            self._mappers[source] = DeepgramStreamMapper(
                source, session_id, self._emit, started_at)
            fut = asyncio.run_coroutine_threadsafe(self._open(source), self._loop)
            try:
                self._conns[source] = fut.result(timeout=10)
            except Exception as e:  # connection failure → inform, no fallback
                self._on_error(f"Cloud transcription failed to connect ({source}): {e}")

    async def _open(self, source: str):
        def on_message(result: dict):
            self._mappers[source].handle(result)
        def on_error(err):
            self._on_error(f"Cloud transcription error ({source}): {err}")
        return self._conn_factory(source, on_message, on_error)

    def feed(self, source: str, frame: np.ndarray, rms: float) -> None:
        conn = self._conns.get(source)
        if conn is None:
            return
        pcm = pcm_float32_to_int16(frame)
        q = self._queues[source]
        q.append(pcm)
        while len(q) > MAX_QUEUED_FRAMES:
            q.popleft()  # drop oldest under backpressure
        asyncio.run_coroutine_threadsafe(self._drain(source), self._loop)

    async def _drain(self, source: str):
        conn = self._conns.get(source)
        q = self._queues[source]
        while q and conn is not None:
            data = q.popleft()
            try:
                # Real deepgram-sdk conn.send() is synchronous; test fakes are async.
                res = conn.send(data)
                if inspect.isawaitable(res):
                    await res
            except Exception as e:
                self._on_error(f"Cloud send failed ({source}): {e}")
                return

    def stop(self) -> None:
        async def _close():
            for c in self._conns.values():
                try:
                    # Real conn.finish() is synchronous; test fakes are async.
                    res = c.finish()
                    if inspect.isawaitable(res):
                        await res
                except Exception:
                    pass
        if self._thread.is_alive():
            fut = asyncio.run_coroutine_threadsafe(_close(), self._loop)
            try:
                fut.result(timeout=5)
            except Exception:
                pass
            self._loop.call_soon_threadsafe(self._loop.stop)

    def ready(self) -> bool:
        return True

    def _default_conn_factory(self, source, on_message, on_error):
        """Open a real Deepgram live WS. The key is passed to the SDK client (header
        auth) — never placed in the URL/query and never logged.

        deepgram-sdk v3 live transcription: model=nova-2, encoding=linear16,
        sample_rate=16000, channels=1, interim_results=True, endpointing on,
        diarize=False. `on_message` receives `result.to_dict()`.
        """
        from deepgram import DeepgramClient, LiveOptions, LiveTranscriptionEvents
        dg = DeepgramClient(self._api_key)  # header auth, key never logged
        conn = dg.listen.websocket.v("1")

        conn.on(LiveTranscriptionEvents.Transcript,
                lambda _s, result, **kw: on_message(result.to_dict()))
        conn.on(LiveTranscriptionEvents.Error,
                lambda _s, error, **kw: on_error(error))
        conn.start(LiveOptions(
            model="nova-2", language="en-US", encoding="linear16",
            sample_rate=16000, channels=1, interim_results=True,
            endpointing=300, diarize=False,
        ))
        return conn
