# Utterance Assembler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace per-3s-chunk transcript fragments with caption-style utterance assembly — live grey partials that settle into one clean final statement on a speech pause.

**Architecture:** A new pure `UtteranceAssembler` (backend/utterance.py) accumulates speech frames into a growing buffer and decides when to emit partial (`is_final=False`) vs final (`is_final=True`) segments, all in *audio-time* (sum of frame durations) so it is fully deterministic and unit-testable. The Whisper worker decides speech/silence per frame via Silero VAD and feeds the assembler; audio capture is changed to emit contiguous, non-overlapping 0.5s mixed frames instead of overlapping 3s windows. The renderer store upserts segments by id so a partial is replaced in place by its final.

**Tech Stack:** Python 3.11+/3.13, numpy, faster-whisper, silero-vad, pytest (new); TypeScript/React/Zustand renderer.

**Spec:** `docs/superpowers/specs/2026-06-13-utterance-assembler-design.md`

**Design note vs spec:** the spec's ~0.2s pre-roll ring is dropped as unnecessary — frames are 0.5s and VAD fires on the frame containing the speech onset, so that frame (with its onset) is already the first appended. `main.py` is unchanged: `transcriber.enqueue(frame, mic_rms, lb_rms)` and the capture `chunk_callback` keep their signatures; only frame size and the transcriber's internals change.

---

## File Structure

| File | Responsibility | Action |
|------|----------------|--------|
| `backend/utterance.py` | Pure utterance state machine (accumulate, partial/final decisions). Injected `transcribe_fn`/`emit_fn`. | **Create** |
| `backend/vad.py` | Silero VAD; add `is_speech_frame` for 0.5s frames. | Modify |
| `backend/audio_capture.py` | Emit contiguous non-overlapping 0.5s mixed frames; pure `mix_frame` helper. | Modify |
| `backend/transcriber.py` | Own model + worker; create assembler in `start()`, run VAD per frame, feed assembler, `transcribe(buffer, beam)`. | Modify |
| `src/store/transcriptStore.ts` | `addSegment` upserts by id. | Modify |
| `src/components/TranscriptPanel.tsx` | Render `is_final===false` grey/italic. | Modify |
| `tests/test_utterance.py` | Unit tests for the assembler (fake transcribe/emit). | **Create** |
| `tests/test_audio_capture.py` | Unit test for `mix_frame`. | **Create** |
| `tests/test_vad.py` | Smoke test: silence → not speech. | **Create** |
| `requirements.txt` | Add `pytest`. | Modify |

**Reference — final shape of `backend/utterance.py`** (tasks build this incrementally; this is the end state for cross-checking):

```python
"""Caption-style utterance assembler — pure state machine, audio-time driven."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Callable, Literal

import numpy as np

from backend.models import TranscriptSegment

SAMPLE_RATE = 16000
SENTENCE_END = (".", "?", "!")

TranscribeFn = Callable[[np.ndarray, int], str]
EmitFn = Callable[[TranscriptSegment], None]


def clean_text(text: str) -> str:
    """Strip and drop empty / pure-punctuation hallucination tails (e.g. '// // //')."""
    t = text.strip()
    if not t:
        return ""
    if not t.replace("/", "").replace(".", "").replace(" ", "").strip():
        return ""
    return t


class UtteranceAssembler:
    def __init__(
        self,
        transcribe_fn: TranscribeFn,
        emit_fn: EmitFn,
        session_id: str,
        *,
        partial_interval_s: float = 1.5,
        silence_finalize_s: float = 0.7,
        max_utterance_s: float = 15.0,
        partial_beam: int = 1,
        final_beam: int = 5,
    ) -> None:
        self._transcribe_fn = transcribe_fn
        self._emit_fn = emit_fn
        self._session_id = session_id
        self._partial_interval_s = partial_interval_s
        self._silence_finalize_s = silence_finalize_s
        self._max_utterance_s = max_utterance_s
        self._partial_beam = partial_beam
        self._final_beam = final_beam

        self._buffer = np.empty(0, dtype=np.float32)
        self._current_id: str | None = None
        self._speaker: Literal["You", "Them"] = "You"
        self._silence_run_s = 0.0
        self._audio_since_partial_s = 0.0
        self._last_wall_clock: datetime | None = None
        self._last_offset = 0.0

    def process(
        self,
        frame: np.ndarray,
        is_speech: bool,
        mic_rms: float,
        lb_rms: float,
        wall_clock: datetime,
        offset: float,
    ) -> None:
        self._last_wall_clock = wall_clock
        self._last_offset = offset
        frame_s = len(frame) / SAMPLE_RATE

        if is_speech:
            if self._current_id is None:
                self._start_utterance(mic_rms, lb_rms)
            self._buffer = np.concatenate([self._buffer, frame])
            self._silence_run_s = 0.0
            self._audio_since_partial_s += frame_s

            if len(self._buffer) / SAMPLE_RATE >= self._max_utterance_s:
                self._finalize()
                return

            if self._audio_since_partial_s >= self._partial_interval_s:
                text = self._transcribe(self._partial_beam)
                self._audio_since_partial_s = 0.0
                if text and text[-1] in SENTENCE_END:
                    self._finalize_with(text)
                elif text:
                    self._emit_segment(text, is_final=False)
        else:
            if self._current_id is not None:
                self._silence_run_s += frame_s
                if self._silence_run_s >= self._silence_finalize_s:
                    self._finalize()

    def flush(self) -> None:
        if self._current_id is not None:
            self._finalize()

    def _start_utterance(self, mic_rms: float, lb_rms: float) -> None:
        self._current_id = str(uuid.uuid4())
        self._speaker = "You" if mic_rms >= lb_rms else "Them"
        self._buffer = np.empty(0, dtype=np.float32)
        self._silence_run_s = 0.0
        self._audio_since_partial_s = 0.0

    def _transcribe(self, beam: int) -> str:
        if len(self._buffer) == 0:
            return ""
        return clean_text(self._transcribe_fn(self._buffer, beam))

    def _finalize(self) -> None:
        self._finalize_with(self._transcribe(self._final_beam))

    def _finalize_with(self, text: str) -> None:
        if text:
            self._emit_segment(text, is_final=True)
        self._reset()

    def _reset(self) -> None:
        self._current_id = None
        self._buffer = np.empty(0, dtype=np.float32)
        self._silence_run_s = 0.0
        self._audio_since_partial_s = 0.0

    def _emit_segment(self, text: str, is_final: bool) -> None:
        seg = TranscriptSegment(
            id=self._current_id or str(uuid.uuid4()),
            session_id=self._session_id,
            speaker=self._speaker,
            wall_clock_time=self._last_wall_clock or datetime.now(),
            session_offset_seconds=self._last_offset,
            text=text,
            is_final=is_final,
            audio_source="mixed",
            confidence=1.0,
        )
        self._emit_fn(seg)
```

---

### Task 0: Test infrastructure

**Files:**
- Modify: `requirements.txt`
- Create: `tests/__init__.py`
- Create: `tests/test_smoke.py`

- [ ] **Step 1: Add pytest to requirements**

Append to `requirements.txt`:

```
pytest==8.2.0
```

- [ ] **Step 2: Install it**

Run: `.venv/Scripts/python.exe -m pip install pytest==8.2.0`
Expected: `Successfully installed pytest-8.2.0` (or already satisfied).

- [ ] **Step 3: Create the test package + a smoke test**

Create `tests/__init__.py` (empty file).

Create `tests/test_smoke.py`:

```python
def test_smoke():
    assert True
```

- [ ] **Step 4: Run from the project root and verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_smoke.py -v`
Expected: `1 passed`.

- [ ] **Step 5: Commit**

```bash
git add requirements.txt tests/__init__.py tests/test_smoke.py
git commit -m "test: add pytest infrastructure"
```

---

### Task 1: `mix_frame` pure helper in audio_capture

Factor the two-source mix into a pure function so capture can mix one frame at a time (replaces the tail-peek `_mix_aligned`).

**Files:**
- Modify: `backend/audio_capture.py`
- Test: `tests/test_audio_capture.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_audio_capture.py`:

```python
import numpy as np

from backend.audio_capture import mix_frame


def test_mix_frame_sums_at_half_gain():
    mic = np.array([1.0, 1.0, 1.0], dtype=np.float32)
    lb = np.array([0.4, 0.4, 0.4], dtype=np.float32)
    out = mix_frame(mic, lb)
    assert np.allclose(out, [0.7, 0.7, 0.7])
    assert out.dtype == np.float32


def test_mix_frame_clips_to_unit_range():
    mic = np.array([1.0, -1.0], dtype=np.float32)
    lb = np.array([1.0, -1.0], dtype=np.float32)
    out = mix_frame(mic, lb)
    assert np.allclose(out, [1.0, -1.0])  # 0.5+0.5 = 1.0, clipped


def test_mix_frame_pads_shorter_source_with_zeros():
    mic = np.array([1.0, 1.0, 1.0, 1.0], dtype=np.float32)
    lb = np.array([1.0, 1.0], dtype=np.float32)
    out = mix_frame(mic, lb)
    assert len(out) == 4
    # lb zero-padded at the front (right-justified by recency)
    assert np.allclose(out, [0.5, 0.5, 1.0, 1.0])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_audio_capture.py -v`
Expected: FAIL with `ImportError: cannot import name 'mix_frame'`.

- [ ] **Step 3: Add the `mix_frame` function**

In `backend/audio_capture.py`, replace the existing `_mix_aligned` function (lines ~177-193) with:

```python
def mix_frame(mic: np.ndarray, lb: np.ndarray) -> np.ndarray:
    """Sum mic + loopback at half gain, right-justified by recency, zero-padded.

    The two sources may differ slightly in length; align both to the longer
    length by zero-padding the front of the shorter one, then sum at half gain.
    """
    n = max(len(mic), len(lb))
    if n == 0:
        return np.empty(0, dtype=np.float32)

    def _pad(arr: np.ndarray) -> np.ndarray:
        a = np.asarray(arr, dtype=np.float32)
        if len(a) < n:
            a = np.concatenate([np.zeros(n - len(a), dtype=np.float32), a])
        return a

    mixed = _pad(mic) * 0.5 + _pad(lb) * 0.5
    return np.clip(mixed, -1.0, 1.0).astype(np.float32)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_audio_capture.py -v`
Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/audio_capture.py tests/test_audio_capture.py
git commit -m "feat: add pure mix_frame helper to audio_capture"
```

---

### Task 2: Capture emits contiguous 0.5s frames

Replace the overlapping 3s-window emit with contiguous, non-overlapping 0.5s frame draining. This removes the 0.5s-overlap duplication and feeds the assembler small frames.

**Files:**
- Modify: `backend/audio_capture.py` (constants ~14-17; `_emit_chunks` ~139-157)

- [ ] **Step 1: Add a frame-size constant**

Near the top constants (after `ROLLING_MAXLEN`), add:

```python
FRAME_SAMPLES = int(0.5 * TARGET_RATE)  # 0.5s frame = 8000 samples @ 16kHz
```

- [ ] **Step 2: Rewrite `_emit_chunks` to drain contiguous frames**

Replace the entire `_emit_chunks` method body with:

```python
    def _emit_chunks(self) -> None:
        """Drain contiguous, non-overlapping 0.5s mixed frames as audio arrives."""
        import time
        while not self._stop_event.is_set():
            time.sleep(0.05)
            with self._lock:
                have = min(len(self._mic_buffer), len(self._loopback_buffer))
                if have < FRAME_SAMPLES:
                    continue
                mic_frame = np.array(
                    [self._mic_buffer.popleft() for _ in range(FRAME_SAMPLES)],
                    dtype=np.float32,
                )
                lb_frame = np.array(
                    [self._loopback_buffer.popleft() for _ in range(FRAME_SAMPLES)],
                    dtype=np.float32,
                )
                mic_rms = self.get_mic_rms()
                lb_rms = self.get_loopback_rms()
            frame = mix_frame(mic_frame, lb_frame)
            if len(frame) > 0:
                self._chunk_callback(frame, mic_rms, lb_rms)
```

Note: `popleft()` consumes samples so frames never overlap. The `deque(maxlen=...)` on `_mic_buffer`/`_loopback_buffer` already bounds memory; draining keeps them from saturating during speech.

- [ ] **Step 3: Remove the now-unused `_samples_since_last_emit` bookkeeping**

In `__init__`, delete the line `self._samples_since_last_emit = 0`. In `_capture_mic`, delete the two lines:

```python
                    # Mic thread drives the emit clock (always streaming).
                    self._samples_since_last_emit += len(arr)
```

(Leave the `self._mic_buffer.extend(arr.tolist())` line.)

- [ ] **Step 4: Verify import + module load (no unit test — threads/PyAudio)**

Run: `.venv/Scripts/python.exe -c "import backend.audio_capture; print('ok')"`
Expected: `ok` (no NameError/SyntaxError). The `mix_frame` test from Task 1 still passes:
Run: `.venv/Scripts/python.exe -m pytest tests/test_audio_capture.py -v` → `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/audio_capture.py
git commit -m "feat: capture emits contiguous 0.5s frames instead of overlapping 3s windows"
```

---

### Task 3: VAD `is_speech_frame`

Add a frame-tuned speech check. Keep the existing `is_speech` for compatibility.

**Files:**
- Modify: `backend/vad.py`
- Test: `tests/test_vad.py`

- [ ] **Step 1: Write the failing test (deterministic silence case)**

Create `tests/test_vad.py`:

```python
import numpy as np

from backend.vad import SileroVAD


def test_silence_is_not_speech():
    vad = SileroVAD()
    silence = np.zeros(int(0.5 * 16000), dtype=np.float32)
    assert vad.is_speech_frame(silence) is False


def test_returns_bool():
    vad = SileroVAD()
    frame = np.zeros(int(0.5 * 16000), dtype=np.float32)
    assert isinstance(vad.is_speech_frame(frame), bool)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_vad.py -v`
Expected: FAIL with `AttributeError: 'SileroVAD' object has no attribute 'is_speech_frame'`.

- [ ] **Step 3: Add `is_speech_frame`**

In `backend/vad.py`, inside `class SileroVAD`, add after `is_speech`:

```python
    def is_speech_frame(self, frame: np.ndarray) -> bool:
        """Speech check tuned for short (~0.5s) frames."""
        tensor = torch.from_numpy(frame.copy()).float()
        result = get_speech_timestamps(
            tensor,
            self._model,
            sampling_rate=16000,
            threshold=self._threshold,
            min_speech_duration_ms=100,
        )
        return len(result) > 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_vad.py -v`
Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/vad.py tests/test_vad.py
git commit -m "feat: add is_speech_frame for short-frame VAD"
```

---

### Task 4: Assembler — accumulate + finalize on silence

Create the assembler with constructor, `process` (speech-accumulate + silence-finalize) and helpers. Partial cadence / punctuation / max-length come in later tasks, but include their constructor params now so signatures stay stable.

**Files:**
- Create: `backend/utterance.py`
- Test: `tests/test_utterance.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_utterance.py`:

```python
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
    # Disable partials so only the final emission fires (partial_interval high).
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_utterance.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.utterance'`.

- [ ] **Step 3: Create `backend/utterance.py`**

Write the full file exactly as in the "Reference — final shape" block at the top of this plan.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_utterance.py -v`
Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/utterance.py tests/test_utterance.py
git commit -m "feat: utterance assembler with silence-gap finalize"
```

---

### Task 5: Assembler — live partial emission cadence

**Files:**
- Test: `tests/test_utterance.py`
- (Implementation already present in the Reference file — this task proves it via tests.)

- [ ] **Step 1: Add failing tests**

Append to `tests/test_utterance.py`:

```python
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
```

- [ ] **Step 2: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_utterance.py -v`
Expected: `4 passed` total. (If the partial tests fail, verify the `_audio_since_partial_s` branch in `process` matches the Reference file.)

- [ ] **Step 3: Commit**

```bash
git add tests/test_utterance.py
git commit -m "test: assembler partial cadence and stable utterance id"
```

---

### Task 6: Assembler — finalize on sentence punctuation

**Files:**
- Test: `tests/test_utterance.py`

- [ ] **Step 1: Add failing test**

Append to `tests/test_utterance.py`:

```python
def test_punctuation_promotes_partial_to_final():
    # Partial transcribe returns a sentence-final string -> immediate final, no silence needed.
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
```

- [ ] **Step 2: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_utterance.py -v`
Expected: `6 passed` total.

- [ ] **Step 3: Commit**

```bash
git add tests/test_utterance.py
git commit -m "test: assembler finalizes on sentence punctuation"
```

---

### Task 7: Assembler — max-length force-finalize

**Files:**
- Test: `tests/test_utterance.py`

- [ ] **Step 1: Add failing test**

Append to `tests/test_utterance.py`:

```python
def test_max_length_forces_final_without_silence():
    # max_utterance_s=2.0; partials disabled. After 2.0s of speech -> forced final.
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
```

- [ ] **Step 2: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_utterance.py -v`
Expected: `8 passed` total.

- [ ] **Step 3: Commit**

```bash
git add tests/test_utterance.py
git commit -m "test: assembler force-finalizes at max utterance length"
```

---

### Task 8: Assembler — speaker decided once at onset

**Files:**
- Test: `tests/test_utterance.py`

- [ ] **Step 1: Add failing test**

Append to `tests/test_utterance.py`:

```python
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
```

- [ ] **Step 2: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_utterance.py -v`
Expected: `10 passed` total.

- [ ] **Step 3: Commit**

```bash
git add tests/test_utterance.py
git commit -m "test: assembler holds onset speaker for whole utterance"
```

---

### Task 9: Assembler — flush + empty/hallucination drop

**Files:**
- Test: `tests/test_utterance.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_utterance.py`:

```python
from backend.utterance import clean_text


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
```

- [ ] **Step 2: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_utterance.py -v`
Expected: `14 passed` total.

- [ ] **Step 3: Run the full Python suite**

Run: `.venv/Scripts/python.exe -m pytest tests/ -v`
Expected: all green (`test_smoke`, `test_audio_capture` ×3, `test_vad` ×2, `test_utterance` ×14).

- [ ] **Step 4: Commit**

```bash
git add tests/test_utterance.py
git commit -m "test: assembler flush and hallucination/empty drop"
```

---

### Task 10: Wire the assembler into WhisperTranscriber

Replace per-chunk transcribe+emit with: worker runs VAD per frame and feeds an `UtteranceAssembler`; transcriber exposes `transcribe(buffer, beam)`.

**Files:**
- Modify: `backend/transcriber.py`

- [ ] **Step 1: Add the transcribe-buffer method + imports**

At the top of `backend/transcriber.py`, add the import:

```python
from backend.utterance import UtteranceAssembler
```

Add this method to `WhisperTranscriber` (after `load_model`):

```python
    def transcribe(self, buffer: np.ndarray, beam_size: int) -> str:
        """Transcribe a complete audio buffer to text. Called from the worker thread."""
        if self._model is None:
            return ""
        try:
            segments, _info = self._model.transcribe(
                buffer,
                beam_size=beam_size,
                vad_filter=True,
                condition_on_previous_text=False,
                temperature=0.0,
                word_timestamps=False,
            )
            return " ".join(s.text.strip() for s in segments).strip()
        except Exception:
            return ""
```

- [ ] **Step 2: Create the assembler in `start()` and reset VAD**

Replace the body of `start()` with:

```python
    def start(self, session_id: str, session_started_at: datetime) -> None:
        """Start the worker thread for a new session."""
        self._session_id = session_id
        self._session_started_at = session_started_at
        self._last_text = ""
        self._vad.reset()
        self._assembler = UtteranceAssembler(
            transcribe_fn=self.transcribe,
            emit_fn=self._emit_callback if self._emit_callback else (lambda _seg: None),
            session_id=session_id,
        )
        self._stop_event.clear()
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()
```

Add `self._assembler: UtteranceAssembler | None = None` to `__init__`.

- [ ] **Step 3: Feed frames through VAD into the assembler**

Replace `_process_chunk` (the whole method) with:

```python
    def _process_chunk(
        self,
        chunk: np.ndarray,
        mic_rms: float,
        loopback_rms: float,
        session_id: str,
        wall_clock: datetime,
        offset: float,
    ) -> None:
        if self._model is None or self._vad is None or self._assembler is None:
            return
        is_speech = self._vad.is_speech_frame(chunk)
        self._assembler.process(chunk, is_speech, mic_rms, loopback_rms, wall_clock, offset)
```

- [ ] **Step 4: Flush the assembler on stop**

In `stop()`, before `self._queue.put(None)`, add:

```python
        if self._assembler:
            self._assembler.flush()
```

- [ ] **Step 5: Verify import + module load**

Run: `.venv/Scripts/python.exe -c "import backend.transcriber, backend.main; print('ok')"`
Expected: `ok`. Run the full suite again: `.venv/Scripts/python.exe -m pytest tests/ -v` → all green.

- [ ] **Step 6: Commit**

```bash
git add backend/transcriber.py
git commit -m "feat: drive transcription through the utterance assembler"
```

---

### Task 11: Renderer store upserts by id

**Files:**
- Modify: `src/store/transcriptStore.ts:43-44`

- [ ] **Step 1: Replace `addSegment` with an upsert**

Replace:

```typescript
  addSegment: (segment: TranscriptSegment) =>
    set((state) => ({ segments: [...state.segments, segment] })),
```

with:

```typescript
  addSegment: (segment: TranscriptSegment) =>
    set((state) => {
      const idx = state.segments.findIndex((s) => s.id === segment.id);
      if (idx === -1) {
        return { segments: [...state.segments, segment] };
      }
      const next = state.segments.slice();
      next[idx] = segment;
      return { segments: next };
    }),
```

- [ ] **Step 2: Typecheck**

Run: `npx tsc --noEmit -p tsconfig.json`
Expected: no errors from `transcriptStore.ts`.

- [ ] **Step 3: Commit**

```bash
git add src/store/transcriptStore.ts
git commit -m "feat: transcript store upserts segments by id"
```

---

### Task 12: TranscriptPanel renders partials grey/italic

**Files:**
- Modify: `src/components/TranscriptPanel.tsx`

- [ ] **Step 1: Find where a segment's text is rendered**

Open `src/components/TranscriptPanel.tsx`. Locate the element that renders `segment.text` (the per-segment row).

- [ ] **Step 2: Apply conditional styling on `is_final`**

On the element that renders the segment text, add a conditional class so non-final segments read as live/partial. Example — merge into the existing `className`:

```tsx
className={`${/* existing classes */ ""} ${segment.is_final ? "" : "italic text-gray-400"}`}
```

If the existing code uses a template literal already, insert `${segment.is_final ? "" : "italic text-gray-400"}` into it. The exact surrounding classes depend on current markup — preserve them; only add the partial-state modifier.

- [ ] **Step 3: Typecheck**

Run: `npx tsc --noEmit -p tsconfig.json`
Expected: no new errors.

- [ ] **Step 4: Commit**

```bash
git add src/components/TranscriptPanel.tsx
git commit -m "feat: render partial transcript segments grey/italic"
```

---

### Task 13: End-to-end live verification + README update

**Files:**
- Modify: `README.md` (Status section)

- [ ] **Step 1: Launch the app**

Ensure no stale sidecar on port 8001 (kill any `python` listening there). From a shell with `.venv` active:
Run: `npm run dev`
Expected: window opens; `%APPDATA%/MeetingPal/logs/sidecar.log` shows `[ws] client connected` and `model_loaded=True`.

- [ ] **Step 2: Record a multi-sentence utterance**

Start a recording. Speak (or play TTS) two full sentences with a clear pause between them, e.g. "This is the first complete sentence. Now here is the second one."
Expected in the transcript panel:
- text appears grey/italic while speaking (partials),
- settles into solid lines on each pause,
- each solid line is ONE whole sentence (not 3s fragments),
- no duplicated boundary words.

- [ ] **Step 3: Verify speaker labels**

The played/system audio sentence is labeled `Them`; speaking into the mic is labeled `You`, and the label does not flip mid-utterance.

- [ ] **Step 4: Update README Status**

In `README.md`, change the Status section's "Active work" line to read that the utterance assembler is implemented (caption-style partials settling into whole-statement finals), and remove the "Active work" framing.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: mark utterance assembler complete in README"
```

- [ ] **Step 6: Push**

```bash
git push origin main
```

---

## Self-Review

**Spec coverage:**
- Audio-accumulate + periodic re-transcribe → Tasks 4–10. ✓
- Live partials (grey) → Tasks 5, 12. ✓
- Finalize on 0.7s silence → Task 4. ✓
- Finalize on sentence punctuation → Task 6. ✓
- Force-finalize at 15s → Task 7. ✓
- Speaker decided once at onset (fixes mislabel) → Task 8. ✓
- Flush on session stop → Tasks 9, 10. ✓
- Empty/hallucination drop → Task 9. ✓
- Contiguous non-overlapping 0.5s frames (kills overlap dup) → Tasks 1–2. ✓
- `is_speech_frame` VAD → Task 3. ✓
- Renderer upsert by id → Task 11. ✓
- Partial beam=1 / final beam=5 → constructor params (Reference file) + `transcribe(buffer, beam)` (Task 10). ✓
- Single worker thread invariant preserved (assembler runs inside worker) → Task 10. ✓

**Placeholder scan:** Task 12 intentionally describes a className merge rather than a full-file rewrite because the surrounding markup is read at execution time; all other steps contain complete code. No TBD/TODO.

**Type consistency:** `process(frame, is_speech, mic_rms, lb_rms, wall_clock, offset)`, `transcribe(buffer, beam)`/`transcribe_fn(buf, beam)`, `clean_text`, `flush`, `mix_frame`, `is_speech_frame` are used identically across all tasks and the Reference file.
