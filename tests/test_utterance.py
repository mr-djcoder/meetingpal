from datetime import datetime

import numpy as np

from backend.models import TranscriptSegment
from backend.utterance import UtteranceAssembler, clean_text

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
    assert seg.speaker == "You"          # mic_rms (0.9) >= lb_rms (0.1) at onset
    assert seg.session_id == "s1"


def test_silence_below_threshold_does_not_finalize():
    asm, rec = build(partial_interval_s=999)
    feed(asm, speech=True, n=2)
    feed(asm, speech=False, n=1)     # 0.5s silence < 0.7s
    assert rec.segments == []


def test_partial_emitted_after_interval():
    asm, rec = build(transcribe_text="hello", partial_interval_s=1.5)
    feed(asm, speech=True, n=3)      # 1.5s -> one partial
    assert len(rec.segments) == 1
    assert rec.segments[0].is_final is False
    assert rec.segments[0].text == "hello"


def test_partials_share_one_id_then_final_reuses_it():
    asm, rec = build(transcribe_text="hello", partial_interval_s=1.5)
    feed(asm, speech=True, n=3)      # partial #1
    feed(asm, speech=True, n=3)      # partial #2
    feed(asm, speech=False, n=2)     # finalize
    ids = {s.id for s in rec.segments}
    assert len(ids) == 1             # all share the utterance id
    assert rec.segments[-1].is_final is True
    assert [s.is_final for s in rec.segments] == [False, False, True]


def test_punctuation_promotes_partial_to_final():
    asm, rec = build(transcribe_text="All done.", partial_interval_s=1.5)
    feed(asm, speech=True, n=3)      # 1.5s -> transcribe -> ends with '.' -> finalize
    assert len(rec.segments) == 1
    assert rec.segments[0].is_final is True
    assert rec.segments[0].text == "All done."


def test_next_utterance_gets_new_id_after_punctuation_final():
    asm, rec = build(transcribe_text="Done.", partial_interval_s=1.5)
    feed(asm, speech=True, n=3)      # finalize utterance 1
    feed(asm, speech=True, n=3)      # finalize utterance 2
    assert len(rec.segments) == 2
    assert rec.segments[0].id != rec.segments[1].id


def test_max_length_forces_final_without_silence():
    asm, rec = build(transcribe_text="long talk", partial_interval_s=999, max_utterance_s=2.0)
    feed(asm, speech=True, n=4)      # 2.0s -> forced finalize
    assert len(rec.segments) == 1
    assert rec.segments[0].is_final is True


def test_speech_continues_with_new_id_after_forced_final():
    asm, rec = build(transcribe_text="long talk", partial_interval_s=999, max_utterance_s=2.0)
    feed(asm, speech=True, n=4)      # forced final (utterance 1)
    feed(asm, speech=True, n=4)      # forced final (utterance 2)
    assert len(rec.segments) == 2
    assert rec.segments[0].id != rec.segments[1].id


def test_speaker_from_onset_rms_and_held_for_utterance():
    asm, rec = build(transcribe_text="hi", partial_interval_s=1.5)
    # Onset frame: mic louder -> "You". Later frames flip rms; speaker must NOT change.
    asm.process(make_frame(), True, 0.9, 0.1, WALL, 0.0)   # onset -> You
    asm.process(make_frame(), True, 0.0, 0.9, WALL, 0.0)
    asm.process(make_frame(), True, 0.0, 0.9, WALL, 0.0)   # triggers partial
    asm.process(make_frame(), False, 0.0, 0.0, WALL, 0.0)
    asm.process(make_frame(), False, 0.0, 0.0, WALL, 0.0)  # finalize
    assert all(s.speaker == "You" for s in rec.segments)


def test_speaker_them_when_loopback_louder_at_onset():
    asm, rec = build(transcribe_text="hi.", partial_interval_s=1.5)
    asm.process(make_frame(), True, 0.1, 0.9, WALL, 0.0)   # onset -> Them
    asm.process(make_frame(), True, 0.1, 0.9, WALL, 0.0)
    asm.process(make_frame(), True, 0.1, 0.9, WALL, 0.0)   # partial -> '.' -> final
    assert rec.segments and all(s.speaker == "Them" for s in rec.segments)


def test_flush_finalizes_active_utterance():
    asm, rec = build(transcribe_text="mid sentence", partial_interval_s=999)
    feed(asm, speech=True, n=2)      # active, no partial, no silence
    asm.flush()
    assert len(rec.segments) == 1
    assert rec.segments[0].is_final is True


def test_flush_noop_when_idle():
    asm, rec = build()
    asm.flush()
    assert rec.segments == []


def test_empty_transcription_is_dropped():
    asm, rec = build(transcribe_text="   ", partial_interval_s=999)
    feed(asm, speech=True, n=2)
    feed(asm, speech=False, n=2)     # finalize, but text is blank
    assert rec.segments == []


def test_clean_text_drops_hallucination_tail():
    assert clean_text("// // //") == ""
    assert clean_text("...") == ""
    assert clean_text("  hello  ") == "hello"
    assert clean_text("Real text.") == "Real text."
