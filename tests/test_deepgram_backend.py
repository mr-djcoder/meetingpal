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


def test_backend_reports_error_when_no_connection_opens():
    """Both connections failing → a clear, actionable error is surfaced (no fallback)."""
    from datetime import datetime
    from backend.deepgram_backend import DeepgramBackend

    errors = []

    def failing_open(source, on_message, on_error):
        raise RuntimeError("boom")

    b = DeepgramBackend(
        api_key="k", session_id="s", emit=lambda seg: None,
        on_error=errors.append, conn_factory=failing_open,
    )
    b.start("s", datetime.now())
    b.stop()
    assert any("switch to Local" in e for e in errors)


def test_backend_works_with_synchronous_connection():
    """Real deepgram-sdk conn.send/finish are sync; _drain/_close must not await them."""
    import time
    import numpy as np
    from datetime import datetime
    from backend.deepgram_backend import DeepgramBackend

    sent = {"mic": [], "loopback": []}

    class SyncConn:
        def __init__(self, source): self.source = source
        def send(self, data): sent[self.source].append(data)   # synchronous
        def finish(self): pass                                  # synchronous

    b = DeepgramBackend(
        api_key="k", session_id="s", emit=lambda seg: None,
        on_error=lambda e: None, conn_factory=lambda source, on_message, on_error: SyncConn(source),
    )
    b.start("s", datetime.now())
    b.feed("loopback", np.ones(8000, dtype=np.float32) * 0.1, 0.2)
    time.sleep(0.2)  # let the loop thread drain
    b.stop()
    assert len(sent["loopback"]) >= 1
    assert isinstance(sent["loopback"][0], (bytes, bytearray))


def test_is_final_chunks_accumulate_until_speech_final():
    """is_final marks a chunk stable, not the utterance done: no premature final."""
    emitted = []
    m = DeepgramStreamMapper(source="loopback", session_id="s", emit=emitted.append)
    m.handle(_dg("what do you think", is_final=True, speech_final=False))
    m.handle(_dg("about the roadmap", is_final=True, speech_final=True))
    assert [e.is_final for e in emitted] == [False, True]
    assert emitted[1].text == "what do you think about the roadmap"
    assert emitted[0].id == emitted[1].id


def test_interim_text_is_appended_to_committed_chunks():
    emitted = []
    m = DeepgramStreamMapper(source="loopback", session_id="s", emit=emitted.append)
    m.handle(_dg("so the plan", is_final=True, speech_final=False))
    m.handle(_dg("is to", is_final=False))
    assert emitted[-1].text == "so the plan is to"
    assert emitted[-1].is_final is False


def test_utterance_end_finalizes_pending_text():
    emitted = []
    m = DeepgramStreamMapper(source="loopback", session_id="s", emit=emitted.append)
    m.handle(_dg("hello there", is_final=True, speech_final=False))
    m.handle({"type": "UtteranceEnd"})
    assert emitted[-1].is_final is True
    assert emitted[-1].text == "hello there"
    m.handle({"type": "UtteranceEnd"})  # nothing pending: no duplicate final
    assert len(emitted) == 2


def test_flush_finalizes_pending_text():
    emitted = []
    m = DeepgramStreamMapper(source="mic", session_id="s", emit=emitted.append)
    m.handle(_dg("trailing words", is_final=True, speech_final=False))
    m.flush()
    assert emitted[-1].is_final is True


def test_backend_reconnects_after_unexpected_close():
    import time
    import numpy as np
    from datetime import datetime
    from backend.deepgram_backend import DeepgramBackend

    sent = []
    opened = []
    errors = []

    class Conn:
        def __init__(self, n): self.n = n
        def send(self, data): sent.append(self.n)
        def finish(self): pass

    def factory(source, on_message, on_error):
        opened.append(source)
        return Conn(len(opened))

    b = DeepgramBackend(api_key="k", session_id="s", emit=lambda s: None,
                        on_error=errors.append, conn_factory=factory)
    b.RECONNECT_DELAYS_S = (0.0, 0.0)
    b.start("s", datetime.now())
    assert opened.count("mic") == 1
    b._on_closed("mic")
    deadline = time.time() + 3
    while opened.count("mic") < 2 and time.time() < deadline:
        time.sleep(0.02)
    assert opened.count("mic") == 2
    time.sleep(0.1)
    b.feed("mic", np.ones(8000, dtype=np.float32) * 0.1, 0.2)
    time.sleep(0.2)
    b.stop()
    assert sent and sent[-1] == 3  # opened order: mic(1), loopback(2), mic again(3)
    assert any("reconnected" in e for e in errors)


def test_backend_gives_up_after_failed_reconnects():
    import time
    from datetime import datetime
    from backend.deepgram_backend import DeepgramBackend

    errors = []
    calls = {"n": 0}

    class Conn:
        def send(self, data): pass
        def finish(self): pass

    def factory(source, on_message, on_error):
        calls["n"] += 1
        if calls["n"] > 2:  # initial mic + loopback succeed, every reconnect fails
            raise RuntimeError("down")
        return Conn()

    b = DeepgramBackend(api_key="k", session_id="s", emit=lambda s: None,
                        on_error=errors.append, conn_factory=factory)
    b.RECONNECT_DELAYS_S = (0.0, 0.0)
    b.start("s", datetime.now())
    b._on_closed("loopback")
    deadline = time.time() + 3
    while not any("could not" in e for e in errors) and time.time() < deadline:
        time.sleep(0.02)
    b.stop()
    assert any("could not reconnect" in e for e in errors)
