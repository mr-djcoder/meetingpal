# tests/test_deepgram_backend.py
from backend.deepgram_backend import DeepgramStreamMapper


def _dg(transcript, is_final, speech_final=False):
    return {
        "channel": {"alternatives": [{"transcript": transcript}]},
        "is_final": is_final,
        "speech_final": speech_final,
    }


def test_interim_then_final_share_one_id():
    emitted = []
    m = DeepgramStreamMapper(source="loopback", session_id="s", emit=emitted.append)
    m.handle(_dg("how are", is_final=False))
    m.handle(_dg("how are you", is_final=True, speech_final=True))
    assert emitted[0].speaker == "Them"
    assert emitted[0].is_final is False
    assert emitted[1].is_final is True
    assert emitted[0].id == emitted[1].id            # one utterance
    assert emitted[1].text == "how are you"


def test_new_utterance_gets_new_id():
    emitted = []
    m = DeepgramStreamMapper(source="mic", session_id="s", emit=emitted.append)
    m.handle(_dg("hello", is_final=True, speech_final=True))
    m.handle(_dg("again", is_final=True, speech_final=True))
    assert emitted[0].speaker == "You"
    assert emitted[0].id != emitted[1].id


def test_empty_transcript_skipped():
    emitted = []
    m = DeepgramStreamMapper(source="mic", session_id="s", emit=emitted.append)
    m.handle(_dg("", is_final=False))
    assert emitted == []


def test_backend_feeds_pcm_and_reports_error(monkeypatch):
    import numpy as np
    from datetime import datetime
    from backend.deepgram_backend import DeepgramBackend

    sent = {"mic": [], "loopback": []}
    errors = []

    class FakeConn:
        def __init__(self, source): self.source = source
        async def send(self, data): sent[self.source].append(data)
        async def finish(self): pass

    def fake_open(source, on_message, on_error):
        return FakeConn(source)

    b = DeepgramBackend(
        api_key="k", session_id="s", emit=lambda seg: None,
        on_error=errors.append, conn_factory=fake_open,
    )
    b.start("s", datetime.now())
    b.feed("mic", np.ones(8000, dtype=np.float32) * 0.1, 0.2)
    b.stop()
    assert len(sent["mic"]) >= 1
    assert isinstance(sent["mic"][0], (bytes, bytearray))
