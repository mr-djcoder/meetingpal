"""API-level tests: auth, preference validation, session start/stop, ask history."""
import json

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import backend.storage as storage
from backend import main


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Client with preferences redirected to a temp dir so tests never touch real prefs."""
    monkeypatch.setattr(storage, "PREFS_DIR", tmp_path)
    monkeypatch.setattr(storage, "PREFS_FILE", tmp_path / "preferences.json")
    monkeypatch.setattr(main, "API_TOKEN", "")
    with TestClient(main.app) as c:
        main.prefs.auto_save = False
        yield c
    main.active_session = None


# ── auth ──────────────────────────────────────────────────────────────────────


def test_http_requires_token_when_configured(client, monkeypatch):
    monkeypatch.setattr(main, "API_TOKEN", "secret")
    assert client.get("/health").status_code == 401
    assert client.get("/health", headers={"x-meetingpal-token": "wrong"}).status_code == 401
    assert client.get("/health", headers={"x-meetingpal-token": "secret"}).status_code == 200


def test_no_cors_headers_are_sent(client):
    r = client.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers


def test_websocket_rejects_browser_origin_and_bad_token(client, monkeypatch):
    monkeypatch.setattr(main, "API_TOKEN", "secret")
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws?token=secret", headers={"origin": "https://evil.example"}):
            pass
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws?token=nope"):
            pass
    with client.websocket_connect("/ws?token=secret"):
        pass  # Electron main: no Origin, right token


# ── preferences ───────────────────────────────────────────────────────────────


def test_prefs_reject_invalid_values(client):
    assert client.put("/api/preferences", json={"theme": "neon"}).status_code == 422
    assert client.put("/api/preferences", json={"whisper_model": "../../evil"}).status_code == 422
    assert client.put("/api/preferences", json={"save_path": "relative/dir"}).status_code == 422
    assert client.put("/api/preferences", json={"window_opacity": 5}).status_code == 422
    assert client.put("/api/preferences", json={"transcription_engine": "x"}).status_code == 422


def test_prefs_accept_valid_values(client, tmp_path):
    r = client.put("/api/preferences", json={"theme": "light", "save_path": str(tmp_path)})
    assert r.status_code == 200
    assert r.json()["theme"] == "light"


def test_device_index_can_be_reset_to_default(client):
    client.put("/api/preferences", json={"mic_device_index": 3})
    assert client.get("/api/preferences").json()["mic_device_index"] == 3
    client.put("/api/preferences", json={"mic_device_index": None})
    assert client.get("/api/preferences").json()["mic_device_index"] is None


# ── session ───────────────────────────────────────────────────────────────────


class _FakeCapture:
    def __init__(self):
        self.stopped = False

    def get_mic_rms(self):
        return 0.0

    get_loopback_rms = get_mic_rms

    def stop(self):
        self.stopped = True


class _FakeBackend:
    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True


@pytest.fixture
def fake_workers(monkeypatch):
    seen = {}

    def fake_start(session, mic_idx, lb_idx):
        seen["mic"], seen["lb"] = mic_idx, lb_idx
        return _FakeBackend(), _FakeCapture(), []

    monkeypatch.setattr(main, "_start_workers", fake_start)
    monkeypatch.setattr(main, "_deepgram_key_memory", "k")
    main.prefs.transcription_engine = "cloud"
    return seen


def test_device_index_zero_is_respected(client, fake_workers):
    main.prefs.mic_device_index = 7
    r = client.post("/api/session/start", json={"mic_device_index": 0})
    assert r.status_code == 200
    assert fake_workers["mic"] == 0  # not replaced by the saved preference
    client.post("/api/session/stop")


def test_start_stop_roundtrip_and_utc_timestamps(client, fake_workers):
    r = client.post("/api/session/start", json={})
    assert r.status_code == 200
    assert r.json()["started_at"].endswith("+00:00")  # real UTC, not local labelled "Z"
    assert client.post("/api/session/start", json={}).status_code == 409
    stop = client.post("/api/session/stop")
    assert stop.status_code == 200
    assert client.post("/api/session/stop").status_code == 404


def test_start_failure_clears_the_session(client, monkeypatch):
    def boom(*a):
        raise RuntimeError("no audio device")

    monkeypatch.setattr(main, "_start_workers", boom)
    monkeypatch.setattr(main, "_deepgram_key_memory", "k")
    main.prefs.transcription_engine = "cloud"
    r = client.post("/api/session/start", json={})
    assert r.status_code == 500
    assert main.active_session is None  # a retry is not blocked by a 409


# ── ask ───────────────────────────────────────────────────────────────────────


def _ask(client, session_id):
    return client.post(
        "/api/ask",
        json={"question": "what now?", "session_id": session_id},
        headers={"Authorization": "Bearer sk-test"},
    )


def test_ask_success_records_both_turns(client, fake_workers, monkeypatch):
    async def fake_ask(**kwargs):
        yield {"type": "content_delta", "text": "Do "}
        yield {"type": "content_delta", "text": "this."}
        yield {"type": "message_stop"}

    monkeypatch.setattr(main._claude_client, "ask", fake_ask)
    sid = client.post("/api/session/start", json={}).json()["session_id"]
    r = _ask(client, sid)
    assert r.status_code == 200
    roles = [(m.role, m.content) for m in main.active_session.chat_messages]
    assert roles == [("user", "what now?"), ("assistant", "Do this.")]
    client.post("/api/session/stop")


def test_ask_error_does_not_poison_history(client, fake_workers, monkeypatch):
    async def failing_ask(**kwargs):
        yield {"type": "error", "message": "boom"}

    monkeypatch.setattr(main._claude_client, "ask", failing_ask)
    sid = client.post("/api/session/start", json={}).json()["session_id"]
    r = _ask(client, sid)
    assert "boom" in r.text
    assert main.active_session.chat_messages == []  # no empty assistant turn left behind
    client.post("/api/session/stop")


def test_ask_requires_known_session(client, fake_workers):
    assert _ask(client, "nope").status_code == 404


def test_ask_uses_gemini_when_selected(client, fake_workers, monkeypatch):
    seen = {}

    async def fake_gemini(**kwargs):
        seen.update(kwargs)
        yield {"type": "content_delta", "text": "From Gemini."}
        yield {"type": "message_stop"}

    monkeypatch.setattr(main._gemini_client, "ask", fake_gemini)
    monkeypatch.setattr(main, "_gemini_key_memory", "g-key")
    monkeypatch.setattr(main.prefs, "chat_provider", "gemini")
    monkeypatch.setattr(main.prefs, "chat_gemini_model", "gemini-test")
    sid = client.post("/api/session/start", json={}).json()["session_id"]
    r = client.post("/api/ask", json={"question": "hi", "session_id": sid})  # no Claude key sent
    assert r.status_code == 200
    assert seen["api_key"] == "g-key" and seen["model"] == "gemini-test"
    assert main.active_session.chat_messages[-1].content == "From Gemini."
    client.post("/api/session/stop")


def test_ask_gemini_without_key_is_401(client, fake_workers, monkeypatch):
    monkeypatch.setattr(main, "_gemini_key_memory", None)
    monkeypatch.setattr(main.prefs, "chat_provider", "gemini")
    sid = client.post("/api/session/start", json={}).json()["session_id"]
    assert client.post("/api/ask", json={"question": "hi", "session_id": sid}).status_code == 401
    client.post("/api/session/stop")


def test_ask_uses_ollama_without_any_key(client, fake_workers, monkeypatch):
    seen = {}

    async def fake_ollama(**kwargs):
        seen.update(kwargs)
        yield {"type": "content_delta", "text": "Local answer."}
        yield {"type": "message_stop"}

    monkeypatch.setattr(main._ollama_client, "ask", fake_ollama)
    monkeypatch.setattr(main, "_gemini_key_memory", None)
    monkeypatch.setattr(main, "_api_key_memory", None)
    monkeypatch.setattr(main.prefs, "chat_provider", "ollama")
    monkeypatch.setattr(main.prefs, "chat_ollama_model", "qwen-test")
    sid = client.post("/api/session/start", json={}).json()["session_id"]
    r = client.post("/api/ask", json={"question": "hi", "session_id": sid})
    assert r.status_code == 200
    assert seen["model"] == "qwen-test"
    assert main.active_session.chat_messages[-1].content == "Local answer."
    client.post("/api/session/stop")


def test_ollama_models_endpoint(client, monkeypatch):
    async def fake_list():
        return ["qwen3.5:27b"]

    monkeypatch.setattr(main, "list_ollama_models", fake_list)
    assert client.get("/api/ollama/models").json() == {"models": ["qwen3.5:27b"]}


def test_clear_chat_forgets_history_and_checks_session(client, fake_workers, monkeypatch):
    async def fake_ask(**kwargs):
        yield {"type": "content_delta", "text": "ok"}
        yield {"type": "message_stop"}

    monkeypatch.setattr(main._claude_client, "ask", fake_ask)
    sid = client.post("/api/session/start", json={}).json()["session_id"]
    _ask(client, sid)
    assert main.active_session.chat_messages
    assert client.post("/api/chat/clear", json={"session_id": "nope"}).status_code == 404
    assert client.post("/api/chat/clear", json={"session_id": sid}).status_code == 200
    assert main.active_session.chat_messages == []
    client.post("/api/session/stop")
