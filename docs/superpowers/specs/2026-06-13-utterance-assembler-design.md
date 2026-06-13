# Utterance Assembler — Design Spec

**Date:** 2026-06-13
**Status:** Approved (pre-implementation)
**Problem:** Transcript lines are fragments, not whole statements. Each fixed 3s audio chunk is transcribed independently and emitted as `is_final=True`, so one spoken sentence gets chopped at the 3s grid (plus 0.5s overlap duplicates boundary words).

## Goal

Caption-style transcription: live **partial** text streams as someone speaks, then **settles** into one clean, whole final statement on a speech pause. Each finished transcript line = one complete utterance.

## Chosen approach

**Audio-accumulate + periodic re-transcribe** (Approach 1 of 3 considered).

Rejected:
- *Text-merge fragments on the 3s grid* — fuzzy overlap merging mis-handles repeated words; partials only update every 3s (no live feel).
- *Swap in a streaming-ASR library* — new dependency, largest rewrite/risk. Overkill now.

## Architecture & data flow

A new **UtteranceAssembler** sits between audio capture and the WS emit. The single Whisper worker thread is preserved (the model is not thread-safe).

```
mic + loopback capture threads
  -> capture emits contiguous, NON-overlapping ~0.5s mixed frames (16kHz mono)   # removes the 0.5s overlap dup bug
    -> frame queue -> single worker thread
      -> UtteranceAssembler.process(frame, mic_rms, lb_rms, wall_clock, offset)
          - VAD(frame): speech / silence
          - accumulate speech into a growing buffer
          - every 1.5s while speaking: transcribe(buffer) -> emit PARTIAL (is_final=false, stable id)
          - on finalize: transcribe(buffer) -> emit FINAL (is_final=true, same id)
        -> emit_callback -> main.py WS broadcast -> electron main -> renderer
          -> transcriptStore UPSERTS by id (partial replaced in place, then replaced by final)
          -> TranscriptPanel renders partials grey/italic, finals solid
```

## State machine (per ~0.5s frame)

- **Speech frame:**
  - If idle: open new utterance — new uuid; decide speaker **once** from mic-vs-loopback RMS at onset and hold it for the whole utterance (fixes first-segment mislabel flip).
  - Append frame to buffer; reset silence run.
  - If 1.5s elapsed since last partial: `transcribe(buffer, beam_size=1)` -> emit partial.
  - If partial text ends with sentence punctuation `. ? !`: finalize.
  - If buffer length >= 15s: finalize, then continue with a fresh buffer (speaker carries over).
- **Silence frame:**
  - If an utterance is active: `silence_run += 0.5s`; if `silence_run >= 0.7s`: finalize.
  - Else idle: drop frame, but keep a ~0.2s pre-roll ring so speech onsets are not clipped.
- **Finalize:** trim trailing silence; `transcribe(buffer, beam_size=5)` -> emit `is_final=true` with the same id; clear buffer; `current_id=None`.
- **Session stop mid-utterance:** `flush()` emits the current buffer as a final segment.

## Tunables (hardcoded defaults now; some may move to preferences.json later)

| Name | Default |
|------|---------|
| frame size | 0.5s |
| partial cadence | 1.5s |
| silence-to-finalize | 0.7s |
| max utterance length | 15s |
| pre-roll | 0.2s |
| partial beam_size | 1 |
| final beam_size | 5 |

## Per-file changes

- **`backend/utterance.py` (NEW)** — `UtteranceAssembler`. Pure state machine. Constructor takes injected `transcribe_fn(np.ndarray, beam_size) -> str` and `emit_fn(TranscriptSegment)` so it is fully unit-testable without Whisper. Holds `buffer`, `silence_run`, `current_id`, `speaker`, `last_partial_at`, `utterance_started_offset`, pre-roll ring. `process(...)` drives the state machine; `flush()` for session stop. Trims trailing silence before the final transcribe; drops empty/whitespace results and known hallucination tails (e.g. `// // //`).
- **`backend/vad.py` (MODIFY)** — add `is_speech_frame(frame)` tuned for ~0.5s frames (reuse `get_speech_timestamps`, lower min duration). Keep `reset()`.
- **`backend/audio_capture.py` (MODIFY)** — replace the 3s-grid `_emit_chunks` / `_mix_aligned` tail-peek with contiguous 0.5s frame draining: track read positions (or pop consumed samples) so frames are gap-free and non-overlapping. Emit `(frame, mic_rms, lb_rms)` every 0.5s.
- **`backend/transcriber.py` (MODIFY)** — split model owner from chunk logic. Keep model load + device fallback (CUDA -> CPU int8). Expose `transcribe(buffer, beam_size) -> str`. Worker loop pulls frames and feeds the `UtteranceAssembler` (assembler runs inside the worker thread, preserving the single-thread invariant). Delete the per-chunk emit path.
- **`backend/main.py` (MODIFY)** — wire capture -> frame queue -> worker/assembler -> `emit_callback` -> WS. No protocol change (`is_final` and `id` already in `TranscriptSegment.to_ws_dict`).
- **`src/store/transcriptStore.ts` (MODIFY)** — `addSegment` upserts by id (replace if id exists, else append). Partials and the final share an id.
- **`src/components/TranscriptPanel.tsx` (MODIFY)** — render `is_final === false` grey/italic; finals solid.
- **`backend/models.py`** — no change (`is_final` already present).

## Testing

- **`tests/test_utterance.py`** — inject fake `transcribe_fn` / `emit_fn`; feed synthetic speech/silence frame sequences. Assert: partial cadence; stable id across partial -> final; finalize on 0.7s silence; finalize on punctuation; forced finalize at 15s; speaker held stable across an utterance; `flush()` on stop; empty/hallucination drop.
- **`tests/test_vad.py`** — speech vs silence frame classification.
- Whisper is not run in tests (transcribe is injected). Manual live-run verifies end-to-end.

## Notes / risks

- This venv is torch **CPU-only** (`cuda=False`), so re-transcribing a growing buffer has real cost. Mitigated by the 15s length cap, the 1.5s partial throttle, and `beam_size=1` for partials.
- Repo currently has no tests and is not a git repo. Recommend `git init` before implementation so the spec and changes are tracked. A `tests/` directory will be added.
- The 0.5s-overlap duplication bug and the first-segment-mislabel bug (both noted in prior live-run session) are fixed as a side effect of this redesign.
