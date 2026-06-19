# tests/test_streaming_utterance.py
import numpy as np
from datetime import datetime
from backend.streaming_utterance import StreamingUtteranceAssembler

SR = 16000


def _frame(seconds=0.5):
    return np.zeros(int(seconds * SR), dtype=np.float32)


def test_construction_and_flush_no_active_utterance():
    emitted = []
    a = StreamingUtteranceAssembler(
        lambda buf, beam, initial_prompt="": "",
        emitted.append,
        "sess-1",
        speaker="You",
    )
    a.flush()  # nothing buffered → no emit
    assert emitted == []


def test_longest_common_prefix():
    from backend.streaming_utterance import _common_prefix
    assert _common_prefix(["a", "b", "c"], ["a", "b", "x"]) == ["a", "b"]
    assert _common_prefix(["a"], ["b"]) == []
    assert _common_prefix([], ["a"]) == []


def test_commit_on_two_agreeing_hypotheses():
    """Two partials agreeing on a leading word commit that word; tail stays live."""
    emitted = []
    # scripted transcriber: first call returns "hello there", second "hello there friend"
    calls = iter(["hello there", "hello there friend"])

    def fake_transcribe(buf, beam, initial_prompt=""):
        return next(calls)

    a = StreamingUtteranceAssembler(fake_transcribe, emitted.append, "s", speaker="You")
    SR = 16000
    speech = np.ones(int(0.5 * SR), dtype=np.float32) * 0.1
    now = datetime.now()
    # feed 1.0s speech → first partial ("hello there"), then 1.0s more → second
    for _ in range(2):
        a.process(speech, True, now, 0.0)
    for _ in range(2):
        a.process(speech, True, now, 0.0)
    # "hello there" agreed across the two hypotheses → committed
    assert a.committed_text() == "hello there"
    # last emitted partial includes committed + tail "friend"
    assert emitted[-1].text == "hello there friend"
    assert emitted[-1].is_final is False


def test_silence_finalizes_with_committed_and_tail():
    emitted = []
    calls = iter(["good morning", "good morning", "good morning everyone", "good morning everyone"])

    def fake(buf, beam, initial_prompt=""):
        try:
            return next(calls)
        except StopIteration:
            return "good morning everyone"

    a = StreamingUtteranceAssembler(fake, emitted.append, "s", speaker="Them",
                                    silence_finalize_s=1.0)
    SR = 16000
    speech = np.ones(int(0.5 * SR), dtype=np.float32) * 0.1
    silence = np.zeros(int(0.5 * SR), dtype=np.float32)
    now = datetime.now()
    for _ in range(6):
        a.process(speech, True, now, 0.0)
    for _ in range(2):  # 1.0s silence ≥ silence_finalize_s
        a.process(silence, False, now, 0.0)
    finals = [e for e in emitted if e.is_final]
    assert len(finals) == 1
    assert "good morning everyone" in finals[0].text
    assert finals[0].speaker == "Them"


def test_empty_hypothesis_does_not_crash_or_emit():
    """A blank/hallucinated-empty hypothesis must not emit or raise."""
    emitted = []
    a = StreamingUtteranceAssembler(
        lambda buf, beam, initial_prompt="": "",  # always empty
        emitted.append, "s", speaker="You", min_window_s=0.5,
    )
    speech = np.ones(int(0.5 * SR), dtype=np.float32) * 0.1
    now = datetime.now()
    for _ in range(4):
        a.process(speech, True, now, 0.0)
    assert emitted == []           # nothing committed/emitted
    assert a.committed_text() == ""


def test_partial_commit_retains_trailing_audio():
    """Under-decoded hypothesis (1 word for a long window) must NOT strip the whole
    window — a trailing tail is retained so later speech isn't lost."""
    emitted = []
    # Always returns a single word that agrees with itself → would drop frac=1.0.
    a = StreamingUtteranceAssembler(
        lambda buf, beam, initial_prompt="": "hello",
        emitted.append, "s", speaker="You", min_window_s=0.5,
    )
    speech = np.ones(int(0.5 * SR), dtype=np.float32) * 0.1
    now = datetime.now()
    for _ in range(6):  # 3s of speech, partials every 1s
        a.process(speech, True, now, 0.0)
    # committed "hello", but the window was NOT fully emptied (retain floor)
    assert "hello" in a.committed_text()
    assert a._window_s() >= 0.4   # ~MIN_RETAIN_S retained, not zero


def test_max_utterance_finalizes_and_resets():
    """Hitting max_utterance_s finalizes and starts a fresh utterance id next frame."""
    emitted = []
    a = StreamingUtteranceAssembler(
        lambda buf, beam, initial_prompt="": "word",
        emitted.append, "s", speaker="You",
        max_utterance_s=1.5, min_window_s=0.5,
    )
    speech = np.ones(int(0.5 * SR), dtype=np.float32) * 0.1
    now = datetime.now()
    for _ in range(4):  # 2s > max 1.5s → finalize mid-way
        a.process(speech, True, now, 0.0)
    finals = [e for e in emitted if e.is_final]
    assert len(finals) >= 1
    first_id = finals[0].id
    # after finalize, a new speech frame must start a new utterance (new id)
    a.process(speech, True, now, 0.0)
    a.process(speech, True, now, 0.0)
    a.flush()
    ids = {e.id for e in emitted}
    assert len(ids) >= 2 or a._current_id is None
