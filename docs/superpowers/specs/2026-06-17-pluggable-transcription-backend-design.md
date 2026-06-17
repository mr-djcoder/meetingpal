# Pluggable Transcription Backend (Local / Cloud) — Design

**Date:** 2026-06-17
**Status:** Approved for planning

## Goal

Let the user choose, in Settings, whether transcription runs **locally** (faster-whisper,
default) or in the **cloud** (Deepgram). Same transcript output either way. Also fix the
local partial-transcription waste so the local path is meaningfully faster — especially on
the GPU box the user is building.

## Motivation

Investigation (2026-06-17, this machine: 8 logical cores, no NVIDIA, CPU int8) found:

- A **fixed ~0.5–1s overhead per `transcribe()` call** dominates; number of calls matters
  more than buffer size.
- `tiny.en` ≈ 2× faster than `base.en`; `distil-small.en` is **slower** than `base.en`
  on CPU (`small` > `base`), so distil is not a CPU lever.
- `cpu_threads` tuning is ~a no-op (default ≈ best; 2 and 8 were worse).
- The assembler re-transcribes the **entire growing utterance every partial** → O(n²)
  compute; measured **1.36× waste** on a 12s turn, more on real speech.
- No CUDA here, but a top-tier GPU PC is planned, where float16 `large-v3` /
  `distil-large-v3` run at very high real-time factors. The CUDA path already exists in
  `transcriber.py` but only as a silent CPU fallback.

Conclusion: make the backend pluggable (local CPU/GPU **auto**, or cloud), and remove the
O(n²) waste in the local path.

## Decisions (locked during brainstorming)

1. **Cloud v1 = Deepgram.** $200 free signup credit (no card), true realtime streaming,
   generic interface so Groq/OpenAI can be added later.
2. **Two Deepgram WebSocket connections** — one per source (mic, loopback). Keep
   source-based `You`/`Them` labeling. Ignore Deepgram's acoustic diarization.
3. **Local device is auto, not a user choice.** CPU by default; CUDA used automatically
   when available. Settings only *shows* the active engine/device/model as read-only info.
4. **Privacy:** local is the default and stays fully offline. Cloud is **opt-in** — disabled
   until the user saves a Deepgram key and accepts an "audio will be streamed to Deepgram"
   warning. The `CLAUDE.md` "no audio leaves the machine" rule is rescoped to local mode.
5. **Engine is fixed for a session.** Changing it applies on the next start.
6. **Local streaming fix (O(n²)) is in scope** — it is part of local processing.

## Architecture

One interface, two implementations, selected at session start:

```
TranscriptionBackend (abstract)
    start(session_id: str, started_at: datetime) -> None
    feed(source: "mic" | "loopback", frame: np.ndarray, rms: float) -> None
    stop() -> None
    # emits TranscriptSegment via the existing emit_callback

├─ LocalBackend    → wraps WhisperTranscriber (VAD + assemblers + faster-whisper).
│                    Device auto: try CUDA float16, else CPU int8 (existing logic).
│                    Uses the new streaming assembler (see "Local streaming fix").
└─ DeepgramBackend → opens 2 Deepgram WS connections (mic, loopback); streams PCM;
                     maps Deepgram events to TranscriptSegment.
```

`audio_capture.py` is unchanged: it produces per-source 16kHz mono 0.5s frames and feeds
the **active backend**. Both backends emit the identical `TranscriptSegment` shape, so the
renderer (`transcriptStore`, `TranscriptPanel`), auto-answer, and `storage.py` need no
changes.

### Backend selection

- New prefs (`backend/storage.py` `UserPreferences`, mirrored in `main.py` `PrefsUpdate`
  and `src/types/electron.d.ts`):
  - `transcription_engine: "local" | "cloud" = "local"`
  - `cloud_provider: str = "deepgram"` (future-proofing; only deepgram implemented)
- `main.py` constructs `LocalBackend` or `DeepgramBackend` at session start based on the
  pref, and wires the same `emit_callback` either way.

## Data flow

**Local:** capture → frames → `LocalBackend` (VAD → streaming assembler → faster-whisper,
device auto) → segments → existing WS push to renderer.

**Cloud:** capture → frames → `DeepgramBackend` → one Deepgram WS per source
(`encoding=linear16`, `sample_rate=16000`, `channels=1`, `interim_results=true`,
endpointing on, diarize off, model `nova-2` or newer) → Deepgram JSON events mapped to
`TranscriptSegment`:
- interim result → `is_final=false` (live partial)
- `is_final`/`speech_final` → `is_final=true`
- `speaker` from the connection's source (mic→`You`, loopback→`Them`)
- one `id` per utterance (new uuid at utterance start, reused across that utterance's
  interims and final), matching how local segments upsert in the store.

## Local streaming fix (LocalAgreement-2)

Replaces the re-transcribe-whole-buffer logic in `backend/utterance.py`.

- Keep the utterance state machine (silence finalize, max length, You/Them).
- Track a **committed prefix** (locked text) and a small trailing **uncommitted audio
  window**. Each partial transcribes only the trailing window, not the whole utterance.
- **LocalAgreement-2:** when two consecutive partials agree on their leading words, commit
  those words — move them into the prefix and drop their audio from the window. Only the
  still-changing tail is re-decoded.
- The emitted partial = committed prefix + current tail hypothesis.
- Finalize emits committed prefix + final tail. No full beam-5 pass over the entire
  utterance.

Net effect: each second of audio is transcribed ~once instead of O(n²). Largest relative
win on GPU (per-audio cost dominates) and on long turns / real speech.

DeepgramBackend is unaffected — Deepgram streams incrementally on its own.

## Overlapping speech / crosstalk

Splitting by source (mic→`You`, loopback→`Them`) over two independent Deepgram
connections handles people talking over each other **natively**: each connection has its
own decoder, so simultaneous speech produces a `You` final and a `Them` final in parallel,
with overlapping `session_offset_seconds`. The renderer shows both lines, ordered by
offset. This is strictly better than a single mixed stream + acoustic diarization, which
would have to untangle overlapping voices into Speaker 0/1 — the case acoustic diarization
handles worst.

The real limitation is **acoustic bleed**: on speakers (not headphones), the mic physically
picks up the other party's voice coming out of the speakers, so their words can be
transcribed a second time as `You`. This is **not new to the cloud path** — the current
local mic/loopback energy heuristic has the identical issue.

Handling this round: **document it and recommend headphones.** Headphones eliminate the
bleed entirely. No code work for bleed in this project.

Future options (not in scope): a cross-source energy-dominance gate (suppress the quieter
source's frames during clear overlap), or real acoustic echo cancellation on mic capture.

## Key storage

- Deepgram key in **keytar** under account `deepgram-api-key` (same pattern as
  `anthropic-api-key`, `gemini-api-key`).
- New IPC + sidecar endpoint `POST /api/key/deepgram`; key is synced to the sidecar on
  startup (transcription is server-side, like the auto-answer keys).
- Key is never written to disk, logs, or frontend state.

## Settings UI

In `src/components/Settings.tsx`:

- **Engine** radio: `Local` / `Cloud`.
- When **Local** selected → read-only info line:
  `Engine: Local · Device: CPU` (or `GPU (CUDA)`) · `Model: base.en`.
  Device/model come from a sidecar status field.
- When **Cloud** selected:
  - Provider: Deepgram (only option for now).
  - Deepgram API key field (saved via keytar).
  - **Warning gate:** "Audio will be streamed to Deepgram for transcription." Cloud cannot
    be enabled until a key is saved and the warning is acknowledged.

## Error handling

- **Cloud, no key:** session start blocked with a clear message. Never silently stream
  audio to nowhere.
- **Deepgram WS error/disconnect:** a few reconnect attempts; if still failing, surface a
  recoverable sidecar error **and auto-fall back to `LocalBackend`** for the remainder of
  the session so transcription never just dies. The fallback is shown in the error banner.
- **Local:** unchanged — existing CUDA→CPU model fallback stays.

## Testing

- **Interface contract test:** both backends satisfy `TranscriptionBackend`
  (`start`/`feed`/`stop`, emits `TranscriptSegment`).
- **LocalBackend:** existing `transcriber` / `utterance` tests keep passing (wrap, don't
  rewrite the model layer).
- **Streaming assembler:** unit tests for LocalAgreement-2 — feed scripted partial
  hypotheses, assert committed prefix grows correctly, tail re-decodes only, finalize emits
  full text, and that work per utterance is bounded (no full re-transcribe).
- **DeepgramBackend:** **mock WebSocket**, feed canned Deepgram JSON events, assert
  `TranscriptSegment` mapping (speaker by source, interim→partial, final→final, text,
  stable id per utterance). No live API in unit tests.
- **Device-info detector:** returns `"cpu"` / `"cuda"` correctly for the status readout.
- **Privacy gate:** cloud engine cannot be enabled without a saved key + acknowledged
  warning.

## Out of scope

- Groq / OpenAI cloud providers (interface leaves room; not implemented in v1).
- Using Deepgram's acoustic diarization (we keep source-based You/Them).
- User-selectable local device or local model picker (device is auto; model stays as the
  current default, surfaced read-only).
