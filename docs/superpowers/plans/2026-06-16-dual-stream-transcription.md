# Dual-Stream Transcription Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transcribe the microphone and the WASAPI loopback as two independent full-level streams with fixed speaker labels (`You` / `Them`), instead of mixing them into one half-gain mono stream — improving the user's-voice recognition and making diarization exact.

**Architecture:** Capture emits per-source 0.5s frames (no mixing). One Whisper model + one worker thread feed TWO `UtteranceAssembler` instances (mic→"You", loopback→"Them"), each with its own Silero VAD. Speaker is fixed per assembler (source-based), replacing the RMS-energy heuristic. A silent source is VAD-gated, so transcription only doubles while both speak.

**Tech Stack:** Python 3.11+/3.13, numpy, faster-whisper, silero-vad, pytest.

**Spec:** `docs/superpowers/specs/2026-06-16-dual-stream-transcription-design.md`

**Base branch:** `feat/utterance-assembler` (this work extends the assembler). Tests already green (20 passing) on the base.

**Sequencing note:** Tasks 1–4 are a coupled signature refactor. Each task keeps the pytest suite green and the modules importable, but the *running* app is only consistent again after Task 3 wires the new signatures. That is expected for this refactor.

---

## File Structure

| File | Responsibility | Action |
|------|----------------|--------|
| `backend/utterance.py` | `UtteranceAssembler` takes a fixed `speaker`; `process()` drops rms args | Modify |
| `tests/test_utterance.py` | helpers + tests updated for the new signature/speaker | Modify |
| `backend/audio_capture.py` | per-source 0.5s frame emit; `drain_frame` helper; remove `mix_frame` | Modify |
| `tests/test_audio_capture.py` | replace `mix_frame` tests with `drain_frame` tests | Modify |
| `backend/transcriber.py` | two VADs + two assemblers; `enqueue(source,...)`; route by source | Modify |
| `backend/main.py` | `_chunk_cb(source, frame, rms)` | Modify |
| `README.md` | note dual-stream | Modify |

---

### Task 1: Assembler takes a fixed speaker

**Files:**
- Modify: `backend/utterance.py`
- Modify: `tests/test_utterance.py`

- [ ] **Step 1: Update the test helpers + speaker tests (write the new expectations first)**

In `tests/test_utterance.py`:

(a) Replace the `build` helper and the `feed` helper with:

```python
def build(transcribe_text="hello world", speaker="You", **kw):
    rec = Recorder()
    asm = UtteranceAssembler(
        transcribe_fn=lambda buf, beam: transcribe_text,
        emit_fn=rec,
        session_id="s1",
        speaker=speaker,
        **kw,
    )
    return asm, rec


def feed(asm, *, speech: bool, n: int):
    for _ in range(n):
        asm.process(make_frame(), speech, WALL, 0.0)
```

(b) Replace the two tests `test_speaker_from_onset_rms_and_held_for_utterance` and `test_speaker_them_when_loopback_louder_at_onset` with:

```python
def test_assembler_emits_its_constructed_speaker_you():
    asm, rec = build(transcribe_text="hi", speaker="You", partial_interval_s=1.5, silence_finalize_s=0.7)
    feed(asm, speech=True, n=3)      # partial
    feed(asm, speech=False, n=2)     # finalize
    assert rec.segments and all(s.speaker == "You" for s in rec.segments)
    assert all(s.audio_source == "mic" for s in rec.segments)


def test_assembler_emits_its_constructed_speaker_them():
    asm, rec = build(transcribe_text="hi", speaker="Them", partial_interval_s=1.5, silence_finalize_s=0.7)
    feed(asm, speech=True, n=3)
    feed(asm, speech=False, n=2)
    assert rec.segments and all(s.speaker == "Them" for s in rec.segments)
    assert all(s.audio_source == "loopback" for s in rec.segments)
```

(c) In `test_silence_gap_finalizes_one_segment`, the existing assertion `assert seg.speaker == "You"` still holds (default `speaker="You"`); leave it. No other test passes rms to `feed`/`process`, so they are unaffected.

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_utterance.py -v`
Expected: FAIL — `UtteranceAssembler.__init__()` has no `speaker` kwarg / `process()` gets wrong arg count.

- [ ] **Step 3: Update `UtteranceAssembler`**

In `backend/utterance.py`:

(a) Add `speaker` as a required keyword-only constructor arg and store it. Change the signature block so the keyword-only section starts with `speaker`:

```python
    def __init__(
        self,
        transcribe_fn: TranscribeFn,
        emit_fn: EmitFn,
        session_id: str,
        *,
        speaker: Literal["You", "Them"],
        partial_interval_s: float = 1.5,
        silence_finalize_s: float = 4.0,
        max_utterance_s: float = 15.0,
        partial_beam: int = 1,
        final_beam: int = 5,
    ) -> None:
```

In the body, set `self._speaker = speaker` (replace the old `self._speaker: Literal["You", "Them"] = "You"` initialization line with `self._speaker: Literal["You", "Them"] = speaker`).

(b) Change `process` to drop the rms params:

```python
    def process(
        self,
        frame: np.ndarray,
        is_speech: bool,
        wall_clock: datetime,
        offset: float,
    ) -> None:
        self._last_wall_clock = wall_clock
        self._last_offset = offset
        frame_s = len(frame) / SAMPLE_RATE

        if is_speech:
            if self._current_id is None:
                self._start_utterance()
            self._chunks.append(frame)
            self._silence_run_s = 0.0
            self._audio_since_partial_s += frame_s

            if self._buffered_s() >= self._max_utterance_s:
                self._finalize()
                return

            if self._audio_since_partial_s >= self._partial_interval_s:
                text = self._transcribe(self._partial_beam)
                self._audio_since_partial_s = 0.0
                if text:
                    self._emit_segment(text, is_final=False)
        else:
            if self._current_id is not None:
                self._silence_run_s += frame_s
                if self._silence_run_s >= self._silence_finalize_s:
                    self._finalize()
```

(c) Change `_start_utterance` to no longer take/decide a speaker:

```python
    def _start_utterance(self) -> None:
        self._current_id = str(uuid.uuid4())
        self._chunks = []
        self._silence_run_s = 0.0
        self._audio_since_partial_s = 0.0
```

(d) In `_emit_segment`, set the audio source from the speaker (replace `audio_source="mixed",`):

```python
            audio_source="mic" if self._speaker == "You" else "loopback",
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_utterance.py -v`
Expected: all pass (the 14 assembler tests, with the two speaker tests replaced).
Also confirm import: `.venv/Scripts/python.exe -c "import backend.utterance; print('ok')"` → `ok`.

- [ ] **Step 5: Commit**

```bash
git add backend/utterance.py tests/test_utterance.py
git commit -m "feat: assembler takes a fixed speaker instead of RMS heuristic"
```

---

### Task 2: Capture emits independent per-source frames

**Files:**
- Modify: `backend/audio_capture.py`
- Modify: `tests/test_audio_capture.py`

- [ ] **Step 1: Replace the mix_frame tests with drain_frame tests**

Replace the entire contents of `tests/test_audio_capture.py` with:

```python
from collections import deque

import numpy as np

from backend.audio_capture import drain_frame


def test_drain_frame_returns_none_when_short():
    buf = deque([0.1, 0.2, 0.3])
    assert drain_frame(buf, 4) is None
    assert len(buf) == 3  # untouched


def test_drain_frame_pops_exactly_n_as_float32():
    buf = deque([float(i) for i in range(10)])
    out = drain_frame(buf, 4)
    assert out is not None
    assert out.dtype == np.float32
    assert list(out) == [0.0, 1.0, 2.0, 3.0]
    assert len(buf) == 6  # 4 consumed from the front


def test_drain_frame_exact_length():
    buf = deque([1.0, 2.0])
    out = drain_frame(buf, 2)
    assert list(out) == [1.0, 2.0]
    assert len(buf) == 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_audio_capture.py -v`
Expected: FAIL — `ImportError: cannot import name 'drain_frame'`.

- [ ] **Step 3: Add `drain_frame`, rewrite `_emit_chunks`, remove `mix_frame`**

In `backend/audio_capture.py`:

(a) Replace the module-level `mix_frame` function (the `def mix_frame(...)` block near the bottom) with:

```python
def drain_frame(buffer: deque, n: int) -> np.ndarray | None:
    """Pop exactly n samples from the front of buffer as a float32 array.

    Returns None (leaving the buffer untouched) when fewer than n samples
    are available.
    """
    if len(buffer) < n:
        return None
    return np.array([buffer.popleft() for _ in range(n)], dtype=np.float32)
```

(b) Replace the body of `_emit_chunks` (currently mixes a combined frame) with an independent per-source drain:

```python
    def _emit_chunks(self) -> None:
        """Drain contiguous 0.5s frames from each source independently (no mixing)."""
        import time
        while not self._stop_event.is_set():
            time.sleep(0.05)
            with self._lock:
                mic_frame = drain_frame(self._mic_buffer, FRAME_SAMPLES)
                lb_frame = drain_frame(self._loopback_buffer, FRAME_SAMPLES)
                mic_rms = self.get_mic_rms()
                lb_rms = self.get_loopback_rms()
            if mic_frame is not None:
                self._chunk_callback("mic", mic_frame, mic_rms)
            if lb_frame is not None:
                self._chunk_callback("loopback", lb_frame, lb_rms)
```

(c) Confirm `from collections import deque` is already imported at the top of the file (it is — `_mic_buffer`/`_loopback_buffer` are `deque`s). Confirm `mix_frame` has no remaining references in the file (grep).

- [ ] **Step 4: Run to verify it passes + import**

Run: `.venv/Scripts/python.exe -m pytest tests/test_audio_capture.py -v`
Expected: `3 passed`.
Run: `.venv/Scripts/python.exe -c "import backend.audio_capture; print('ok')"` → `ok`.
Run: `grep -n "mix_frame" backend/audio_capture.py` → no matches.

- [ ] **Step 5: Commit**

```bash
git add backend/audio_capture.py tests/test_audio_capture.py
git commit -m "feat: capture emits independent per-source frames instead of a mixed frame"
```

---

### Task 3: Transcriber routes two streams to two assemblers

**Files:**
- Modify: `backend/transcriber.py`

- [ ] **Step 1: Two VAD instances**

In `backend/transcriber.py`:

(a) In `__init__`, replace the single `self._vad: SileroVAD | None = None` line with:

```python
        self._mic_vad: SileroVAD | None = None  # lazy-loaded in load_model()
        self._lb_vad: SileroVAD | None = None
```

and replace the single `self._assembler: UtteranceAssembler | None = None` line with:

```python
        self._mic_assembler: UtteranceAssembler | None = None
        self._lb_assembler: UtteranceAssembler | None = None
```

(b) In `load_model`, replace the lazy VAD load (`if self._vad is None: self._vad = SileroVAD()`) with:

```python
        # Lazy-load one VAD per source on first model load
        if self._mic_vad is None:
            self._mic_vad = SileroVAD()
        if self._lb_vad is None:
            self._lb_vad = SileroVAD()
```

- [ ] **Step 2: Build two assemblers in `start()` and reset both VADs**

Replace the body of `start()` so it creates one assembler per source with a fixed speaker:

```python
    def start(self, session_id: str, session_started_at: datetime) -> None:
        """Start the worker thread for a new session."""
        self._session_id = session_id
        self._session_started_at = session_started_at
        if self._mic_vad:
            self._mic_vad.reset()
        if self._lb_vad:
            self._lb_vad.reset()
        emit = self._emit_callback if self._emit_callback else (lambda _seg: None)
        self._mic_assembler = UtteranceAssembler(self.transcribe, emit, session_id, speaker="You")
        self._lb_assembler = UtteranceAssembler(self.transcribe, emit, session_id, speaker="Them")
        self._stop_event.clear()
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()
```

- [ ] **Step 3: `enqueue` carries the source; worker passes it through**

Replace `enqueue` with:

```python
    def enqueue(self, source: str, frame: np.ndarray, rms: float) -> None:
        """Enqueue a 0.5s audio frame for a source ('mic' or 'loopback')."""
        now = datetime.now()
        offset = 0.0
        if self._session_started_at:
            offset = (now - self._session_started_at).total_seconds()
        self._queue.put((source, frame, rms, self._session_id, now, offset))
```

Update the queue type hint at the top of `__init__` if present (`self._queue: queue.Queue[...]`) to a permissive form:

```python
        self._queue: queue.Queue[tuple | None] = queue.Queue()
```

Replace `_worker_loop`'s unpacking + dispatch:

```python
    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                item = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue
            if item is None:
                break
            source, frame, rms, session_id, wall_clock, offset = item
            self._process_chunk(source, frame, rms, session_id, wall_clock, offset)
            self._queue.task_done()
```

- [ ] **Step 4: Route in `_process_chunk`**

Replace `_process_chunk` with:

```python
    def _process_chunk(
        self,
        source: str,
        frame: np.ndarray,
        rms: float,
        session_id: str,
        wall_clock: datetime,
        offset: float,
    ) -> None:
        if self._model is None:
            return
        if source == "mic":
            vad, assembler = self._mic_vad, self._mic_assembler
        else:
            vad, assembler = self._lb_vad, self._lb_assembler
        if vad is None or assembler is None:
            return
        is_speech = vad.is_speech_frame(frame)
        assembler.process(frame, is_speech, wall_clock, offset)
```

- [ ] **Step 5: Flush both assemblers on stop**

In `stop()`, replace the single `if self._assembler: self._assembler.flush()` (which runs AFTER the worker join) with:

```python
        if self._mic_assembler:
            self._mic_assembler.flush()
        if self._lb_assembler:
            self._lb_assembler.flush()
```

Keep the existing ordering: `_stop_event.set()` → sentinel → `worker.join()` → THEN the flushes (so the model is single-threaded).

- [ ] **Step 6: Verify imports + full suite**

Run: `.venv/Scripts/python.exe -c "import backend.transcriber, backend.main; print('ok')"` → `ok`.
Run: `.venv/Scripts/python.exe -m pytest tests/ -q` → all pass.

- [ ] **Step 7: Commit**

```bash
git add backend/transcriber.py
git commit -m "feat: route mic and loopback to separate assemblers (source-based speaker)"
```

---

### Task 4: Wire the per-source callback in main

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: Update the chunk callback**

In `backend/main.py`, in `start_session`, replace the `_chunk_cb` definition (currently `def _chunk_cb(chunk, mic_rms, lb_rms): transcriber.enqueue(chunk, mic_rms, lb_rms)`) with:

```python
    def _chunk_cb(source, frame, rms):
        transcriber.enqueue(source, frame, rms)
```

Nothing else changes (the WS broadcast, session-segment upsert, and `_audio_level_task` are untouched).

- [ ] **Step 2: Verify import + suite**

Run: `.venv/Scripts/python.exe -c "import backend.main; print('ok')"` → `ok`.
Run: `.venv/Scripts/python.exe -m pytest tests/ -q` → all pass.

- [ ] **Step 3: Commit**

```bash
git add backend/main.py
git commit -m "feat: pass audio source through the chunk callback"
```

---

### Task 5: Live verification + README + push

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Launch the app**

Free port 8001 (kill stray `python`). From a shell with `.venv` active: `npm run dev`.
Expected: window opens; sidecar healthy; `[ws] client connected`.

- [ ] **Step 2: Verify dual-stream behaviour**

Start a recording. Speak into the mic AND play speech through the speakers.
Expected:
- Your voice (mic) transcribes noticeably better than before (it is now full-level, not half-gain).
- Your lines are labelled `You`, system audio `Them`, and labels never flip mid-utterance.
- Talking over the system audio yields a `You` line and a `Them` line growing concurrently.

- [ ] **Step 3: Update README**

In `README.md`, update the transcription/Status description to note that the mic and system audio are transcribed as two independent full-level streams with source-based `You`/`Them` labels (replacing the mixed-mono + RMS-heuristic approach). Update the "Key constraints" audio line away from "mixed at 16kHz mono".

- [ ] **Step 4: Commit + push**

```bash
git add README.md
git commit -m "docs: document dual-stream transcription"
git push origin feat/dual-stream-audio
```

---

## Self-Review

**Spec coverage:**
- Per-source independent 0.5s frames, no mixing → Task 2. ✓
- Mic at full level (mix removed) → Task 2. ✓
- Two assemblers, fixed speaker per source → Tasks 1, 3. ✓
- Two VAD instances → Task 3. ✓
- One model + one worker preserved; flush both after join → Task 3. ✓
- `audio_source` reflects source → Task 1. ✓
- RMS-heuristic / `get_speaker` retired → Tasks 1 (speaker fixed) + 3 (no diarizer use). ✓
- Capture callback + enqueue carry source → Tasks 2, 3, 4. ✓
- Tests: assembler speaker tests + `drain_frame` tests → Tasks 1, 2. ✓

**Placeholder scan:** No TBD/TODO; every code step has complete code. Task 5's README step describes the exact edits to make (concrete, small).

**Type consistency:** `process(frame, is_speech, wall_clock, offset)` matches between `utterance.py` (Task 1), the assembler call in `transcriber._process_chunk` (Task 3), and the test `feed`/`process` calls (Task 1). `enqueue(source, frame, rms)` matches between `transcriber.py` (Task 3), `_worker_loop` unpack (Task 3), and `_chunk_cb` (Task 4). `chunk_callback(source, frame, rms)` matches between `audio_capture._emit_chunks` (Task 2) and `_chunk_cb` (Task 4). `drain_frame(buffer, n)` matches between `audio_capture.py` and its tests (Task 2). The constructor keyword `speaker=` matches between `utterance.py`, `transcriber.start()`, and the test `build` helper.
