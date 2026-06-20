# Pluggable Transcription Backend (Local / Cloud) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user pick local (faster-whisper, default) or cloud (Deepgram) transcription in Settings, behind one `TranscriptionBackend` interface, and remove the local O(n²) partial re-transcription via a revertible streaming assembler.

**Architecture:** A `TranscriptionBackend` protocol with two implementations — `LocalBackend` (wraps the current `WhisperTranscriber`) and `DeepgramBackend` (two Deepgram WebSocket connections, one per source). `main.py` constructs one per session from the `transcription_engine` pref. Both emit the existing `TranscriptSegment`, so the renderer/storage/auto-answer are untouched. The local assembler gains a `streaming` (LocalAgreement-2) path selectable against a preserved `legacy` path via `local_transcribe_mode`.

**Tech Stack:** Python 3.13 · FastAPI · faster-whisper · deepgram-sdk (async) · Electron 30 · React 18 · keytar · pytest

Spec: `docs/superpowers/specs/2026-06-17-pluggable-transcription-backend-design.md`

---

## File Structure

**Create:**
- `backend/transcription_backend.py` — `TranscriptionBackend` Protocol + `LocalBackend`.
- `backend/deepgram_backend.py` — `DeepgramBackend` + `pcm_float32_to_int16`.
- `backend/streaming_utterance.py` — `StreamingUtteranceAssembler` (LocalAgreement-2).
- `tests/test_streaming_utterance.py`, `tests/test_deepgram_backend.py`, `tests/test_transcription_backend.py`, `tests/test_pcm.py`, `tests/test_prefs_backend.py`.

**Modify:**
- `backend/storage.py` — new prefs.
- `backend/main.py` — `PrefsUpdate`, backend selection at session start, `/api/key/deepgram`, device/mode in `/health` or a new `/api/engine/status`, sync key on save.
- `backend/utterance.py` — rename class to `LegacyUtteranceAssembler` (keep behavior), keep `UtteranceAssembler` as alias for existing tests.
- `backend/transcriber.py` — accept an assembler factory keyed by mode; expose `device` string.
- `requirements.txt` — pin `deepgram-sdk`.
- `electron/preload.ts`, `electron/main.ts`, `src/types/electron.d.ts` — Deepgram key IPC + sync.
- `src/components/Settings.tsx` — engine selector, key field, warning gate, info readout, mode toggle.

---

## Phase 1 — Preferences plumbing

### Task 1: Add backend prefs to storage

**Files:**
- Modify: `backend/storage.py:42-46`
- Test: `tests/test_prefs_backend.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_prefs_backend.py
from backend.storage import UserPreferences


def test_backend_prefs_defaults():
    p = UserPreferences()
    assert p.transcription_engine == "local"
    assert p.cloud_provider == "deepgram"
    assert p.local_transcribe_mode == "streaming"
```

- [ ] **Step 2: Run test, verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_prefs_backend.py -v`
Expected: FAIL — `AttributeError: 'UserPreferences' object has no attribute 'transcription_engine'`

- [ ] **Step 3: Add the fields**

In `backend/storage.py`, in the `UserPreferences` dataclass after `always_on_top` / before `transcript_split`:

```python
    transcription_engine: Literal["local", "cloud"] = "local"
    cloud_provider: str = "deepgram"
    local_transcribe_mode: Literal["streaming", "legacy"] = "streaming"
```

- [ ] **Step 4: Run test, verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_prefs_backend.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/storage.py tests/test_prefs_backend.py
git commit -m "feat: add transcription_engine/cloud_provider/local_transcribe_mode prefs"
```

### Task 2: Mirror prefs in PrefsUpdate + TypeScript

**Files:**
- Modify: `backend/main.py:189-195` (`PrefsUpdate`)
- Modify: `src/types/electron.d.ts:33-52` (`UserPreferences`)

- [ ] **Step 1: Extend `PrefsUpdate`**

In `backend/main.py`, in the `PrefsUpdate` model add:

```python
    transcription_engine: str | None = None
    cloud_provider: str | None = None
    local_transcribe_mode: str | None = None
```

- [ ] **Step 2: Extend the TS interface**

In `src/types/electron.d.ts`, in `interface UserPreferences` add:

```typescript
  transcription_engine: 'local' | 'cloud';
  cloud_provider: string;
  local_transcribe_mode: 'streaming' | 'legacy';
```

- [ ] **Step 3: Verify types compile**

Run: `npx tsc --noEmit -p tsconfig.json`
Expected: no errors

- [ ] **Step 4: Verify prefs round-trip**

Run: `.venv/Scripts/python.exe -c "from backend.main import PrefsUpdate; print(PrefsUpdate(transcription_engine='cloud').transcription_engine)"`
Expected: `cloud`

- [ ] **Step 5: Commit**

```bash
git add backend/main.py src/types/electron.d.ts
git commit -m "feat: mirror backend prefs in PrefsUpdate and electron types"
```

---

## Phase 2 — Streaming assembler + kill-switch

### Task 3: Preserve current assembler as legacy

**Files:**
- Modify: `backend/utterance.py:28`
- Test: existing `tests/` referencing `UtteranceAssembler` must still pass.

- [ ] **Step 1: Rename the class, keep a back-compat alias**

In `backend/utterance.py`, rename `class UtteranceAssembler:` to `class LegacyUtteranceAssembler:`. At the end of the file add:

```python
# Back-compat alias: existing imports of UtteranceAssembler keep working and refer
# to the proven full-buffer assembler. The streaming variant lives in
# backend/streaming_utterance.py and is selected by local_transcribe_mode.
UtteranceAssembler = LegacyUtteranceAssembler
```

- [ ] **Step 2: Run the full suite, verify green**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: same pass count as before (no regressions)

- [ ] **Step 3: Commit**

```bash
git add backend/utterance.py
git commit -m "refactor: rename UtteranceAssembler to LegacyUtteranceAssembler with alias"
```

### Task 4: Define the streaming assembler interface + no-op skeleton

**Files:**
- Create: `backend/streaming_utterance.py`
- Test: `tests/test_streaming_utterance.py`

Both assemblers share this interface: `__init__(transcribe_fn, emit_fn, session_id, *, speaker)`, `process(frame, is_speech, wall_clock, offset)`, `flush()`. `transcribe_fn` here gains an optional `initial_prompt` kwarg used by the streaming path.

- [ ] **Step 1: Write the failing test (construction + interface)**

```python
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
```

- [ ] **Step 2: Run test, verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_streaming_utterance.py -v`
Expected: FAIL — module does not exist

- [ ] **Step 3: Create the skeleton**

```python
# backend/streaming_utterance.py
"""LocalAgreement-2 streaming utterance assembler.

Only the trailing uncommitted audio window is re-transcribed each partial; words
that two consecutive hypotheses agree on are committed (locked) and their audio is
dropped. This removes the O(n^2) re-transcription of the legacy assembler.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Callable, Literal

import numpy as np

from backend.models import TranscriptSegment
from backend.utterance import clean_text

SAMPLE_RATE = 16000

TranscribeFn = Callable[..., str]  # (buffer, beam, initial_prompt="") -> str
EmitFn = Callable[[TranscriptSegment], None]


class StreamingUtteranceAssembler:
    def __init__(
        self,
        transcribe_fn: TranscribeFn,
        emit_fn: EmitFn,
        session_id: str,
        *,
        speaker: Literal["You", "Them"],
        partial_interval_s: float = 1.0,
        silence_finalize_s: float = 4.0,
        max_utterance_s: float = 30.0,
        min_window_s: float = 1.0,
        beam: int = 1,
    ) -> None:
        self._transcribe_fn = transcribe_fn
        self._emit_fn = emit_fn
        self._session_id = session_id
        self._speaker = speaker
        self._partial_interval_s = partial_interval_s
        self._silence_finalize_s = silence_finalize_s
        self._max_utterance_s = max_utterance_s
        self._min_window_s = min_window_s
        self._beam = beam

        self._current_id: str | None = None
        self._committed_words: list[str] = []     # locked prefix
        self._window: list[np.ndarray] = []        # uncommitted trailing audio
        self._prev_tail_words: list[str] = []      # last hypothesis tail (for agreement)
        self._silence_run_s = 0.0
        self._audio_since_partial_s = 0.0
        self._last_wall_clock: datetime | None = None
        self._last_offset = 0.0

    def flush(self) -> None:
        if self._current_id is not None:
            self._finalize()
```

- [ ] **Step 4: Run test, verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_streaming_utterance.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/streaming_utterance.py tests/test_streaming_utterance.py
git commit -m "feat: streaming utterance assembler skeleton"
```

### Task 5: LocalAgreement-2 commit logic

**Files:**
- Modify: `backend/streaming_utterance.py`
- Test: `tests/test_streaming_utterance.py`

LocalAgreement-2 rule: split each new hypothesis into words. The longest common prefix between this hypothesis and the previous hypothesis (beyond what is already committed) is the **agreed** portion → commit it. Keep the rest as the unstable tail. The emitted partial text = committed words + current hypothesis tail.

- [ ] **Step 1: Write failing tests for the agreement helper**

```python
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
```

- [ ] **Step 2: Run, verify fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_streaming_utterance.py -v`
Expected: FAIL — `_common_prefix` / `committed_text` / `process` not implemented

- [ ] **Step 3: Implement agreement + process**

Add to `backend/streaming_utterance.py`:

```python
def _common_prefix(a: list[str], b: list[str]) -> list[str]:
    out: list[str] = []
    for x, y in zip(a, b):
        if x == y:
            out.append(x)
        else:
            break
    return out
```

Add these to `__init__`: `self._committed_audio_s = 0.0`. Then add methods to `StreamingUtteranceAssembler`:

```python
    def committed_text(self) -> str:
        return " ".join(self._committed_words).strip()

    def _window_s(self) -> float:
        return sum(len(c) for c in self._window) / SAMPLE_RATE

    def _start_utterance(self) -> None:
        self._current_id = str(uuid.uuid4())
        self._committed_words = []
        self._window = []
        self._prev_tail_words = []
        self._committed_audio_s = 0.0
        self._silence_run_s = 0.0
        self._audio_since_partial_s = 0.0

    def process(self, frame, is_speech, wall_clock, offset) -> None:
        self._last_wall_clock = wall_clock
        self._last_offset = offset
        frame_s = len(frame) / SAMPLE_RATE

        if is_speech:
            if self._current_id is None:
                self._start_utterance()
            self._window.append(frame)
            self._silence_run_s = 0.0
            self._audio_since_partial_s += frame_s

            if self._committed_audio_s + self._window_s() >= self._max_utterance_s:
                self._finalize()
                return
            if (self._audio_since_partial_s >= self._partial_interval_s
                    and self._window_s() >= self._min_window_s):
                self._audio_since_partial_s = 0.0
                self._run_partial()
        else:
            if self._current_id is not None:
                self._silence_run_s += frame_s
                if self._silence_run_s >= self._silence_finalize_s:
                    self._finalize()

    def _run_partial(self) -> None:
        buf = np.concatenate(self._window)
        hyp = clean_text(self._transcribe_fn(buf, self._beam, initial_prompt=self.committed_text()))
        words = hyp.split()
        agreed = _common_prefix(words, self._prev_tail_words)
        if agreed:
            self._commit_words(agreed, words)
            tail_words = words[len(agreed):]
            self._prev_tail_words = []   # window changed; restart agreement
        else:
            tail_words = words
            self._prev_tail_words = words
        text = (self.committed_text() + " " + " ".join(tail_words)).strip()
        if text:
            self._emit_segment(text, is_final=False)
```

- [ ] **Step 4: Add `_commit_words`, `_finalize`, `_reset`, `_emit_segment`**

`agreed` is the common prefix of the current and previous hypotheses *over the current
window* (which holds only not-yet-committed audio), so every word in `agreed` is new —
append all of it. The committed audio is dropped from the window proportionally to the
fraction of hypothesis words committed. (Proportional trimming is the v1 heuristic; the
documented robust upgrade is word-timestamp-based trimming — see spec "Risks". The kill-
switch to `legacy` covers any quality regression.)

```python
    def _commit_words(self, agreed: list[str], hyp_words: list[str]) -> None:
        self._committed_words.extend(agreed)
        if not self._window:
            return
        merged = np.concatenate(self._window)
        frac = min(1.0, len(agreed) / len(hyp_words)) if hyp_words else 1.0
        drop = int(frac * merged.size)
        kept = merged[drop:]
        self._committed_audio_s += drop / SAMPLE_RATE
        self._window = [kept] if kept.size else []

    def _finalize(self) -> None:
        text = self.committed_text()
        if self._window:
            buf = np.concatenate(self._window)
            tail = clean_text(self._transcribe_fn(buf, self._beam, initial_prompt=text))
            text = (text + " " + tail).strip()
        if text:
            self._emit_segment(text, is_final=True)
        self._reset()

    def _reset(self) -> None:
        self._current_id = None
        self._committed_words = []
        self._window = []
        self._prev_tail_words = []
        self._committed_audio_s = 0.0
        self._silence_run_s = 0.0
        self._audio_since_partial_s = 0.0

    def _emit_segment(self, text: str, is_final: bool) -> None:
        assert self._current_id is not None
        seg = TranscriptSegment(
            id=self._current_id,
            session_id=self._session_id,
            speaker=self._speaker,
            wall_clock_time=self._last_wall_clock or datetime.now(),
            session_offset_seconds=self._last_offset,
            text=text,
            is_final=is_final,
            audio_source="mic" if self._speaker == "You" else "loopback",
            confidence=1.0,
        )
        self._emit_fn(seg)
```

- [ ] **Step 5: Run tests, verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_streaming_utterance.py -v`
Expected: PASS (`test_longest_common_prefix`, `test_commit_on_two_agreeing_hypotheses`)

- [ ] **Step 6: Add finalize + silence tests**

```python
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
```

- [ ] **Step 7: Run, verify pass; commit**

Run: `.venv/Scripts/python.exe -m pytest tests/test_streaming_utterance.py -v`
Expected: PASS

```bash
git add backend/streaming_utterance.py tests/test_streaming_utterance.py
git commit -m "feat: LocalAgreement-2 commit logic in streaming assembler"
```

### Task 6: Transcriber selects assembler by mode + exposes device

**Files:**
- Modify: `backend/transcriber.py:20-104`
- Test: `tests/test_transcription_backend.py` (added in Task 7 also covers this)

- [ ] **Step 1: Write failing test**

```python
# tests/test_transcriber_mode.py
from backend.transcriber import WhisperTranscriber


def test_assembler_class_by_mode():
    t_stream = WhisperTranscriber(model_name="base.en", transcribe_mode="streaming")
    t_legacy = WhisperTranscriber(model_name="base.en", transcribe_mode="legacy")
    assert t_stream._assembler_cls.__name__ == "StreamingUtteranceAssembler"
    assert t_legacy._assembler_cls.__name__ == "LegacyUtteranceAssembler"


def test_device_defaults_to_unknown_before_load():
    t = WhisperTranscriber(model_name="base.en")
    assert t.device in ("cpu", "cuda", "unknown")
```

- [ ] **Step 2: Run, verify fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_transcriber_mode.py -v`
Expected: FAIL — `transcribe_mode` not accepted

- [ ] **Step 3: Implement**

In `backend/transcriber.py`:

- Import both assemblers:

```python
from backend.utterance import LegacyUtteranceAssembler
from backend.streaming_utterance import StreamingUtteranceAssembler
```

- Add `transcribe_mode` param to `__init__` and pick the class + track device:

```python
    def __init__(
        self,
        model_name: str = "base.en",
        emit_callback: Callable[[TranscriptSegment], None] | None = None,
        download_progress_cb: DownloadProgressCallback | None = None,
        transcribe_mode: str = "streaming",
    ) -> None:
        ...
        self._assembler_cls = (
            StreamingUtteranceAssembler if transcribe_mode == "streaming"
            else LegacyUtteranceAssembler
        )
        self._device = "unknown"
```

- Add a `device` property:

```python
    @property
    def device(self) -> str:
        return self._device
```

- Set `self._device` in `load_model` on each branch (`"cuda"` in the try, `"cpu"` in the except).

- In `start()`, build assemblers via the class:

```python
        self._mic_assembler = self._assembler_cls(self.transcribe, emit, session_id, speaker="You")
        self._lb_assembler = self._assembler_cls(self.transcribe, emit, session_id, speaker="Them")
```

- Update `transcribe` to accept the optional prompt:

```python
    def transcribe(self, buffer: np.ndarray, beam_size: int, initial_prompt: str = "") -> str:
        ...
        segments, _info = self._model.transcribe(
            buffer,
            beam_size=beam_size,
            vad_filter=False,
            condition_on_previous_text=False,
            temperature=0.0,
            word_timestamps=False,
            initial_prompt=initial_prompt or None,
        )
```

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_transcriber_mode.py tests/ -q`
Expected: PASS (and no regressions)

- [ ] **Step 5: Commit**

```bash
git add backend/transcriber.py tests/test_transcriber_mode.py
git commit -m "feat: transcriber picks assembler by mode and tracks device"
```

---

## Phase 3 — Backend abstraction + LocalBackend

### Task 7: TranscriptionBackend protocol + LocalBackend wrapper

**Files:**
- Create: `backend/transcription_backend.py`
- Test: `tests/test_transcription_backend.py`

- [ ] **Step 1: Write failing test**

```python
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
```

- [ ] **Step 2: Run, verify fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_transcription_backend.py -v`
Expected: FAIL — module missing

- [ ] **Step 3: Implement**

```python
# backend/transcription_backend.py
"""Pluggable transcription backend interface and the local implementation."""
from __future__ import annotations

from datetime import datetime
from typing import Protocol

import numpy as np


class TranscriptionBackend(Protocol):
    def start(self, session_id: str, started_at: datetime) -> None: ...
    def feed(self, source: str, frame: np.ndarray, rms: float) -> None: ...
    def stop(self) -> None: ...
    def ready(self) -> bool: ...


class LocalBackend:
    """Wraps the existing WhisperTranscriber behind the backend interface."""

    def __init__(self, transcriber) -> None:
        self._t = transcriber

    def start(self, session_id: str, started_at: datetime) -> None:
        self._t.start(session_id, started_at)

    def feed(self, source: str, frame: np.ndarray, rms: float) -> None:
        self._t.enqueue(source, frame, rms)

    def stop(self) -> None:
        self._t.stop()

    def ready(self) -> bool:
        return bool(getattr(self._t, "model_loaded", False))

    @property
    def device(self) -> str:
        return getattr(self._t, "device", "unknown")
```

- [ ] **Step 4: Run, verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_transcription_backend.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/transcription_backend.py tests/test_transcription_backend.py
git commit -m "feat: TranscriptionBackend protocol + LocalBackend wrapper"
```

---

## Phase 4 — DeepgramBackend

### Task 8: PCM float32→int16 conversion

**Files:**
- Modify: `backend/deepgram_backend.py` (create)
- Test: `tests/test_pcm.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_pcm.py
import numpy as np
from backend.deepgram_backend import pcm_float32_to_int16


def test_pcm_conversion_scales_and_clips():
    x = np.array([0.0, 1.0, -1.0, 2.0, -2.0, 0.5], dtype=np.float32)
    raw = pcm_float32_to_int16(x)
    out = np.frombuffer(raw, dtype="<i2")
    assert out[0] == 0
    assert out[1] == 32767
    assert out[2] == -32767 or out[2] == -32768
    assert out[3] == 32767   # clipped
    assert out[4] <= -32767  # clipped
    assert abs(int(out[5]) - 16383) <= 2
    assert raw.__class__ is bytes
```

- [ ] **Step 2: Run, verify fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_pcm.py -v`
Expected: FAIL — module missing

- [ ] **Step 3: Implement (start the module)**

```python
# backend/deepgram_backend.py
"""Deepgram cloud transcription backend — two WS connections, one per source."""
from __future__ import annotations

import numpy as np


def pcm_float32_to_int16(frame: np.ndarray) -> bytes:
    """Convert float32 [-1, 1] mono audio to little-endian int16 PCM bytes."""
    clipped = np.clip(frame, -1.0, 1.0)
    return (clipped * 32767.0).astype("<i2").tobytes()
```

- [ ] **Step 4: Run, verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_pcm.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/deepgram_backend.py tests/test_pcm.py
git commit -m "feat: float32->int16 PCM conversion for Deepgram"
```

### Task 9: Deepgram event → TranscriptSegment mapping (pure function)

**Files:**
- Modify: `backend/deepgram_backend.py`
- Test: `tests/test_deepgram_backend.py`

Isolate the mapping from the network so it is unit-testable without a socket. A small per-source `DeepgramStreamMapper` holds the current utterance id and turns Deepgram result dicts into `TranscriptSegment`s.

- [ ] **Step 1: Write failing test**

```python
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
```

- [ ] **Step 2: Run, verify fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_deepgram_backend.py -v`
Expected: FAIL — `DeepgramStreamMapper` missing

- [ ] **Step 3: Implement the mapper**

Append to `backend/deepgram_backend.py`:

```python
import uuid
from datetime import datetime
from typing import Callable

from backend.models import TranscriptSegment

EmitFn = Callable[[TranscriptSegment], None]


class DeepgramStreamMapper:
    """Maps one source's Deepgram results to TranscriptSegments with stable ids."""

    def __init__(self, source: str, session_id: str, emit: EmitFn,
                 started_at: datetime | None = None) -> None:
        self._source = source
        self._speaker = "You" if source == "mic" else "Them"
        self._session_id = session_id
        self._emit = emit
        self._started_at = started_at or datetime.now()
        self._current_id: str | None = None

    def handle(self, result: dict) -> None:
        alts = result.get("channel", {}).get("alternatives", [{}])
        text = (alts[0].get("transcript") or "").strip()
        if not text:
            return
        if self._current_id is None:
            self._current_id = str(uuid.uuid4())
        is_final = bool(result.get("is_final"))
        now = datetime.now()
        seg = TranscriptSegment(
            id=self._current_id,
            session_id=self._session_id,
            speaker=self._speaker,
            wall_clock_time=now,
            session_offset_seconds=(now - self._started_at).total_seconds(),
            text=text,
            is_final=is_final,
            audio_source=self._source,
            confidence=1.0,
        )
        self._emit(seg)
        if is_final:
            self._current_id = None  # next result starts a new utterance
```

- [ ] **Step 4: Run, verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_deepgram_backend.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/deepgram_backend.py tests/test_deepgram_backend.py
git commit -m "feat: Deepgram result -> TranscriptSegment mapper"
```

### Task 10: DeepgramBackend network shell (async loop in thread)

**Files:**
- Modify: `backend/deepgram_backend.py`
- Modify: `requirements.txt`
- Test: `tests/test_deepgram_backend.py` (add an error-path test with a fake connection)

- [ ] **Step 1: Pin the SDK**

Add to `requirements.txt`:

```text
deepgram-sdk==3.7.* ; python_version >= "3.11"
```

Then: `.venv/Scripts/python.exe -m pip install "deepgram-sdk==3.7.*"`

- [ ] **Step 2: Write failing test (start/feed/stop with injected connection factory + error emits)**

```python
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
```

- [ ] **Step 3: Run, verify fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_deepgram_backend.py::test_backend_feeds_pcm_and_reports_error -v`
Expected: FAIL — `DeepgramBackend` missing

- [ ] **Step 4: Implement the backend shell**

Append to `backend/deepgram_backend.py`. The backend owns a dedicated asyncio loop in a thread; `feed` converts to PCM and pushes via `run_coroutine_threadsafe` into a **bounded** queue per source (drop oldest on overflow). `conn_factory` is injectable so tests skip real sockets.

```python
import asyncio
import threading
from collections import deque

MAX_QUEUED_FRAMES = 50  # ~25s at 0.5s frames; drop oldest beyond this (backpressure)


class DeepgramBackend:
    def __init__(self, api_key, session_id, emit, on_error,
                 conn_factory=None, started_at=None):
        self._api_key = api_key
        self._session_id = session_id
        self._emit = emit
        self._on_error = on_error
        self._conn_factory = conn_factory or self._default_conn_factory
        self._started_at = started_at
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._conns: dict[str, object] = {}
        self._queues: dict[str, deque] = {"mic": deque(), "loopback": deque()}
        self._mappers: dict[str, DeepgramStreamMapper] = {}

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def start(self, session_id: str, started_at: datetime) -> None:
        self._started_at = started_at
        self._thread.start()
        for source in ("mic", "loopback"):
            self._mappers[source] = DeepgramStreamMapper(
                source, session_id, self._emit, started_at)
            fut = asyncio.run_coroutine_threadsafe(self._open(source), self._loop)
            try:
                self._conns[source] = fut.result(timeout=10)
            except Exception as e:  # connection failure → inform, no fallback
                self._on_error(f"Cloud transcription failed to connect ({source}): {e}")

    async def _open(self, source: str):
        def on_message(result: dict):
            self._mappers[source].handle(result)
        def on_error(err):
            self._on_error(f"Cloud transcription error ({source}): {err}")
        return self._conn_factory(source, on_message, on_error)

    def feed(self, source: str, frame: np.ndarray, rms: float) -> None:
        conn = self._conns.get(source)
        if conn is None:
            return
        pcm = pcm_float32_to_int16(frame)
        q = self._queues[source]
        q.append(pcm)
        while len(q) > MAX_QUEUED_FRAMES:
            q.popleft()  # drop oldest under backpressure
        asyncio.run_coroutine_threadsafe(self._drain(source), self._loop)

    async def _drain(self, source: str):
        conn = self._conns.get(source)
        q = self._queues[source]
        while q and conn is not None:
            data = q.popleft()
            try:
                await conn.send(data)
            except Exception as e:
                self._on_error(f"Cloud send failed ({source}): {e}")
                return

    def stop(self) -> None:
        async def _close():
            for c in self._conns.values():
                try:
                    await c.finish()
                except Exception:
                    pass
        if self._thread.is_alive():
            fut = asyncio.run_coroutine_threadsafe(_close(), self._loop)
            try:
                fut.result(timeout=5)
            except Exception:
                pass
            self._loop.call_soon_threadsafe(self._loop.stop)

    def ready(self) -> bool:
        return True

    def _default_conn_factory(self, source, on_message, on_error):
        """Open a real Deepgram live WS. The key is passed to the SDK client (header
        auth) — never placed in the URL/query and never logged.

        deepgram-sdk v3 live transcription: model=nova-2, encoding=linear16,
        sample_rate=16000, channels=1, interim_results=True, endpointing on,
        diarize=False. `on_message` receives `result.to_dict()`.
        """
        from deepgram import DeepgramClient, LiveOptions, LiveTranscriptionEvents
        dg = DeepgramClient(self._api_key)  # header auth, key never logged
        conn = dg.listen.websocket.v("1")

        conn.on(LiveTranscriptionEvents.Transcript,
                lambda _s, result, **kw: on_message(result.to_dict()))
        conn.on(LiveTranscriptionEvents.Error,
                lambda _s, error, **kw: on_error(error))
        conn.start(LiveOptions(
            model="nova-2", language="en-US", encoding="linear16",
            sample_rate=16000, channels=1, interim_results=True,
            endpointing=300, diarize=False,
        ))
        return conn
```

`self._conn_factory = conn_factory or self._default_conn_factory` binds the instance method when no factory is injected, so `self._api_key` is in scope. `_default_conn_factory` is the only part touching the live SDK and is verified by manual/live testing, not unit tests.

- [ ] **Step 5: Run, verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_deepgram_backend.py -v`
Expected: PASS (mapper tests + feed/error test)

- [ ] **Step 6: Commit**

```bash
git add backend/deepgram_backend.py tests/test_deepgram_backend.py requirements.txt
git commit -m "feat: DeepgramBackend async-in-thread shell with bounded backpressure"
```

---

## Phase 5 — Wiring, keys, Settings UI

### Task 11: Deepgram key endpoint + sidecar memory

**Files:**
- Modify: `backend/main.py` (after `/api/key/gemini`, ~line 235)
- Test: `tests/test_deepgram_key_endpoint.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_deepgram_key_endpoint.py
from fastapi.testclient import TestClient
from backend import main


def test_store_deepgram_key():
    with TestClient(main.app) as client:
        r = client.post("/api/key/deepgram", json={"api_key": "dg-123"})
        assert r.status_code == 200
        assert r.json() == {"stored": True}
        assert main._deepgram_key_memory == "dg-123"
```

- [ ] **Step 2: Run, verify fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_deepgram_key_endpoint.py -v`
Expected: FAIL — route/global missing

- [ ] **Step 3: Implement**

In `backend/main.py` add near the other key globals (line ~40):

```python
_deepgram_key_memory: str | None = None  # Deepgram key, in-process only
```

And after `store_gemini_key`:

```python
@app.post("/api/key/deepgram")
def store_deepgram_key(body: KeyBody):
    global _deepgram_key_memory
    _deepgram_key_memory = body.api_key
    _flush("[key] Deepgram API key stored in memory")
    return {"stored": True}
```

- [ ] **Step 4: Run, verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_deepgram_key_endpoint.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/main.py tests/test_deepgram_key_endpoint.py
git commit -m "feat: /api/key/deepgram endpoint stores key in sidecar memory"
```

### Task 12: Engine status endpoint (device/model/mode readout)

**Files:**
- Modify: `backend/main.py`
- Test: `tests/test_engine_status.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_engine_status.py
from fastapi.testclient import TestClient
from backend import main


def test_engine_status_shape():
    with TestClient(main.app) as client:
        r = client.get("/api/engine/status")
        assert r.status_code == 200
        body = r.json()
        assert body["engine"] in ("local", "cloud")
        assert "device" in body and "model" in body and "mode" in body
```

- [ ] **Step 2: Run, verify fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_engine_status.py -v`
Expected: FAIL — route missing

- [ ] **Step 3: Implement**

In `backend/main.py`:

```python
@app.get("/api/engine/status")
def engine_status():
    device = transcriber.device if transcriber else "unknown"
    return {
        "engine": prefs.transcription_engine,
        "device": "GPU (CUDA)" if device == "cuda" else "CPU" if device == "cpu" else "unknown",
        "model": prefs.whisper_model,
        "mode": prefs.local_transcribe_mode,
        "cloud_provider": prefs.cloud_provider,
    }
```

- [ ] **Step 4: Run, verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_engine_status.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/main.py tests/test_engine_status.py
git commit -m "feat: /api/engine/status returns device/model/mode for Settings readout"
```

### Task 13: Select backend at session start

**Files:**
- Modify: `backend/main.py:257-286` (`start_session`) and lifespan (`transcriber` construction with mode)

- [ ] **Step 1: Construct the transcriber with the saved mode**

In `lifespan`, pass the mode:

```python
    transcriber = WhisperTranscriber(
        model_name=prefs.whisper_model,
        emit_callback=_on_transcript_segment,
        transcribe_mode=prefs.local_transcribe_mode,
    )
```

- [ ] **Step 2: Build the active backend in `start_session`**

Replace the `_chunk_cb` + `transcriber.start(...)` block with backend selection:

```python
    from backend.transcription_backend import LocalBackend
    from backend.deepgram_backend import DeepgramBackend

    global active_backend
    if prefs.transcription_engine == "cloud":
        if not _deepgram_key_memory:
            active_session = None
            raise HTTPException(status_code=400, detail="Cloud engine selected but no Deepgram key set")
        active_backend = DeepgramBackend(
            api_key=_deepgram_key_memory,
            session_id=session.id,
            emit=_on_transcript_segment,
            on_error=lambda msg: event_loop and event_loop.call_soon_threadsafe(
                lambda: asyncio.ensure_future(_broadcast(
                    {"type": "error", "code": "cloud_transcription",
                     "message": msg, "recoverable": True}))),
            started_at=session.started_at,
        )
    else:
        if not transcriber or not transcriber.model_loaded:
            raise HTTPException(status_code=503, detail="Whisper model not yet loaded")
        active_backend = LocalBackend(transcriber)

    def _chunk_cb(source, frame, rms):
        active_backend.feed(source, frame, rms)

    audio_capture = AudioCapture(
        chunk_callback=_chunk_cb,
        mic_device_index=body.mic_device_index or prefs.mic_device_index,
        loopback_device_index=body.loopback_device_index or prefs.loopback_device_index,
    )
    active_backend.start(session.id, session.started_at)
    audio_capture.start()
```

Add `active_backend = None` to module globals near `active_session`, and in `_do_stop_session` replace `transcriber.stop()` with:

```python
    if active_backend:
        active_backend.stop()
```

- [ ] **Step 3: Move the model-loaded gate**

The cloud path must NOT require the Whisper model. Remove the top-level `if not transcriber or not transcriber.model_loaded` early-return at line 267 (the check now lives inside the `else` branch above).

- [ ] **Step 4: Run backend + smoke test**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: PASS (existing session tests still green; local path unchanged behavior)

Run (manual local smoke): `.venv/Scripts/python.exe backend/main.py` then start a session via the app in local mode — transcription works as before.

- [ ] **Step 5: Commit**

```bash
git add backend/main.py
git commit -m "feat: select Local/Deepgram backend at session start from prefs"
```

### Task 14: Re-sync Deepgram key on save (Electron)

**Files:**
- Modify: `electron/preload.ts:78`, `electron/main.ts` (key IPC + syncKeysToSidecar), `src/types/electron.d.ts`

- [ ] **Step 1: Add the preload bridge**

In `electron/preload.ts` after `hasGeminiKey`:

```typescript
  setDeepgramKey: (key: string) => ipcRenderer.invoke('set-deepgram-key', key),
  hasDeepgramKey: () => ipcRenderer.invoke('has-deepgram-key'),
```

- [ ] **Step 2: Add the IPC handlers in `electron/main.ts`**

Mirror the gemini handlers (keytar account `deepgram-api-key`); on `set-deepgram-key`, store in keytar AND POST to the sidecar immediately:

```typescript
ipcMain.handle('set-deepgram-key', async (_e, key: string) => {
  await keytar.setPassword(KEYTAR_SERVICE, 'deepgram-api-key', key);
  await apiRequest('POST', '/api/key/deepgram', { api_key: key });  // sync on save
});
ipcMain.handle('has-deepgram-key', async () => {
  return Boolean(await keytar.getPassword(KEYTAR_SERVICE, 'deepgram-api-key'));
});
```

In the existing startup `syncKeysToSidecar` routine, add a Deepgram sync alongside the anthropic/gemini ones:

```typescript
const dgKey = await keytar.getPassword(KEYTAR_SERVICE, 'deepgram-api-key');
if (dgKey) await apiRequest('POST', '/api/key/deepgram', { api_key: dgKey });
```

- [ ] **Step 3: Declare the API in `src/types/electron.d.ts`**

```typescript
  setDeepgramKey(key: string): Promise<void>;
  hasDeepgramKey(): Promise<boolean>;
```

- [ ] **Step 4: Verify Electron + renderer typecheck**

Run: `npx tsc --noEmit -p tsconfig.electron.json && npx tsc --noEmit -p tsconfig.json`
Expected: no errors

- [ ] **Step 5: Commit**

```bash
git add electron/preload.ts electron/main.ts src/types/electron.d.ts
git commit -m "feat: Deepgram key keytar storage + sync to sidecar on save and startup"
```

### Task 15: Settings UI — engine selector, key, warning gate, info, mode toggle

**Files:**
- Modify: `src/components/Settings.tsx`

- [ ] **Step 1: Add engine state + status fetch**

In `Settings.tsx`, add state and load the current prefs + engine status:

```typescript
const [engine, setEngine] = useState<'local' | 'cloud'>('local');
const [mode, setMode] = useState<'streaming' | 'legacy'>('streaming');
const [hasDgKey, setHasDgKey] = useState(false);
const [dgKeyInput, setDgKeyInput] = useState('');
const [cloudAck, setCloudAck] = useState(false);
const [status, setStatus] = useState<{ device: string; model: string } | null>(null);

useEffect(() => {
  window.electronAPI.getPreferences().then((p) => {
    setEngine(p.transcription_engine);
    setMode(p.local_transcribe_mode);
  });
  window.electronAPI.hasDeepgramKey().then(setHasDgKey);
  fetch('http://127.0.0.1:8000/api/engine/status')
    .then((r) => r.json()).then((s) => setStatus({ device: s.device, model: s.model }))
    .catch(() => setStatus(null));
}, []);
```

> NOTE: use the sidecar base URL constant already used elsewhere in the renderer if one exists; otherwise the IPC `getPreferences` pattern. Do not hardcode the port if a helper exists.

- [ ] **Step 2: Render the engine section**

Add a "Transcription" section. Engine radios disabled while recording (read `isRecording` from `useRecording`/store):

```tsx
<section className="space-y-2">
  <h3 className="text-sm font-semibold text-gray-200">Transcription</h3>
  <label className="flex items-center gap-2">
    <input type="radio" name="engine" checked={engine === 'local'}
      disabled={isRecording}
      onChange={() => { setEngine('local'); window.electronAPI.setPreferences({ transcription_engine: 'local' } as never); }} />
    <span>Local (private, on-device)</span>
  </label>
  <label className="flex items-center gap-2">
    <input type="radio" name="engine" checked={engine === 'cloud'}
      disabled={isRecording || !(hasDgKey && (cloudAck || engine === 'cloud'))}
      onChange={() => { setEngine('cloud'); window.electronAPI.setPreferences({ transcription_engine: 'cloud' } as never); }} />
    <span>Cloud (Deepgram)</span>
  </label>
  {isRecording && <p className="text-xs text-gray-500">Applies on next recording start.</p>}

  {engine === 'local' && status && (
    <p className="text-xs text-gray-400">Engine: Local · Device: {status.device} · Model: {status.model}</p>
  )}
  {engine === 'local' && (
    <label className="flex items-center gap-2 text-xs text-gray-400">
      Transcription mode:
      <select value={mode} disabled={isRecording}
        onChange={(e) => { const m = e.target.value as 'streaming' | 'legacy';
          setMode(m); window.electronAPI.setPreferences({ local_transcribe_mode: m } as never); }}>
        <option value="streaming">Streaming (faster)</option>
        <option value="legacy">Legacy (stable)</option>
      </select>
    </label>
  )}
</section>
```

- [ ] **Step 3: Render the cloud key + warning gate**

```tsx
{(engine === 'cloud' || !hasDgKey) && (
  <div className="space-y-2 border-t border-gray-800 pt-2">
    <p className="text-xs text-amber-400">
      ⚠ Cloud mode streams your meeting audio to Deepgram for transcription.
    </p>
    <label className="flex items-center gap-2 text-xs">
      <input type="checkbox" checked={cloudAck} onChange={(e) => setCloudAck(e.target.checked)} />
      I understand audio will be sent to Deepgram.
    </label>
    <div className="flex gap-2">
      <input type="password" placeholder="Deepgram API key" value={dgKeyInput}
        onChange={(e) => setDgKeyInput(e.target.value)}
        className="flex-1 bg-gray-800 rounded px-2 py-1 text-sm" />
      <button
        disabled={!dgKeyInput || !cloudAck}
        onClick={async () => { await window.electronAPI.setDeepgramKey(dgKeyInput);
          setHasDgKey(true); setDgKeyInput(''); }}
        className="px-3 py-1 rounded bg-blue-600 text-white text-sm disabled:opacity-40">
        Save key
      </button>
    </div>
  </div>
)}
```

- [ ] **Step 4: Typecheck**

Run: `npx tsc --noEmit -p tsconfig.json`
Expected: no errors

- [ ] **Step 5: Commit**

```bash
git add src/components/Settings.tsx
git commit -m "feat: Settings transcription engine selector, Deepgram key + warning gate, mode toggle, device info"
```

### Task 16: Verify PyInstaller bundles deepgram-sdk

**Files:**
- Modify: `meetingpal.spec` (hidden imports if needed)

- [ ] **Step 1: Build the sidecar**

Run: `.venv/Scripts/pyinstaller meetingpal.spec`
Expected: build completes

- [ ] **Step 2: Smoke-test the bundled import**

Run: `dist/meetingpal/meetingpal.exe` (or the spec's output path) and hit `/health`.
Expected: process starts, no `ModuleNotFoundError: deepgram`.

- [ ] **Step 3: If the import is missing, add hidden imports**

In `meetingpal.spec`, add to `hiddenimports`:

```python
hiddenimports = [..., 'deepgram', 'websockets', 'aiohttp']
```

Rebuild and re-run Step 2.

- [ ] **Step 4: Commit**

```bash
git add meetingpal.spec
git commit -m "build: ensure PyInstaller bundles deepgram-sdk async deps"
```

---

## Final verification

- [ ] Full backend suite green: `.venv/Scripts/python.exe -m pytest tests/ -q`
- [ ] Renderer + Electron typecheck: `npx tsc --noEmit -p tsconfig.json && npx tsc --noEmit -p tsconfig.electron.json`
- [ ] Manual: local streaming mode transcribes; flip to `legacy` in Settings → still works (kill-switch).
- [ ] Manual: cloud mode with a Deepgram key transcribes You/Them via two connections; pulling the network surfaces a recoverable error (no silent reroute).
- [ ] Do NOT merge PRs or push to `main` without explicit approval.
