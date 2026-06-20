# Dual-Stream Transcription — Design Spec

**Date:** 2026-06-16
**Status:** Approved (architecture + key decisions approved during brainstorming; implementing autonomously, flagged for user review)
**Problem:** The user's own voice transcribes worse than the other party's. Today mic + loopback are mixed into one mono stream at half gain (`mic*0.5 + loopback*0.5`) and fed to a single assembler. The mic (acoustic, noisy, quieter) loses to the loopback (clean, full-level digital stream) in that shared input, and speaker labels come from an RMS-energy guess that mislabels.

## Goal

Transcribe the **microphone and the WASAPI loopback as two independent streams**, each at full level, each with a fixed speaker label. This improves the user's-voice recognition (no more half-gain mixing) and makes `You`/`Them` exact (source-based, not RMS heuristic).

## Approved decisions

- **Both at once:** independent assemblers per source — a `You` line and a `Them` line can grow and finalize concurrently (captures crosstalk).
- **Un-mix only:** transcribe the mic at full level; no normalization / noise-reduction in this change (no new dependencies). Normalization is a future follow-up.

## Architecture

Two assemblers, **one** Whisper model, **one** worker thread (preserves the single-model thread-safety invariant). A silent source is VAD-gated, so it costs only cheap VAD, not transcription — load only doubles while both speak.

```
mic thread     -> mic deque  --\
loopback thread -> lb deque  --/
   _emit_chunks drains a 0.5s frame from EACH source INDEPENDENTLY (no mixing)
     -> chunk_callback('mic',      mic_frame, mic_rms)
     -> chunk_callback('loopback', lb_frame,  lb_rms)
       -> transcriber.enqueue(source, frame, rms)  -> single queue
         -> ONE worker thread:
              source 'mic'      -> mic_vad.is_speech_frame(frame) -> mic_assembler.process(...)   speaker "You"
              source 'loopback' -> lb_vad.is_speech_frame(frame)  -> lb_assembler.process(...)    speaker "Them"
              both assemblers transcribe via the shared self.transcribe(buffer, beam)  [serialized by the single worker]
           -> emit_callback(seg) -> WS -> renderer upserts by id  (You + Them lines independent)
```

## Component changes

### `backend/audio_capture.py`
- `_emit_chunks` no longer mixes. It drains each source's deque **independently**: whenever a source's deque has >= `FRAME_SAMPLES` (0.5s), pop one frame and emit it tagged with its source. Mic and loopback emit on their own schedules (one can be silent while the other is active).
- `chunk_callback` signature becomes `(source: Literal["mic","loopback"], frame: np.ndarray, rms: float)`.
- The `mix_frame` function and its uses are removed (un-mixed now). `get_mic_rms` / `get_loopback_rms` stay (used by the audio-level visualizer, unchanged).
- Factor a tiny pure helper `drain_frame(buffer: deque, n: int) -> np.ndarray | None` (pop `n` samples as a float32 array, or `None` if fewer than `n` available) so the drain logic is unit-testable without PyAudio.

### `backend/utterance.py`
- `UtteranceAssembler` gains a constructor arg **`speaker: Literal["You","Them"]`** (fixed for the assembler's lifetime).
- `process(...)` drops the `mic_rms` / `lb_rms` params — new signature `process(frame, is_speech, wall_clock, offset)`. `_start_utterance()` no longer decides a speaker (it's fixed); it just opens a new id + resets the buffer.
- `_emit_segment` sets `audio_source = "mic" if self._speaker == "You" else "loopback"` (was hardcoded `"mixed"`).
- All existing tuning (0.5s frames, 1.5s partial cadence, 4.0s silence-finalize, 15s cap, no punctuation split) is unchanged.

### `backend/transcriber.py`
- `enqueue(source, frame, rms)` — queue tuples carry the source.
- `start()` creates **two** assemblers: `self._mic_assembler = UtteranceAssembler(self.transcribe, emit_fn, session_id, speaker="You")` and `self._lb_assembler = UtteranceAssembler(..., speaker="Them")`, and **two** `SileroVAD` instances (`self._mic_vad`, `self._lb_vad`) so VAD state doesn't cross-contaminate.
- `_process_chunk(source, frame, rms, ...)` routes by source: pick the matching VAD + assembler, `is_speech = vad.is_speech_frame(frame)`, `assembler.process(frame, is_speech, wall_clock, offset)`.
- `stop()` flushes BOTH assemblers (after the worker has joined — the existing post-join-flush thread-safety fix is kept).
- The single-VAD lazy load in `load_model` becomes two VAD instances. `transcribe(buffer, beam)` is unchanged and shared by both assemblers (serialized by the single worker thread).
- The old `diarizer.get_speaker` energy heuristic is no longer used; remove its import/use from the transcriber. (`backend/diarizer.py` may be left unused — deleting it is out of scope.)

### `backend/main.py`
- `_chunk_cb` becomes `def _chunk_cb(source, frame, rms): transcriber.enqueue(source, frame, rms)`. Nothing else changes — the WS protocol, session-segment upsert, and audio-level task are untouched.

## Data flow / concurrency

Capture interleaves `('mic', ...)` and `('loopback', ...)` frames into the single queue. The single worker dequeues them in order and calls the matching assembler's `process`. Each assembler keeps its own buffer/state and shares the one Whisper model; transcription is therefore serialized (no concurrent model access). When both speak, two transcribe calls per partial tick run back-to-back — acceptable on the CPU model per the "both at once" decision.

## Testing

- **`tests/test_utterance.py` (update):** the `build()` helper passes `speaker=`; `feed()` / `process()` calls drop the rms args. Replace the two RMS-based speaker tests with: an assembler built `speaker="You"` emits `You`; one built `speaker="Them"` emits `Them`; `audio_source` reflects the source. All other assembler behavior tests stay.
- **`tests/test_audio_capture.py` (update):** remove the `mix_frame` tests; add tests for the new pure `drain_frame(deque, n)` helper (returns `None` when short; pops exactly `n` samples as float32; advances the deque).
- **VAD test** unchanged.
- **Integration / live (manual):** speak into the mic and play audio through the speakers; confirm the user's voice transcribes noticeably better than before (full level), `You`/`Them` are correct and never flip mid-utterance, and simultaneous speech yields concurrent `You` + `Them` lines.

## Out of scope (future)

- Mic normalization / AGC / noise reduction (the "improve the mic signal itself" option — deferred).
- Two Whisper models / parallel transcription threads (rejected — doubles RAM for little gain on CPU).
- Removing the now-unused `backend/diarizer.py`.
