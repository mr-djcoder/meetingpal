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
