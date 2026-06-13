# Research: MeetingPal Core App

**Branch**: `001-meetingpal-core-app` | **Date**: 2026-03-12

---

## Decision 1: WASAPI Loopback Audio Capture Library

**Decision**: Use **PyAudioWPatch** (not standard sounddevice or PyAudio) for WASAPI loopback capture.

**Rationale**: Standard `sounddevice` has no native WASAPI loopback support. Standard `PyAudio` requires PortAudio which also lacks loopback. `PyAudioWPatch` is a maintained PortAudio fork explicitly built for Windows WASAPI loopback — it exposes `get_default_wasapi_loopback()` and `get_loopback_device_info_generator()`. Two concurrent streams are opened: one loopback at 44.1kHz stereo, one microphone at 16kHz mono. The loopback stream is downsampled to 16kHz and converted to mono using `scipy.signal.resample`, then mixed at 0.5 + 0.5 scaling to prevent clipping.

**Alternatives considered**:
- `sounddevice` — No loopback support without C extensions
- Standard `PyAudio` — No WASAPI loopback without patched PortAudio
- VB-Audio Virtual Cable — Third-party driver install required (violates spec FR-002)

**Key implementation notes**:
- WASAPI loopback devices are virtual input devices; treat them as input even though they capture output
- WASAPI shared mode only (exclusive mode doesn't support loopback) — ~22ms latency, acceptable for transcription
- Use blocking `stream.read()` in a dedicated thread, not callbacks, to avoid overload
- Common pitfall: some budget audio cards don't expose loopback endpoints — show clear error in onboarding Step 2

---

## Decision 2: faster-whisper Threading & Real-Time Strategy

**Decision**: Single background worker thread with a `queue.Queue` feeding one `WhisperModel` instance. GPU (CUDA float16) when available, CPU (int8) as fallback.

**Rationale**: `faster-whisper` / CTranslate2 is NOT thread-safe for concurrent `transcribe()` calls on the same model instance. A single producer-consumer pattern (audio capture → queue → transcriber thread) is safe, simple, and matches Constitution Principle V (simplicity). CTranslate2 releases the Python GIL during inference, so the FastAPI event loop is not blocked.

**Key implementation notes**:
- `WhisperModel("base.en", device="cuda", compute_type="float16")` for GPU; `WhisperModel("base.en", device="cpu", compute_type="int8")` for CPU
- `model.transcribe()` returns **only final segments** — no interim/partial results natively
- For near-real-time "typing" feel, implement overlap: each 3s chunk shares 0.5s with the next via a rolling deque buffer; new confirmed segments are emitted, previously seen segments are deduplicated
- Recommended `transcribe()` params for real-time: `beam_size=5`, `vad_filter=True`, `condition_on_previous_text=True`, `temperature=0.0`, `word_timestamps=False`
- Model load time: base.en ~3-5s cold start; subsequent restarts < 1s (cached in `%USERPROFILE%\.cache\huggingface\hub\`)

**Alternatives considered**:
- `whisper_streaming` library — More complex, additional dependency, overkill for 2-speaker meeting use case
- Multiple model instances — Higher memory, unnecessary for single session

---

## Decision 3: Voice Activity Detection

**Decision**: Use **Silero VAD** as a gate before faster-whisper. Batch-process each 3-second chunk with `get_speech_timestamps()`.

**Rationale**: Silero VAD is ~1-2MB, CPU-optimized, <1ms per chunk, and integrates as a one-call check. Using batch mode (not VADIterator) on complete 3-second chunks is simpler and sufficient — we don't need frame-level streaming detection since chunks are already pre-buffered.

**Key implementation notes**:
- `torch.set_num_threads(1)` is critical for CPU performance
- Input: float32 numpy array at 16kHz, values in [-1.0, 1.0]
- Threshold 0.5 (default) works well; lower to 0.35 if speech is being missed
- Call `reset_states()` between sessions (not between chunks within a session — it's stateful)
- If `get_speech_timestamps()` returns empty list → skip chunk; otherwise → send to faster-whisper

**Alternatives considered**:
- faster-whisper's built-in `vad_filter=True` — Also uses Silero internally, but processing happens inside transcribe(); using it as an external gate allows measuring silence rate and providing audio level feedback to the waveform visualizer

---

## Decision 4: Speaker Diarization Strategy

**Decision**: Two-phase hybrid approach: **(Phase 1 MVP)** speaker detection via separate audio track analysis (mic vs. loopback source tracking) with simple heuristic labeling; **(Phase 2)** post-hoc speaker embedding clustering with SpeechBrain ECAPA-TDNN.

**Rationale**: `pyannote.audio` in real-time streaming mode requires GPU for <5s latency and mandates a HuggingFace token (user friction). It cannot reliably process 3-5 second chunks. For a 2-speaker meeting, a simpler and more reliable approach leverages the fact that we know the audio *source* — microphone audio = "You", loopback audio = "Them".

**Phase 1 implementation** (mic/loopback source tracking):
- Keep mic and loopback streams separate through VAD; don't merge until transcription
- Run VAD on each channel independently: if mic energy is dominant → "You", if loopback energy is dominant → "Them"
- This works for meetings where speakers don't talk over each other (the common case)
- If both channels have energy simultaneously → label as "You" (conservative)

**Phase 2 implementation** (periodic re-labeling):
- Every 30s, extract speaker embeddings from accumulated 5-second speech windows using SpeechBrain `spkrec-ecapa-voxceleb`
- Apply `AgglomerativeClustering(n_clusters=2)` to assign speaker 0 / speaker 1
- Map: speaker associated with more mic-dominant windows → "You"
- Retroactively update existing transcript segments' speaker labels

**Alternatives considered**:
- `pyannote.audio` batch — Too slow for real-time, requires HF token, overkill for 2-speaker case
- `diart` — Real-time pyannote wrapper but GPU-heavy and still requires HF token
- Picovoice Falcon — Commercial, paid per-use

---

## Decision 5: Electron ↔ Python Sidecar IPC

**Decision**: `spawn()` with `stdio: 'pipe'`, hardcoded port 8001, HTTP GET `/health` readiness polling, WebSocket for streaming, REST for request/response.

**Rationale**: `spawn()` is the correct Node.js API for long-lived child processes — no output buffering limit, streaming stdout/stderr. Hardcoded port 8001 is simpler than dynamic discovery (no port file needed). Health polling at 500ms intervals with 30-retry limit (15s timeout) gives the sidecar enough time to load models.

**IPC layers** (no shortcuts or violations of the context bridge rule):
1. Renderer → preload's `contextBridge` → IPC message → main process
2. Main process → HTTP POST / WebSocket → Python sidecar (localhost:8001)
3. Python sidecar → WebSocket push → main process → `webContents.send()` → preload → renderer

**Key implementation notes**:
- Set `PYTHONUNBUFFERED=1` in sidecar env so Python `print()` lines stream in real-time to Electron's log
- `app.on('before-quit')`: close WebSocket, send SIGTERM to sidecar, wait for `exit` event (3s), then SIGKILL fallback
- Pass API key via `Authorization: Bearer <key>` HTTP header on each request — NOT in env vars (env vars are visible in process listings)
- Sidecar crash restart: up to 3 restarts with 2s delay; after limit, show error in UI

---

## Decision 6: PyInstaller Bundling Strategy

**Decision**: Single-file `--onedir` mode (not `--onefile`) with a `meetingpal.spec` file. Whisper base.en model weights downloaded at first startup and cached in `%APPDATA%\MeetingPal\models\`.

**Rationale**: `--onedir` unpacks once on install rather than on every launch (avoiding slow temp-dir extraction). Model weights are ~150MB — bundling in the installer is possible but inflates download size significantly. First-run download with a progress indicator is a better UX.

**Critical hidden imports** for this stack:
- `uvicorn.logging`, `uvicorn.loops.auto`, `uvicorn.protocols.http.auto`, `uvicorn.protocols.websockets.auto`
- `starlette.middleware.cors`
- `ctranslate2` (CTranslate2 C++ bindings used by faster-whisper)
- `pyaudiowpatch` (PyAudioWPatch internals)
- `anthropic.types`, `anthropic._streaming`

**Electron Forge `extraResources`** configuration:
- `from: './dist/meetingpal'` → `to: 'sidecar'`
- `asarUnpack: ['**/sidecar/**']` — required so `spawn()` can find and execute the .exe

**Alternatives considered**:
- `--onefile` PyInstaller — Slow cold start (extracts to temp on every launch), worse UX
- Bundle model weights in installer — ~250MB installer vs ~100MB + first-run download

---

## Decision 7: keytar — API Key Storage

**Decision**: `keytar` v7 in Electron main process only. Service: `'MeetingPal'`, account: `'anthropic-api-key'`. API key passed to Python sidecar via `Authorization: Bearer` header, never via environment variable.

**Rationale**: Windows Credential Manager via keytar is the secure, user-transparent way to store secrets on Windows (visible in Credential Manager UI). Electron main process has full OS access; renderer must use context bridge. Rebuilding keytar for Electron via `@electron/rebuild` is the standard workflow.

**Key implementation notes**:
- `postinstall` script: `electron-rebuild -w keytar -f`
- Webpack `externals: { keytar: 'commonjs keytar' }` to prevent ASAR packaging the native .node file
- On sidecar startup: Electron main retrieves key from keytar, holds it in memory, injects as header per request

**Alternatives considered**:
- `safeStorage` (Electron built-in) — Newer alternative, but keytar is more battle-tested for Windows Credential Manager specifically and shows up visibly in Credential Manager UI (user trust signal)
- Environment variable — Insecure (visible in `ps aux` / Task Manager)

---

## Decision 8: Claude API Streaming in FastAPI

**Decision**: FastAPI `StreamingResponse` with `text/event-stream` content type using Anthropic SDK's `.stream()` context manager. React frontend consumes via `fetch` + `ReadableStream` (not `EventSource`, which doesn't support POST with custom headers).

**Rationale**: SSE over HTTP is the simplest unidirectional streaming pattern. The `fetch` + `ReadableStream` approach gives full control over headers (needed for `Authorization`) while EventSource only supports GET without headers.

**Context window management**:
- System prompt contains the meeting transcript formatted as `[HH:MM AM/PM] You: "..."` / `[HH:MM AM/PM] Them: "..."`
- Sliding window: trim oldest segments from system prompt when token count (measured via `client.messages.count_tokens()`) exceeds 60K tokens (leaving 20K for conversation history + response)
- Multi-turn chat history passed in `messages[]` array, pruned separately when it exceeds 20K tokens

**MeetingPal persona** (system prompt, per spec):
> "You are MeetingPal, a world-class executive consultant and strategic advisor who has been silently listening to a live meeting. You have full context of everything said so far, provided in the transcript below. Your job is to help the user — a busy professional — in real time during the meeting. Be concise, sharp, and immediately useful. Prioritize insights from the transcript over general knowledge. Never mention that you are an AI unless directly asked. Respond as a trusted advisor would in a 1:1 chat."

**Alternatives considered**:
- WebSocket for Claude responses — More complex, bi-directional overhead not needed for this use case
- EventSource — Cannot send POST body or custom headers
