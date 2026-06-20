# tests/test_transcription_backend.py
import numpy as np
from datetime import datetime
from backend.transcription_backend import LocalBackend, TranscriptionBackend


class FakeTranscriber:
    def __init__(self):
        self.started = False
        self.fed = []
        self.stopped = False
        self.model_loaded = True
        self.device = "cpu"
    def start(self, sid, started): self.started = (sid, started)
    def enqueue(self, source, frame, rms): self.fed.append((source, rms))
    def stop(self): self.stopped = True


def test_localbackend_delegates_to_transcriber():
    t = FakeTranscriber()
    b: TranscriptionBackend = LocalBackend(t)
    now = datetime.now()
    b.start("sess", now)
    b.feed("mic", np.zeros(8000, dtype=np.float32), 0.2)
    b.stop()
    assert t.started == ("sess", now)
    assert t.fed == [("mic", 0.2)]
    assert t.stopped is True


def test_localbackend_reports_status():
    t = FakeTranscriber()
    b = LocalBackend(t)
    assert b.ready() is True
    assert b.device == "cpu"
