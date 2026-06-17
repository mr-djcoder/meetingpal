# tests/test_deepgram_key_endpoint.py
from fastapi.testclient import TestClient
from backend import main


def test_store_deepgram_key():
    with TestClient(main.app) as client:
        r = client.post("/api/key/deepgram", json={"api_key": "dg-123"})
        assert r.status_code == 200
        assert r.json() == {"stored": True}
        assert main._deepgram_key_memory == "dg-123"
