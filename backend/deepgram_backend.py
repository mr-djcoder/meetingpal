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
        self._committed: list[str] = []  # is_final chunks of the utterance in progress

    def handle(self, result: dict) -> None:
        """Deepgram `is_final` marks a *chunk* as stable, not the utterance as complete.
        An utterance ends on `speech_final` (endpoint) or an UtteranceEnd event, so we
        accumulate stable chunks and only emit a final segment at the endpoint. This
        keeps half-sentences from being treated as finished questions."""
        if result.get("type") == "UtteranceEnd":
            self._finalize_pending()
            return
        alts = result.get("channel", {}).get("alternatives", [{}])
        text = (alts[0].get("transcript") or "").strip()
        speech_final = bool(result.get("speech_final"))
        if not text:
            if speech_final:
                self._finalize_pending()
            return
        if result.get("is_final"):
            self._committed.append(text)
            self._emit_text(" ".join(self._committed), is_final=speech_final)
            if speech_final:
                self._reset()
        else:
            self._emit_text(" ".join(self._committed + [text]), is_final=False)

    def _finalize_pending(self) -> None:
        if self._committed:
            self._emit_text(" ".join(self._committed), is_final=True)
        self._reset()

    def flush(self) -> None:
        """Finalize whatever is pending (called when the session stops)."""
        self._finalize_pending()

    def _reset(self) -> None:
        self._committed = []
        self._current_id = None

    def _emit_text(self, text: str, is_final: bool) -> None:
        if self._current_id is None:
            self._current_id = str(uuid.uuid4())
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


import asyncio
import inspect
import threading
from collections import deque

MAX_QUEUED_FRAMES = 50  # ~25s at 0.5s frames; drop oldest beyond this (backpressure)


class DeepgramBackend:
    RECONNECT_DELAYS_S = (1.0, 2.0, 4.0)  # per attempt after an unexpected close

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
        self._stopping = False
        self._reconnecting: set[str] = set()

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
        if not self._conns:  # neither source connected — surface a clear, actionable error
            self._on_error("Cloud transcription unavailable — switch to Local in Settings "
                           "or check your connection / Deepgram key.")

    def _handlers(self, source: str):
        def on_message(result: dict):
            self._mappers[source].handle(result)
        def on_error(err):
            self._on_error(f"Cloud transcription error ({source}): {err}")
        return on_message, on_error

    async def _open(self, source: str):
        on_message, on_error = self._handlers(source)
        return self._conn_factory(source, on_message, on_error)

    def _on_closed(self, source: str) -> None:
        """Connection dropped unexpectedly (called from the SDK's thread)."""
        if self._stopping or source in self._reconnecting or not self._thread.is_alive():
            return
        self._reconnecting.add(source)
        self._conns.pop(source, None)  # feed() drops audio for this source until back
        asyncio.run_coroutine_threadsafe(self._reconnect(source), self._loop)

    async def _reconnect(self, source: str) -> None:
        loop = asyncio.get_running_loop()
        try:
            for delay in self.RECONNECT_DELAYS_S:
                if self._stopping:
                    return
                await asyncio.sleep(delay)
                try:
                    on_message, on_error = self._handlers(source)
                    conn = await loop.run_in_executor(
                        None, self._conn_factory, source, on_message, on_error)
                except Exception:
                    continue
                self._conns[source] = conn
                self._on_error(f"Cloud transcription reconnected ({source}).")
                return
            self._on_error(f"Cloud transcription lost the {source} connection and could not "
                           "reconnect. Stop and start the recording, or switch to Local.")
        finally:
            self._reconnecting.discard(source)

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
        self._stopping = True
        for mapper in self._mappers.values():
            try:
                mapper.flush()  # emit any utterance still in progress as final
            except Exception:
                pass

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
            self._thread.join(timeout=2)  # don't leak the loop thread

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
        conn.on(LiveTranscriptionEvents.UtteranceEnd,
                lambda _s, result, **kw: on_message(result.to_dict()))
        conn.on(LiveTranscriptionEvents.Close,
                lambda _s, *a, **kw: self._on_closed(source))
        conn.start(LiveOptions(
            model="nova-2", language="en-US", encoding="linear16",
            sample_rate=16000, channels=1, interim_results=True,
            endpointing=300, utterance_end_ms="1000", diarize=False,
        ))
        return conn
