"""FastAPI sidecar entrypoint — registers all routes and manages app lifespan."""
from __future__ import annotations

import os
# Fix PyTorch + Intel MKL duplicate OpenMP runtime on Windows
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import argparse
import asyncio
import json
import sys
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.audio_capture import AudioCapture, enumerate_devices
from backend.auto_answer import AutoAnswerOrchestrator
from backend.claude_client import ClaudeClient
from backend.gemini_client import GeminiClient, list_gemini_models
from backend.models import ChatMessage, RecordingSession, TranscriptSegment
from backend.storage import UserPreferences, load_preferences, save_preferences, save_session
from backend.transcriber import WhisperTranscriber

# ── App-wide state ────────────────────────────────────────────────────────────

transcriber: WhisperTranscriber | None = None
audio_capture: AudioCapture | None = None
active_session: RecordingSession | None = None
connected_websockets: set[WebSocket] = set()
prefs: UserPreferences = UserPreferences()
_api_key_memory: str | None = None  # Claude key, held in-process only, never on disk
_gemini_key_memory: str | None = None  # Gemini key, in-process only
event_loop: asyncio.AbstractEventLoop | None = None  # captured at startup for cross-thread scheduling

_claude_client = ClaudeClient()
_gemini_client = GeminiClient()
auto_answer: AutoAnswerOrchestrator | None = None  # created at startup

SIDECAR_VERSION = "1.0.0"


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
    )
    # Load model in background so health returns model_loaded=false while loading
    event_loop.run_in_executor(None, transcriber.load_model, None)
    yield
    if audio_capture:
        audio_capture.stop()
    if transcriber:
        transcriber.stop()


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(title="MeetingPal Sidecar", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Helper ────────────────────────────────────────────────────────────────────


def _flush(msg: str) -> None:
    print(msg, flush=True)


async def _broadcast(data: dict) -> None:
    dead: list[WebSocket] = []
    for ws in list(connected_websockets):
        try:
            await ws.send_json(data)
        except Exception:
            dead.append(ws)
    for ws in dead:
        connected_websockets.discard(ws)


def _on_transcript_segment(seg: TranscriptSegment) -> None:
    """Called from transcriber worker thread — schedule broadcast on event loop."""
    if active_session:
        # Partials and the final of one utterance share an id; upsert so the persisted
        # transcript (and the Claude context) holds one clean entry per utterance, not
        # every interim partial. The latest write (the final) wins.
        for i, existing in enumerate(active_session.segments):
            if existing.id == seg.id:
                active_session.segments[i] = seg
                break
        else:
            active_session.segments.append(seg)
    if event_loop is None:
        return
    # Worker runs off-loop; hand the coroutine to the captured loop thread-safely.
    event_loop.call_soon_threadsafe(
        lambda: asyncio.ensure_future(_broadcast(seg.to_ws_dict()))
    )
    # Auto-answer: on a finalized question from the other party, the orchestrator
    # decides whether to fire (enabled / Them / is-question / min-interval).
    if auto_answer is not None and prefs.auto_answer_enabled and active_session is not None:
        segments_snapshot = list(active_session.segments)
        history_snapshot = list(active_session.chat_messages)
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


def _require_api_key(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing API key")
    key = auth[len("Bearer "):]
    if not key:
        raise HTTPException(status_code=401, detail="Empty API key")
    return key


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


class PrefsUpdate(BaseModel):
    whisper_model: str | None = None
    claude_model: str | None = None
    mic_device_index: int | None = None
    loopback_device_index: int | None = None
    auto_save: bool | None = None
    save_path: str | None = None
    font_size: int | None = None
    theme: str | None = None
    onboarding_completed: bool | None = None
    auto_answer_enabled: bool | None = None
    auto_answer_prompt: str | None = None
    auto_answer_provider: str | None = None
    auto_answer_model: str | None = None
    chat_panel_visible: bool | None = None
    custom_titlebar: bool | None = None
    window_opacity: float | None = None
    transcript_split: float | None = None


@app.put("/api/preferences")
def update_preferences(body: PrefsUpdate):
    global prefs
    data = body.model_dump(exclude_none=True)
    old_model = prefs.whisper_model
    for k, v in data.items():
        if hasattr(prefs, k):
            setattr(prefs, k, v)
    save_preferences(prefs)
    # Hot-reload Whisper model if it changed
    if "whisper_model" in data and data["whisper_model"] != old_model and transcriber and event_loop:
        event_loop.run_in_executor(None, transcriber.load_model, prefs.whisper_model)
        _flush(f"[prefs] reloading Whisper model: {prefs.whisper_model}")
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
    whisper_model: str = "base.en"
    duration_limit_seconds: int | None = None


@app.post("/api/session/start")
async def start_session(body: StartSessionBody, request: Request):
    global active_session, audio_capture

    if active_session and active_session.status == "recording":
        raise HTTPException(
            status_code=409,
            detail={"error": "A recording session is already active", "session_id": active_session.id},
        )

    if not transcriber or not transcriber.model_loaded:
        raise HTTPException(status_code=503, detail="Whisper model not yet loaded")

    session = RecordingSession(
        id=str(uuid.uuid4()),
        started_at=datetime.now(),
        status="recording",
    )
    active_session = session

    def _chunk_cb(source, frame, rms):
        transcriber.enqueue(source, frame, rms)

    audio_capture = AudioCapture(
        chunk_callback=_chunk_cb,
        mic_device_index=body.mic_device_index or prefs.mic_device_index,
        loopback_device_index=body.loopback_device_index or prefs.loopback_device_index,
    )
    transcriber.start(session.id, session.started_at)
    audio_capture.start()

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
    return {"session_id": session.id, "started_at": session.started_at.isoformat() + "Z", "status": "recording"}


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


async def _do_stop_session() -> dict:
    global active_session, audio_capture

    if not active_session or active_session.status != "recording":
        raise HTTPException(status_code=404, detail="No active recording session")

    session = active_session
    session.stopped_at = datetime.now()
    session.status = "stopped"

    if audio_capture:
        audio_capture.stop()
        audio_capture = None
    if transcriber:
        transcriber.stop()

    save_path_val: str | None = None
    if prefs.auto_save:
        try:
            save_path_val = save_session(session, prefs)
            session.save_path = save_path_val
        except Exception as e:
            _flush(f"[session] save failed: {e}")

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
        "stopped_at": session.stopped_at.isoformat() + "Z",
        "duration_seconds": duration,
        "segment_count": len(session.segments),
        "save_path": save_path_val,
    }


@app.post("/api/session/stop")
async def stop_session():
    return await _do_stop_session()


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

    # Add user message to history
    user_msg = ChatMessage(
        session_id=session.id,
        role="user",
        content=body.question,
        transcript_snapshot_count=len(segments),
    )
    session.chat_messages.append(user_msg)

    claude = ClaudeClient()

    async def _stream():
        full_response = ""
        async for event in claude.ask(
            question=body.question,
            segments=segments,
            history=history,
            api_key=api_key,
            model=body.claude_model,
        ):
            if event["type"] == "content_delta":
                full_response += event["text"]
            yield f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"

        # Append assistant message
        asst_msg = ChatMessage(
            session_id=session.id,
            role="assistant",
            content=full_response,
            transcript_snapshot_count=len(segments),
        )
        session.chat_messages.append(asst_msg)

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
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
