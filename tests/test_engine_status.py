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
