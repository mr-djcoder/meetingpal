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
