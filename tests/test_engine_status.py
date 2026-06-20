# tests/test_engine_status.py
from fastapi.testclient import TestClient
from backend import main


def test_engine_status_shape():
    with TestClient(main.app) as client:
        r = client.get("/api/engine/status")
        assert r.status_code == 200
        body = r.json()
        assert body["engine"] in ("local", "cloud")
        assert "device" in body and "model" in body and "mode" in body
        assert "ready" in body and isinstance(body["ready"], bool)


def test_engine_status_cloud_is_ready_without_model():
    """Cloud engine reports ready even when the local Whisper model is not loaded."""
    with TestClient(main.app) as client:
        # set AFTER lifespan startup (which reloads prefs from disk)
        prev = main.prefs.transcription_engine
        main.prefs.transcription_engine = "cloud"
        try:
            body = client.get("/api/engine/status").json()
            assert body["engine"] == "cloud"
            assert body["ready"] is True
        finally:
            main.prefs.transcription_engine = prev
