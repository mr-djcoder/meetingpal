from datetime import datetime

import numpy as np

from backend.models import TranscriptSegment
from backend.utterance import UtteranceAssembler

WALL = datetime(2026, 6, 13, 12, 0, 0)


def make_frame(seconds=0.5):
    return np.ones(int(seconds * 16000), dtype=np.float32)


class Recorder:
    def __init__(self):
        self.segments: list[TranscriptSegment] = []

    def __call__(self, seg: TranscriptSegment):
        self.segments.append(seg)


def build(transcribe_text="hello world", **kw):
    rec = Recorder()
    asm = UtteranceAssembler(
        transcribe_fn=lambda buf, beam: transcribe_text,
        emit_fn=rec,
        session_id="s1",
        **kw,
    )
    return asm, rec


def feed(asm, *, speech: bool, n: int, mic=0.9, lb=0.1):
    for _ in range(n):
        asm.process(make_frame(), speech, mic, lb, WALL, 0.0)


def test_silence_gap_finalizes_one_segment():
    asm, rec = build(transcribe_text="hello world.", partial_interval_s=999)
    feed(asm, speech=True, n=4)      # 2.0s speech, no partial
    feed(asm, speech=False, n=2)     # 1.0s silence >= 0.7s -> finalize
    assert len(rec.segments) == 1
    seg = rec.segments[0]
    assert seg.is_final is True
    assert seg.text == "hello world."


def test_silence_below_threshold_does_not_finalize():
    asm, rec = build(partial_interval_s=999)
    feed(asm, speech=True, n=2)
    feed(asm, speech=False, n=1)     # 0.5s silence < 0.7s
    assert rec.segments == []
