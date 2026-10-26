"""FastAPI sidecar entrypoint — registers all routes and manages app lifespan."""
from __future__ import annotations

import os
# Native-stability env: must be set BEFORE torch / ctranslate2 (faster-whisper) load.
# - KMP_DUPLICATE_LIB_OK: tolerate the duplicate Intel OpenMP runtime on Windows.
# - OMP/MKL thread caps: torch (Silero VAD) and ctranslate2 (Whisper) each spawn their
#   own OpenMP pool; uncapped, they oversubscribe the cores and intermittently fault
#   (0xC0000005). Cap them so the two native runtimes don't fight.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("OMP_NUM_THREADS", "4")
os.environ.setdefault("MKL_NUM_THREADS", "4")
os.environ.setdefault("OMP_WAIT_POLICY", "PASSIVE")

import argparse
import asyncio
import hmac
import json
import sys
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator

from backend.audio_capture import AudioCapture, enumerate_devices
from backend.auto_answer import AutoAnswerOrchestrator
from backend.claude_client import ClaudeClient
from backend.echo import EchoFilter
from backend.gemini_client import GeminiClient, list_gemini_models
from backend.models import ChatMessage, RecordingSession, TranscriptSegment, to_utc_iso
from backend.storage import (
    UserPreferences,
    allocate_session_folder,
    journal_segment,
    load_preferences,
    save_preferences,
    save_session,
)
from backend.transcriber import WhisperTranscriber

# ── App-wide state ────────────────────────────────────────────────────────────

# Shared secret between the Electron main process and this sidecar, generated per launch
# and passed through the environment. Unset only for standalone development.
API_TOKEN = os.environ.get("MEETINGPAL_TOKEN", "")
TOKEN_HEADER = "x-meetingpal-token"

transcriber: WhisperTranscriber | None = None
audio_capture: AudioCapture | None = None
active_session: RecordingSession | None = None
active_backend = None  # LocalBackend or DeepgramBackend for the running session
connected_websockets: set[WebSocket] = set()
prefs: UserPreferences = UserPreferences()
_api_key_memory: str | None = None  # Claude key, held in-process only, never on disk
_gemini_key_memory: str | None = None  # Gemini key, in-process only
_deepgram_key_memory: str | None = None  # Deepgram key, in-process only
event_loop: asyncio.AbstractEventLoop | None = None  # captured at startup for cross-thread scheduling
_server: uvicorn.Server | None = None  # set by __main__, lets /api/shutdown stop uvicorn
_pending_model: str | None = None  # Whisper reload requested mid-recording, applied at stop
_broadcast_lock = asyncio.Lock()  # serializes sends so partials/finals keep their order
_echo = EchoFilter()
_echo_ids: set[str] = set()  # utterance ids already identified as mic echo

_claude_client = ClaudeClient()
_gemini_client = GeminiClient()
auto_answer: AutoAnswerOrchestrator | None = None  # created at startup

SIDECAR_VERSION = "1.1.0"


# ── Lifespan ──────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    global transcriber, prefs, event_loop, auto_answer
    event_loop = asyncio.get_running_loop()
    auto_answer = AutoAnswerOrchestrator(_broadcast)
    prefs = load_preferences()
    transcriber = WhisperTranscriber(
        model_name=prefs.whisper_model,
        emit_callback=_on_transcript_segment,
        transcribe_mode=prefs.local_transcribe_mode,
        error_callback=_on_transcriber_error,
    )
    # Load model in background so health returns model_loaded=false while loading
    event_loop.run_in_executor(None, transcriber.load_model, None)
    yield
    if audio_capture:
        audio_capture.stop()
    if transcriber:
        transcriber.stop()


# ── FastAPI app ───────────────────────────────────────────────────────────────

# No CORS: the renderer never talks to this server (all traffic goes through the Electron
# main process), so no browser origin has any business calling it.
app = FastAPI(title="MeetingPal Sidecar", lifespan=lifespan)


def _token_ok(presented: str | None) -> bool:
    if not API_TOKEN:
        return True  # standalone development
    return hmac.compare_digest((presented or "").encode(), API_TOKEN.encode())


@app.middleware("http")
async def require_token(request: Request, call_next):
    if not _token_ok(request.headers.get(TOKEN_HEADER)):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    return await call_next(request)


# ── Helper ────────────────────────────────────────────────────────────────────


def _flush(msg: str) -> None:
    print(msg, flush=True)


async def _broadcast(data: dict) -> None:
    async with _broadcast_lock:
        dead: list[WebSocket] = []
        for ws in list(connected_websockets):
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            connected_websockets.discard(ws)


def _broadcast_threadsafe(data: dict) -> None:
    """Schedule a broadcast from any thread, preserving call order."""
    if event_loop is None:
        return
    event_loop.call_soon_threadsafe(lambda: asyncio.ensure_future(_broadcast(data)))


def _error_event(code: str, message: str, recoverable: bool = True) -> dict:
    return {"type": "error", "code": code, "message": message, "recoverable": recoverable}


def _on_transcriber_error(message: str) -> None:
    _broadcast_threadsafe(_error_event("local_transcription", message))


def _on_transcript_segment(seg: TranscriptSegment) -> None:
    """Called from transcriber / cloud worker threads; schedule broadcast on event loop."""
    session = active_session
    if prefs.suppress_echo and session is not None:
        if seg.speaker == "Them":
            _echo.note_other(seg.text)
        elif seg.id in _echo_ids or _echo.is_echo(seg.text):
            _suppress_echo(session, seg)
            return

    if session:
        # Partials and the final of one utterance share an id; upsert so the persisted
        # transcript (and the Claude context) holds one clean entry per utterance, not
        # every interim partial. The latest write (the final) wins.
        for i, existing in enumerate(session.segments):
            if existing.id == seg.id:
                session.segments[i] = seg
                break
        else:
            session.segments.append(seg)
        if seg.is_final and prefs.auto_save:
            # Crash safety: finalized text hits disk immediately, not only at stop.
            try:
                journal_segment(session, prefs, seg)
            except Exception as exc:
                _flush(f"[session] journal write failed: {exc}")
    _broadcast_threadsafe(seg.to_ws_dict())

    # Auto-answer: only a finalized question from the other party can fire it, so check
    # that before copying the (potentially large) transcript.
    if (
        auto_answer is not None and event_loop is not None
        and prefs.auto_answer_enabled and session is not None
        and seg.is_final and seg.speaker == "Them"
    ):
        segments_snapshot = list(session.segments)
        history_snapshot = list(session.chat_messages)
        event_loop.call_soon_threadsafe(
            lambda: asyncio.ensure_future(
                auto_answer.maybe_answer(
                    segment=seg,
                    prefs=prefs,
                    claude_key=_api_key_memory,
                    gemini_key=_gemini_key_memory,
                    claude_client=_claude_client,
                    gemini_client=_gemini_client,
                    segments=segments_snapshot,
                    history=history_snapshot,
                )
            )
        )


def _suppress_echo(session: RecordingSession, seg: TranscriptSegment) -> None:
    """Drop mic text that duplicates the other side; retract it if a partial already shipped."""
    _echo_ids.add(seg.id)
    before = len(session.segments)
    session.segments[:] = [s for s in session.segments if s.id != seg.id]
    if len(session.segments) != before:
        _broadcast_threadsafe({"type": "transcript_remove", "id": seg.id})


def _require_api_key(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer ") and auth[len("Bearer "):]:
        return auth[len("Bearer "):]
    if _api_key_memory:
        return _api_key_memory
    raise HTTPException(status_code=401, detail="Missing API key")


# ── Health ────────────────────────────────────────────────────────────────────


@app.get("/health")
def health():
    loaded = transcriber.model_loaded if transcriber else False
    _flush(f"[health] model_loaded={loaded}")
    return {"status": "healthy", "model_loaded": loaded, "sidecar_version": SIDECAR_VERSION}


# ── Devices ───────────────────────────────────────────────────────────────────


@app.get("/api/devices")
def get_devices():
    devices = enumerate_devices()
    return {"devices": [asdict(d) for d in devices]}


# ── Preferences ───────────────────────────────────────────────────────────────


@app.get("/api/preferences")
def get_preferences():
    return asdict(prefs)


NULLABLE_PREFS = {"mic_device_index", "loopback_device_index"}  # None = "system default"


class PrefsUpdate(BaseModel):
    whisper_model: Literal["base.en", "small.en", "medium.en"] | None = None
    claude_model: str | None = Field(default=None, min_length=1, max_length=100)
    mic_device_index: int | None = Field(default=None, ge=0)
    loopback_device_index: int | None = Field(default=None, ge=0)
    auto_save: bool | None = None
    save_path: str | None = Field(default=None, min_length=1, max_length=500)
    font_size: int | None = Field(default=None, ge=8, le=48)
    theme: Literal["dark", "light"] | None = None
    onboarding_completed: bool | None = None
    auto_answer_enabled: bool | None = None
    auto_answer_prompt: str | None = Field(default=None, max_length=4000)
    auto_answer_provider: Literal["claude", "gemini"] | None = None
    auto_answer_model: str | None = Field(default=None, max_length=100)
    chat_panel_visible: bool | None = None
    custom_titlebar: bool | None = None
    window_opacity: float | None = Field(default=None, ge=0.05, le=1.0)
    always_on_top: bool | None = None
    transcript_split: float | None = Field(default=None, ge=10, le=90)
    transcript_visible: bool | None = None
    transcription_engine: Literal["local", "cloud"] | None = None
    cloud_provider: Literal["deepgram"] | None = None
    local_transcribe_mode: Literal["streaming", "legacy"] | None = None
    suppress_echo: bool | None = None

    @field_validator("save_path")
    @classmethod
    def _absolute_path(cls, v: str | None) -> str | None:
        if v is not None and not Path(v).is_absolute():
            raise ValueError("save_path must be an absolute path")
        return v


@app.put("/api/preferences")
def update_preferences(body: PrefsUpdate):
    global prefs, _pending_model
    # model_fields_set (not exclude_none) so a device index can be reset to None.
    data = {
        k: getattr(body, k)
        for k in body.model_fields_set
        if getattr(body, k) is not None or k in NULLABLE_PREFS
    }
    old_model = prefs.whisper_model
    for k, v in data.items():
        if hasattr(prefs, k):
            setattr(prefs, k, v)
    save_preferences(prefs)
    # Hot-reload Whisper model if it changed. Never mid-recording: reloading stops the
    # worker thread, which would silently kill the live session's transcription.
    if "whisper_model" in data and data["whisper_model"] != old_model and transcriber and event_loop:
        if active_session and active_session.status == "recording":
            _pending_model = prefs.whisper_model
            _flush(f"[prefs] Whisper model change to {prefs.whisper_model} deferred until recording stops")
        else:
            event_loop.run_in_executor(None, transcriber.load_model, prefs.whisper_model)
            _flush(f"[prefs] reloading Whisper model: {prefs.whisper_model}")
    # Swap the local assembler (streaming/legacy kill-switch) — cheap, applies next session.
    if "local_transcribe_mode" in data and transcriber:
        transcriber.set_transcribe_mode(prefs.local_transcribe_mode)
        _flush(f"[prefs] local transcribe mode: {prefs.local_transcribe_mode}")
    return asdict(prefs)


# ── API Key ───────────────────────────────────────────────────────────────────


class KeyBody(BaseModel):
    api_key: str


@app.post("/api/key")
def store_key(body: KeyBody):
    global _api_key_memory
    _api_key_memory = body.api_key
    _flush("[key] API key stored in memory")
    return {"stored": True}


@app.post("/api/key/gemini")
def store_gemini_key(body: KeyBody):
    global _gemini_key_memory
    _gemini_key_memory = body.api_key
    _flush("[key] Gemini API key stored in memory")
    return {"stored": True}


@app.post("/api/key/deepgram")
def store_deepgram_key(body: KeyBody):
    global _deepgram_key_memory
    _deepgram_key_memory = body.api_key
    _flush("[key] Deepgram API key stored in memory")
    return {"stored": True}


@app.get("/api/engine/status")
def engine_status():
    device = transcriber.device if transcriber else "unknown"
    # Cloud needs no local model; local is ready once Whisper has loaded.
    ready = (
        prefs.transcription_engine == "cloud"
        or (transcriber.model_loaded if transcriber else False)
    )
    # Report the model actually loaded (auto-upgraded to a large model on GPU), falling
    # back to the configured one before load completes.
    model = transcriber.active_model if (transcriber and transcriber.model_loaded) else prefs.whisper_model
    return {
        "engine": prefs.transcription_engine,
        "device": "GPU (CUDA)" if device == "cuda" else "CPU" if device == "cpu" else "unknown",
        "model": model,
        "configured_model": prefs.whisper_model,
        # True when the GPU path loaded a different model than the Settings choice.
        "model_overridden": model != prefs.whisper_model,
        "mode": prefs.local_transcribe_mode,
        "cloud_provider": prefs.cloud_provider,
        "ready": ready,
    }


@app.get("/api/gemini/models")
async def gemini_models():
    """List Gemini models for the picker; falls back to a static set without a key."""
    if not _gemini_key_memory:
        from backend.gemini_client import FALLBACK_GEMINI_MODELS
        return {"models": list(FALLBACK_GEMINI_MODELS)}
    return {"models": await list_gemini_models(_gemini_key_memory)}


# ── Session ───────────────────────────────────────────────────────────────────


class StartSessionBody(BaseModel):
    mic_device_index: int | None = None
    loopback_device_index: int | None = None
    duration_limit_seconds: int | None = None


def _start_workers(session: RecordingSession, mic_idx: int | None, loopback_idx: int | None):
    """Blocking part of session start (PortAudio init, cloud connect). Runs in a thread."""
    from backend.transcription_backend import LocalBackend
    from backend.deepgram_backend import DeepgramBackend

    if prefs.transcription_engine == "cloud":
        backend = DeepgramBackend(
            api_key=_deepgram_key_memory,
            session_id=session.id,
            emit=_on_transcript_segment,
            on_error=lambda msg: _broadcast_threadsafe(_error_event("cloud_transcription", msg)),
            started_at=session.started_at,
        )
    else:
        backend = LocalBackend(transcriber)

    capture = AudioCapture(
        chunk_callback=lambda source, frame, rms: backend.feed(source, frame, rms),
        mic_device_index=mic_idx,
        loopback_device_index=loopback_idx,
    )
    backend.start(session.id, session.started_at)
    try:
        failures = capture.start()
    except Exception:
        backend.stop()
        raise
    return backend, capture, failures


@app.post("/api/session/start")
async def start_session(body: StartSessionBody, request: Request):
    global active_session, audio_capture, active_backend

    if active_session and active_session.status == "recording":
        raise HTTPException(
            status_code=409,
            detail={"error": "A recording session is already active", "session_id": active_session.id},
        )

    if prefs.transcription_engine == "cloud":
        if not _deepgram_key_memory:
            raise HTTPException(status_code=400, detail="Cloud engine selected but no Deepgram key set")
    elif not transcriber or not transcriber.model_loaded:
        raise HTTPException(status_code=503, detail="Whisper model not yet loaded")

    session = RecordingSession(
        id=str(uuid.uuid4()),
        started_at=datetime.now(),
        status="recording",
    )
    active_session = session  # claimed before the first await, so a concurrent start gets 409
    _echo.reset()
    _echo_ids.clear()

    # `is not None`, not `or`: device index 0 is a valid choice.
    mic_idx = body.mic_device_index if body.mic_device_index is not None else prefs.mic_device_index
    lb_idx = (
        body.loopback_device_index
        if body.loopback_device_index is not None
        else prefs.loopback_device_index
    )
    try:
        # Blocking work (PortAudio init, cloud handshakes) must not stall the event loop.
        backend, capture, failures = await asyncio.to_thread(_start_workers, session, mic_idx, lb_idx)
    except Exception as exc:
        active_session = None
        _flush(f"[session] start failed: {exc}")
        raise HTTPException(status_code=500, detail=f"Could not start audio capture: {exc}")
    active_backend, audio_capture = backend, capture

    if prefs.auto_save:
        try:
            allocate_session_folder(session, prefs)
        except Exception as exc:
            _flush(f"[session] could not create session folder: {exc}")

    for failure in failures:  # one source down is survivable, but the user should know
        await _broadcast(_error_event("audio_source", failure))

    # Start audio level broadcast task
    asyncio.ensure_future(_audio_level_task(session.started_at))

    if body.duration_limit_seconds:
        async def _auto_stop():
            await asyncio.sleep(body.duration_limit_seconds)
            if active_session and active_session.id == session.id:
                await _do_stop_session()
        asyncio.ensure_future(_auto_stop())

    await _broadcast({"type": "session_status", "status": "recording", "session_id": session.id})
    _flush(f"[session] started {session.id}")
    return {"session_id": session.id, "started_at": to_utc_iso(session.started_at), "status": "recording"}


async def _audio_level_task(started_at: datetime) -> None:
    """Broadcast AudioLevelFrame at ~10fps while session is active."""
    while active_session and active_session.status == "recording" and audio_capture:
        mic_level = audio_capture.get_mic_rms()
        lb_level = audio_capture.get_loopback_rms()
        elapsed_ms = int((datetime.now() - started_at).total_seconds() * 1000)
        await _broadcast({
            "type": "audio_level",
            "mic_level": mic_level,
            "loopback_level": lb_level,
            "timestamp_ms": elapsed_ms,
        })
        await asyncio.sleep(0.1)


def _stop_workers(capture: AudioCapture | None, backend) -> None:
    """Blocking part of session stop (stream teardown, final decode). Runs in a thread."""
    if capture:
        capture.stop()
    if backend:
        backend.stop()


async def _do_stop_session() -> dict:
    global active_session, audio_capture, active_backend, _pending_model

    if not active_session or active_session.status != "recording":
        raise HTTPException(status_code=404, detail="No active recording session")

    session = active_session
    session.stopped_at = datetime.now()
    session.status = "stopped"

    capture, backend = audio_capture, active_backend
    audio_capture = None
    active_backend = None
    await asyncio.to_thread(_stop_workers, capture, backend)

    save_path_val: str | None = None
    if prefs.auto_save:
        try:
            save_path_val = await asyncio.to_thread(save_session, session, prefs)
            session.save_path = save_path_val
        except Exception as e:
            _flush(f"[session] save failed: {e}")

    if _pending_model and transcriber and event_loop:
        model, _pending_model = _pending_model, None
        event_loop.run_in_executor(None, transcriber.load_model, model)
        _flush(f"[prefs] applying deferred Whisper model: {model}")

    duration = int((session.stopped_at - session.started_at).total_seconds())
    await _broadcast({
        "type": "session_status",
        "status": "stopped",
        "session_id": session.id,
        "save_path": save_path_val,
    })
    _flush(f"[session] stopped {session.id}")
    return {
        "session_id": session.id,
        "stopped_at": to_utc_iso(session.stopped_at),
        "duration_seconds": duration,
        "segment_count": len(session.segments),
        "save_path": save_path_val,
    }


@app.post("/api/session/stop")
async def stop_session():
    return await _do_stop_session()


@app.post("/api/shutdown")
async def shutdown():
    """Graceful exit for the Electron main process: save any live session, then stop."""
    if active_session and active_session.status == "recording":
        try:
            await _do_stop_session()
        except HTTPException:
            pass
    if _server is not None:
        _server.should_exit = True
    return {"ok": True}


# ── Transcript retrieval ──────────────────────────────────────────────────────


@app.get("/api/session/{session_id}/transcript")
def get_transcript(session_id: str):
    if not active_session or active_session.id != session_id:
        raise HTTPException(status_code=404, detail="Session not found")
    return {
        "session_id": session_id,
        "segments": [s.to_ws_dict() for s in active_session.segments],
    }


# ── Claude Q&A ────────────────────────────────────────────────────────────────


class AskBody(BaseModel):
    question: str
    session_id: str
    claude_model: str = "claude-sonnet-4-6"


@app.post("/api/ask")
async def ask_claude(body: AskBody, request: Request):
    api_key = _require_api_key(request)

    if not active_session or active_session.id != body.session_id:
        raise HTTPException(status_code=404, detail="Session not found")

    session = active_session
    segments = list(session.segments)
    history = list(session.chat_messages)

    user_msg = ChatMessage(
        session_id=session.id,
        role="user",
        content=body.question,
        transcript_snapshot_count=len(segments),
    )
    session.chat_messages.append(user_msg)

    async def _stream():
        full_response = ""
        failed = False
        try:
            async for event in _claude_client.ask(
                question=body.question,
                segments=segments,
                history=history,
                api_key=api_key,
                model=body.claude_model,
            ):
                if event["type"] == "content_delta":
                    full_response += event["text"]
                elif event["type"] == "error":
                    failed = True
                yield f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"
        finally:
            # Only a real answer joins the history. An empty assistant turn would be
            # rejected by the API on every later ask, and a dangling question is noise.
            if full_response.strip() and not failed:
                session.chat_messages.append(ChatMessage(
                    session_id=session.id,
                    role="assistant",
                    content=full_response,
                    transcript_snapshot_count=len(segments),
                ))
            elif user_msg in session.chat_messages:
                session.chat_messages.remove(user_msg)

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Transfer-Encoding": "chunked",
        },
    )


# ── WebSocket ─────────────────────────────────────────────────────────────────


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    # Browsers always send Origin and are not bound by CORS for WebSockets, so any web
    # page could otherwise subscribe to the live transcript. The Electron main process
    # (Node `ws`) sends no Origin and presents the launch token.
    if ws.headers.get("origin") is not None or not _token_ok(ws.query_params.get("token")):
        await ws.close(code=1008)
        return
    await ws.accept()
    connected_websockets.add(ws)
    _flush(f"[ws] client connected ({len(connected_websockets)} total)")
    try:
        while True:
            await ws.receive_text()  # keep alive
    except WebSocketDisconnect:
        pass
    finally:
        connected_websockets.discard(ws)
        _flush(f"[ws] client disconnected ({len(connected_websockets)} remaining)")


# ── Entry point ───────────────────────────────────────────────────────────────


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    _flush(f"[sidecar] starting on port {args.port}")
    _server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=args.port, log_level="warning")
    )
    _server.run()
