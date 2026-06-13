# Tasks: MeetingPal Core App

**Input**: Design documents from `/specs/001-meetingpal-core-app/`
**Prerequisites**: plan.md ✓, spec.md ✓, research.md ✓, data-model.md ✓, contracts/backend-api.md ✓, quickstart.md ✓

**Tests**: Not requested — no test tasks generated.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (US1–US5)
- Exact file paths are included in all task descriptions

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project scaffolding, dependency installation, tooling configuration. No feature logic — just a runnable skeleton.

- [X] T001 Initialize Node.js project: create `package.json` with Electron 30, React 18, TypeScript 5, TailwindCSS 3, Zustand 4, Vite, `@electron-forge/cli`, `@electron-forge/maker-squirrel`, `keytar`, `@electron/rebuild` — set `postinstall` to `electron-rebuild -w keytar -f`
- [X] T002 Create TypeScript configs: `tsconfig.json` (strict mode, `noImplicitAny`, `moduleResolution: bundler`) and `tsconfig.electron.json` (target Node, CJS module for main process)
- [X] T003 [P] Create `vite.config.ts` for React renderer with TailwindCSS plugin; create `tailwind.config.ts` with dark mode `class` strategy; create `src/index.css` with `@tailwind` directives
- [X] T004 [P] Create `forge.config.ts`: Squirrel maker for win32/x64 only; `extraResources` copying `dist/meetingpal/` → `sidecar/`; `asarUnpack: ['**/sidecar/**']`; no macOS/Linux makers
- [X] T005 [P] Create `requirements.txt` with all Python dependencies: `pyaudiowpatch`, `faster-whisper`, `silero-vad`, `speechbrain`, `scikit-learn`, `scipy`, `numpy`, `anthropic`, `fastapi`, `uvicorn[standard]`, `torch`, `torchaudio`
- [X] T006 [P] Create `meetingpal.spec` (PyInstaller): `--onedir` mode, `Analysis(['backend/main.py'], ...)` with hidden imports for uvicorn, starlette, ctranslate2, pyaudiowpatch, anthropic, silero_vad, speechbrain; `EXE(console=False, name='meetingpal')`
- [X] T007 [P] Create folder skeleton: `electron/`, `src/components/`, `src/store/`, `src/hooks/`, `src/onboarding/steps/`, `backend/` — all empty `__init__.py` / index files; create `src/App.tsx` shell

**Checkpoint**: `npm install` and `pip install -r requirements.txt` both complete without errors. Folder structure matches plan.md.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure every user story depends on — sidecar lifecycle, IPC bridge, FastAPI skeleton, preferences storage, Zustand stores, WebSocket hook. **No user story work begins until this phase is complete.**

**⚠️ CRITICAL**: All Phase 3+ tasks depend on this phase being complete.

- [X] T008 Implement `backend/storage.py`: `UserPreferences` dataclass with all fields from data-model.md; `load_preferences()` reading `%APPDATA%/MeetingPal/preferences.json`; `save_preferences()` writing atomically; default values as specified
- [X] T009 [P] Implement `backend/main.py`: FastAPI app with `lifespan` context manager; register all route modules; `GET /health` returning `{"status":"healthy","model_loaded":bool}`; uvicorn startup on port from CLI arg; `PYTHONUNBUFFERED=1` stdout flush on all log lines
- [X] T010 [P] Implement `GET /api/preferences` and `PUT /api/preferences` (partial update) in `backend/main.py` using `storage.py`; implement `POST /api/key` endpoint that delegates to a `KeyManager` stub (to be wired to keytar via Electron IPC — Python side just accepts and stores the key in memory for the session)
- [X] T011 [P] Implement `GET /api/devices` in `backend/audio_capture.py`: enumerate PyAudioWPatch devices; return `AudioDevice[]` JSON per contracts/backend-api.md; mark `is_default` correctly for both mic and loopback types
- [X] T012 Implement `electron/sidecar.ts`: `SidecarManager` class — `spawn()` using Node `child_process.spawn()` with `stdio:'pipe'`; health-poll loop (500ms, 30 retries); pipe stdout/stderr to `%APPDATA%/MeetingPal/logs/sidecar.log`; `shutdown()` sends SIGTERM, waits for `exit` event (3s), then SIGKILL fallback; crash restart up to 3 times with 2s delay
- [X] T013 Implement `electron/main.ts`: `app.on('ready')` → `SidecarManager.spawn()` → await health → `createWindow()`; IPC handlers for all `window.electronAPI` methods per contracts/backend-api.md; `app.on('before-quit')` calls `SidecarManager.shutdown()`; keytar `get/set/delete` wired to `ipcMain.handle`; inject API key as `Authorization: Bearer` header on all `/api/*` fetch calls
- [X] T014 Implement `electron/preload.ts`: `contextBridge.exposeInMainWorld('electronAPI', {...})` exposing all methods from the `ElectronAPI` interface in contracts/backend-api.md — `getDevices`, `startSession`, `stopSession`, `askQuestion`, `getPreferences`, `setPreferences`, `setApiKey`, `hasApiKey`, `onTranscriptSegment`, `onAudioLevel`, `onAiToken`, `onAiDone`, `onError`, `copyTranscript`, `exportTranscript`; all real-time listeners return a cleanup function that calls `ipcRenderer.removeListener`
- [X] T015 Implement `src/store/transcriptStore.ts`: Zustand store with `sessionId`, `isRecording`, `sessionStartedAt`, `segments: TranscriptSegment[]`; actions `startSession`, `stopSession`, `addSegment`, `clearSession`; `TranscriptSegment` TypeScript interface matching data-model.md
- [X] T016 [P] Implement `src/store/chatStore.ts`: Zustand store with `messages: ChatMessage[]`, `isStreaming`, `streamingContent`; actions `addUserMessage`, `appendToken`, `finalizeAssistantMessage`, `clearHistory`; `ChatMessage` TypeScript interface matching data-model.md
- [X] T017 Implement `src/hooks/useWebSocket.ts`: `useWebSocket()` hook — calls `window.electronAPI.onTranscriptSegment` and `window.electronAPI.onAudioLevel` on mount; dispatches to `transcriptStore.addSegment` and an `audioLevel` state atom; returns cleanup on unmount; handles `error` events by surfacing to a toast/banner

**Checkpoint**: `python backend/main.py --port 8001` starts and `GET http://localhost:8001/health` returns `{"status":"healthy","model_loaded":false}`. `npm run dev` opens an Electron window (blank shell). All IPC handlers registered.

---

## Phase 3: User Story 1 — Live Transcription During a Meeting (Priority: P1) 🎯 MVP

**Goal**: User clicks Start Recording → WASAPI loopback + mic captured → Silero VAD gates silence → faster-whisper transcribes → labeled segments (You/Them) appear in TranscriptPanel within 4 seconds.

**Independent Test**: Open app, click Start Recording, speak for 10 seconds; verify labeled transcript lines appear in the left panel within 4s. No AI panel needed.

- [X] T018 [US1] Implement audio mixing and rolling buffer in `backend/audio_capture.py`: open PyAudioWPatch loopback stream (44.1kHz stereo) and mic stream (16kHz mono) concurrently in separate threads; resample loopback to 16kHz mono using `scipy.signal.resample`; mix at `0.5 * mic + 0.5 * loopback` with `np.clip`; maintain separate `mic_buffer` and `loopback_buffer` deques for energy monitoring; push mixed audio into `RollingBuffer` deque (`maxlen = 3.5s * 16000 = 56000 samples`); on each full 3s chunk, advance by 2.5s (0.5s overlap)
- [X] T019 [P] [US1] Implement `backend/vad.py`: load Silero VAD model with `torch.set_num_threads(1)`; `is_speech(chunk: np.ndarray) -> bool` using `get_speech_timestamps(chunk, model, sampling_rate=16000, threshold=0.5)`; return `True` iff result is non-empty; expose `reset()` method for between-session cleanup
- [X] T020 [P] [US1] Implement speaker heuristic in `backend/diarizer.py`: `get_speaker(mic_rms: float, loopback_rms: float) -> Literal["You","Them"]` — return `"You"` if `mic_rms >= loopback_rms`, else `"Them"`; compute RMS as `np.sqrt(np.mean(buf**2))` over the last 3s of each separate buffer
- [X] T021 [US1] Implement `backend/transcriber.py`: `WhisperTranscriber` class — load `WhisperModel(model_name, device="cuda", compute_type="float16")` with CPU int8 fallback; single `threading.Thread` worker consuming `queue.Queue[np.ndarray]`; for each chunk: check `vad.is_speech()` gate, transcribe with `beam_size=5, vad_filter=True, condition_on_previous_text=True, temperature=0.0`; deduplicate against last-seen segment text; build `TranscriptSegment` dict (speaker, wall_clock_time, session_offset, text, is_final, confidence); call `emit_callback(segment)`; expose `load_model(name)`, `start()`, `stop()`, `enqueue(chunk)` methods
- [X] T022 [US1] Implement `POST /api/session/start` and `POST /api/session/stop` in `backend/main.py`: start creates `RecordingSession`, starts `AudioCapture` and `WhisperTranscriber`, returns session JSON; stop halts capture, flushes queue, updates session `stopped_at`; enforce single-session-at-a-time with 409 response
- [X] T023 [US1] Implement WebSocket `/ws` endpoint in `backend/main.py`: accept connections, register in `connected_websockets` set; `emit_callback` from transcriber broadcasts `TranscriptSegment` JSON to all connected sockets; emit `AudioLevelFrame` at ~10fps from separate 100ms asyncio task reading mic/loopback RMS; broadcast `session_status` on start/stop; remove socket from set on disconnect
- [X] T024 [US1] Implement `src/components/TranscriptPanel.tsx`: scrollable feed of `TranscriptSegment[]` from `transcriptStore`; each row: speaker label badge (blue for "You", gray for "Them"), formatted timestamp, text; `useEffect` scroll-to-bottom on segment append unless user has scrolled up (detect with `scrollTop + clientHeight < scrollHeight - 20`); "Copy Transcript" and "Export" button stubs (wired in US5); meeting timer display from `sessionStartedAt`; recording indicator red dot when `isRecording`
- [X] T025 [P] [US1] Implement `src/components/AudioVisualizer.tsx`: receives `{ micLevel: number, loopbackLevel: number }` props; renders two animated bar charts (or waveform lines) using CSS transforms; collapsible toggle; smooth level interpolation using `requestAnimationFrame`; hidden when not recording
- [X] T026 [US1] Implement `src/components/TopBar.tsx`: MeetingPal logo + name; Start/Stop Recording toggle button (calls `window.electronAPI.startSession` / `stopSession`); updates `transcriptStore` on response; platform selector dropdown (Google Meet / Zoom / Teams / Other — label only, no functional effect); settings gear icon (opens Settings modal, wired in US4); API key status indicator (green dot if `hasApiKey()` returns true, red if false)
- [X] T027 [US1] Implement `src/hooks/useRecording.ts`: `useRecording()` hook returning `{ isRecording, startRecording, stopRecording, duration }`; `duration` is a `useInterval`-driven counter from `sessionStartedAt`; delegates to `window.electronAPI.startSession` / `stopSession` and dispatches to `transcriptStore`
- [X] T028 [US1] Implement `src/App.tsx` MainLayout: resizable split-pane using CSS `grid` with `grid-template-columns: 60fr 40fr`; render `<TopBar />`, `<TranscriptPanel />`, `<AIChatPanel />` (placeholder), `<AudioVisualizer />`; wire `useWebSocket()` at root level so all stores receive events; apply dark/light theme class to `<html>` from preferences

**Checkpoint**: `npm run dev` → click Start Recording → speak for 10s → labeled "You" / "Them" transcript rows appear within 4 seconds. AudioVisualizer bars respond. Stop Recording halts capture.

---

## Phase 4: User Story 2 — AI Q&A Against Live Meeting Context (Priority: P1)

**Goal**: User types a question in the right panel → Claude streams a response grounded in the meeting transcript → response appears token-by-token within 3s.

**Independent Test**: With a pre-seeded transcript in `transcriptStore`, type "What were the action items?" and press Send; verify tokens stream into the chat panel and reference transcript content.

- [X] T029 [US2] Implement `backend/claude_client.py`: `ClaudeClient` class — `ask(question: str, segments: list, history: list, api_key: str, model: str)` as an async generator yielding SSE events; build system prompt from MeetingPal persona + transcript formatted as `[HH:MM AM/PM] You/Them: "..."` using `wall_clock_time`; trim transcript to ≤60K tokens using `anthropic.count_tokens()` sliding-window (drop oldest segments); trim history to ≤20K tokens (drop oldest exchange pairs); call `client.messages.stream(model, max_tokens=2048, system, messages)` using `.stream()` context manager; yield `{"type":"content_delta","text":token}` per token; yield `{"type":"message_stop","stop_reason":..., "input_tokens":..., "output_tokens":...}` on completion; yield `{"type":"error","message":...}` on exception
- [X] T030 [US2] Implement `POST /api/ask` in `backend/main.py`: extract `question`, `session_id`, `claude_model` from body; extract API key from `Authorization: Bearer` header; retrieve `session.segments` and `session.chat_messages`; call `ClaudeClient.ask()` as async generator; return `StreamingResponse` with `media_type="text/event-stream"`; after stream completes, append user+assistant `ChatMessage` to session history; return 401 if no API key, 404 if session not found
- [X] T031 [US2] Implement `src/components/AIChatPanel.tsx`: chat message list rendering `chatStore.messages` (user messages right-aligned, assistant left-aligned); streaming assistant message appends to `streamingContent` via `appendToken`; `finalizeAssistantMessage()` on `message_stop` event; input textarea with `Ctrl+Enter` keyboard shortcut; Send button; suggested prompt chips row: "Summarize so far", "What are the action items?", "Catch me up — I zoned out", "What was just decided?", "Draft a follow-up email" — each chip populates input and auto-submits; "MeetingPal AI" header with small badge; scrolls to bottom on new message
- [X] T032 [US2] Implement AI token streaming in `src/hooks/useWebSocket.ts` (extend existing hook): wire `window.electronAPI.onAiToken(token => chatStore.appendToken(token))` and `window.electronAPI.onAiDone(() => chatStore.finalizeAssistantMessage())`; Electron main process connects SSE response from `/api/ask` and emits tokens to renderer via `webContents.send('ai-token', text)` and `webContents.send('ai-done', summary)`
- [X] T033 [US2] Wire `AIChatPanel` `handleSend()`: call `chatStore.addUserMessage(question)`, then `window.electronAPI.askQuestion(question, claudeModel)`; disable input while `chatStore.isStreaming`; show error banner if `onError` fires during stream; replace `<AIChatPanel />` placeholder in `App.tsx` MainLayout

**Checkpoint**: With recording active and transcript populated, type "Summarize so far" in chat panel and press Enter; Claude response streams token-by-token referencing actual transcript content.

---

## Phase 5: User Story 3 — First-Run Onboarding Wizard (Priority: P2)

**Goal**: On first launch (no API key stored), display a 5-step wizard guiding the user through API key entry, audio device confirmation, audio test, demo, and ready screen. Entire flow completable in under 5 minutes.

**Independent Test**: Clear `%APPDATA%/MeetingPal/preferences.json` and delete keytar credential; relaunch app; complete all 5 wizard steps; verify main interface appears and `preferences.onboarding_completed === true`.

- [X] T034 [US3] Update `src/App.tsx` routing: on mount, call `window.electronAPI.hasApiKey()` and read `preferences.onboarding_completed`; if either is false, render `<OnboardingWizard onComplete={() => setOnboardingDone(true)} />`; otherwise render `<MainLayout />`
- [X] T035 [P] [US3] Implement `src/onboarding/steps/ApiKeyStep.tsx`: password input field for Anthropic API key; "Get one at console.anthropic.com" hyperlink (opens in default browser via `shell.openExternal`); validate non-empty and `sk-ant-` prefix on submit; call `window.electronAPI.setApiKey(key)`; show success indicator; advance to Step 2
- [X] T036 [P] [US3] Implement `src/onboarding/steps/AudioSetupStep.tsx`: on mount call `window.electronAPI.getDevices()`; display detected default microphone name and default WASAPI loopback device name in confirmation cards; show warning if no loopback device found (with driver update instructions); "Looks good, continue" advances to Step 3
- [X] T037 [US3] Implement `src/onboarding/steps/AudioTestStep.tsx`: call `window.electronAPI.startSession({durationLimit: 10})` to start a 10s test capture; render live `<AudioVisualizer />` showing mic and loopback levels; "Both channels active?" confirmation with green checkmarks when both `micLevel > 0.05` and `loopbackLevel > 0.05` have been seen; stop session on advance; extend `POST /api/session/start` to accept optional `duration_limit_seconds` that auto-stops after N seconds for test mode
- [X] T038 [P] [US3] Implement `src/onboarding/steps/DemoStep.tsx`: hardcoded mock transcript array of 6 segments (3 "You", 3 "Them") with realistic meeting dialogue; play with typewriter-effect at 150ms per segment; after transcript plays, show mock AI response "Based on the discussion..." with token-drip animation; "This is what MeetingPal looks like in action" header
- [X] T039 [P] [US3] Implement `src/onboarding/steps/ReadyStep.tsx`: "You're ready!" heading; brief feature summary bullets; "Start Using MeetingPal" primary button; on click: call `window.electronAPI.setPreferences({onboarding_completed: true})`, then call `onComplete()` callback
- [X] T040 [US3] Implement `src/onboarding/OnboardingWizard.tsx`: step state machine (`step: 1 | 2 | 3 | 4 | 5`); progress indicator (dots or numbered steps); render the active step component; pass `onNext` / `onBack` callbacks; wrap in centered modal overlay with MeetingPal branding

**Checkpoint**: Delete keytar credential and `preferences.json`, relaunch via `npm run dev`, walk through all 5 steps — reach MainLayout at the end with onboarding flag set.

---

## Phase 6: User Story 4 — Settings & Customization (Priority: P3)

**Goal**: User opens Settings modal, changes Whisper model / audio device / API key / Claude model / theme / font size / save path / auto-save; all changes persist and take effect on next recording.

**Independent Test**: Open Settings, change `whisper_model` to `small.en`, save, close and reopen Settings — verify `small.en` is still selected. Change theme to light — verify UI switches.

- [X] T041 [US4] Implement `src/components/Settings.tsx`: modal/drawer triggered by TopBar gear icon; sections: API Key (password input + update button), Whisper Model (radio: base.en / small.en / medium.en), Audio Devices (mic dropdown + loopback dropdown populated from `getDevices()`), Claude Model (radio: sonnet / opus), Auto-save toggle, Save Location (folder picker via `dialog.showOpenDialog`), Font Size slider (10–24px), Dark/Light mode toggle; on Save: call `window.electronAPI.setPreferences({...changedFields})`; on Cancel: discard; show current values loaded from `getPreferences()` on open
- [X] T042 [US4] Implement live theme switching in `src/App.tsx`: subscribe to `preferences.theme` in `UserPreferences`; toggle `document.documentElement.classList.toggle('dark', theme === 'dark')` on change; apply `font-size` CSS variable to transcript panel from `preferences.font_size`
- [X] T043 [US4] Implement Whisper model hot-reload in `backend/transcriber.py`: add `PUT /api/preferences` handler to call `transcriber.load_model(new_model)` when `whisper_model` field changes; `load_model()` stops worker thread, replaces `WhisperModel` instance, restarts worker; block recording start during model reload with `model_loaded: false` in `/health`; wire "Open folder" button in Settings to `shell.openPath(saveLocation)` in Electron main

**Checkpoint**: Change Whisper model in Settings while not recording — sidecar log shows new model loading. Change theme — UI immediately switches dark/light. Font size slider updates transcript text in real time.

---

## Phase 7: User Story 5 — Transcript Export & Session Persistence (Priority: P3)

**Goal**: Stop Recording → transcript.md and qa_log.md saved to dated folder automatically (if auto-save on). Copy Transcript puts full text on clipboard. Export to .txt/.md saves file via dialog.

**Independent Test**: Start a short recording, generate 3 transcript segments, ask 1 AI question, click Stop Recording; verify `%USERPROFILE%\Documents\MeetingPal\recordings\YYYY-MM-DD_HH-MM\` folder contains `transcript.md` and `qa_log.md` with correct content.

- [X] T044 [US5] Implement `save_session(session: RecordingSession, prefs: UserPreferences)` in `backend/storage.py`: create folder `{save_path}\{YYYY-MM-DD_HH-MM}\`; write `transcript.md` with header and all segments formatted as `**[HH:MM AM/PM] Speaker**: text`; write `qa_log.md` with all `ChatMessage` pairs formatted per data-model.md; return saved folder path
- [X] T045 [US5] Update `POST /api/session/stop` response in `backend/main.py` to call `storage.save_session()` when `prefs.auto_save is True`; include `save_path` in response JSON; broadcast `session_status` WebSocket message with `save_path`
- [X] T046 [US5] Implement `copyTranscript` and `exportTranscript` in `electron/main.ts`: `copyTranscript(sessionId)` — fetch `GET /api/session/{id}/transcript`, format as plain text, call `clipboard.writeText()`; `exportTranscript(sessionId, format)` — show `dialog.showSaveDialog()` with `.txt`/`.md` filter, write formatted content to chosen path, return path
- [X] T047 [US5] Wire Copy and Export buttons in `src/components/TranscriptPanel.tsx`: "Copy Transcript" button calls `window.electronAPI.copyTranscript(sessionId)` and briefly shows "Copied!" feedback; "Export ▾" dropdown (txt / md) calls `window.electronAPI.exportTranscript(sessionId, format)` and shows saved-path toast

**Checkpoint**: Run a 30s session with 2 AI questions, click Stop, open the dated folder in Explorer — both markdown files present with correct content. Copy Transcript button pastes readable text in Notepad.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Packaging, error resilience, accessibility, and production readiness across all stories.

- [X] T048 Finalize `meetingpal.spec` PyInstaller file: verify all hidden imports from research.md Decision 6 are present; add `collect_data_files('faster_whisper')` and `collect_data_files('anthropic')`; set `console=False`; test `pyinstaller meetingpal.spec --clean` produces working `dist/meetingpal/meetingpal.exe`
- [X] T049 [P] Finalize `forge.config.ts`: verify `extraResources` copies `dist/meetingpal/` to `resources/sidecar/`; verify `asarUnpack` includes sidecar; verify `getSidecarPath()` in `electron/sidecar.ts` resolves correctly in packaged mode via `process.resourcesPath`; run `npm run make` and verify `MeetingPal-Setup.exe` produces a working install
- [X] T050 [P] Implement sidecar error display in renderer: `window.electronAPI.onError(error => ...)` in `src/App.tsx`; show non-blocking toast/banner for `recoverable: true` errors; show blocking modal for `recoverable: false` errors with actionable message (e.g., "No WASAPI loopback device found — update your audio drivers")
- [X] T051 [P] Implement Whisper model first-run download progress in `backend/transcriber.py`: intercept HuggingFace `tqdm` download progress and emit WebSocket `{"type":"model_download_progress","percent":float}` events; display progress bar in Electron loading screen while `model_loaded: false`
- [X] T052 [P] Add `GET /api/session/{session_id}/transcript` endpoint to `backend/main.py` (required by `copyTranscript` in T046); return `{"session_id":..., "segments":[...]}` per contracts/backend-api.md
- [X] T053 Validate `quickstart.md` end-to-end: follow every step from clone to first recording; update any commands or paths that have drifted; confirm all "Common Development Issues" entries are accurate
- [X] T054 [P] Update `CLAUDE.md` Recent Changes section: add entry summarizing completed feature `001-meetingpal-core-app` — PyAudioWPatch for WASAPI, faster-whisper transcription, Silero VAD, energy-heuristic diarization, Claude SSE streaming, keytar credential storage

**Checkpoint**: `npm run make` produces `MeetingPal-Setup.exe`; install on clean Windows VM; complete onboarding; record a 5-minute meeting; ask 3 questions; stop; verify saved files. All 12 acceptance criteria from spec.md pass.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — start immediately; all T001–T007 can run in parallel
- **Phase 2 (Foundational)**: Depends on Phase 1 — **blocks all user story phases**
- **Phase 3 (US1)**: Depends on Phase 2 completion — core MVP, highest priority
- **Phase 4 (US2)**: Depends on Phase 2; can start in parallel with Phase 3 by a second developer after Phase 2 complete
- **Phase 5 (US3)**: Depends on Phase 2; depends on Phase 3 (`AudioVisualizer`, `startSession`, `getDevices`) — start after Phase 3
- **Phase 6 (US4)**: Depends on Phase 2; some tasks depend on Phase 3 (Whisper reload) — start after Phase 3
- **Phase 7 (US5)**: Depends on Phase 3 (session model, transcript) and Phase 4 (Q&A log) — start after Phase 4
- **Phase 8 (Polish)**: Depends on all story phases

### User Story Dependencies

| Story | Depends On | Can Parallelize With |
|-------|-----------|----------------------|
| US1 (Live Transcription, P1) | Phase 2 | US2 (different files) |
| US2 (AI Q&A, P1) | Phase 2 | US1 (different files) |
| US3 (Onboarding, P2) | Phase 2 + US1 (AudioVisualizer, startSession) | US4 (different files) |
| US4 (Settings, P3) | Phase 2 + US1 (Whisper reload) | US3, US5 (different files) |
| US5 (Export, P3) | US1 (session model) + US2 (chat log) | US3, US4 (different files) |

### Within Each User Story

- Backend tasks (audio/transcription/Claude/storage) before the React components that consume them
- `backend/audio_capture.py` (T018) → `backend/transcriber.py` (T021) → WebSocket broadcast (T023) → React component (T024)
- `backend/claude_client.py` (T029) → SSE endpoint (T030) → React AI panel (T031) → token streaming wire (T032)

---

## Parallel Opportunities

### Phase 1 — All parallelizable

```
T001 ─┐
T002  ├─ All can run simultaneously (different config files)
T003  │
T004  │
T005  │
T006  │
T007 ─┘
```

### Phase 2 — Partial parallelism

```
T008 ─┐
T009  ├─ Parallel (different files)
T010  │
T011 ─┘
T012 ─ Sequential (sidecar.ts before main.ts)
T013 ─ Sequential (after T012)
T014 ─ Sequential (after T013 — preload references electronAPI shape)
T015 ─┐
T016  ├─ Parallel (different store files)
T017 ─┘
```

### Phase 3 (US1) — Backend tasks parallel with each other before frontend

```
T018 ─┐
T019  ├─ Backend tasks: parallel (different files)
T020 ─┘
T021 ─ After T018, T019, T020
T022 ─ After T021
T023 ─ After T022
T024 ─┐
T025  ├─ React components: parallel (different files)
T026  │
T027 ─┘
T028 ─ After T024, T025, T026, T027
```

### Phase 4 (US2) — Parallelizable with Phase 3 backend tasks

```
T029 ─ Parallel with Phase 3 (different file: claude_client.py)
T030 ─ After T029
T031 ─┐
T032  ├─ Parallel (different concerns)
     ─┘
T033 ─ After T031, T032
```

---

## Implementation Strategy

### MVP First (P1 Stories Only)

1. Complete **Phase 1** (Setup) — ~1 session
2. Complete **Phase 2** (Foundational) — ~2 sessions
3. Complete **Phase 3** (US1: Live Transcription) — **STOP and validate**
4. Complete **Phase 4** (US2: AI Q&A) — **STOP and validate**
5. **MVP complete**: recording + real-time transcript + AI Q&A fully functional

### Incremental Delivery

1. **Phase 1 + 2** → skeleton runs, health endpoint responds
2. **+ Phase 3** → recording and transcript work end-to-end (demoable)
3. **+ Phase 4** → AI Q&A streaming works (full core product)
4. **+ Phase 5** → onboarding wizard (new-user experience)
5. **+ Phase 6** → settings (power user features)
6. **+ Phase 7** → export and persistence (workflow integration)
7. **+ Phase 8** → packaged installer, error resilience

### Two-Developer Parallel Strategy

After Phase 2 completion:
- **Developer A**: Phase 3 (US1 backend: T018–T023) + Phase 3 (React: T024–T028)
- **Developer B**: Phase 4 (US2 backend: T029–T030) + Phase 4 (React: T031–T033)

Both developers merge after Phase 3 + 4, then continue sequentially through Phase 5–7.

---

## Notes

- `[P]` tasks operate on different files with no dependency on incomplete sibling tasks — safe to parallelize
- Story labels (`[US1]`–`[US5]`) map directly to user stories in spec.md
- No test tasks generated (not requested in spec)
- Commit after each checkpoint or logical group (T018–T020 together, T024–T027 together, etc.)
- Constitution Principle V: resist adding abstraction layers not needed for current tasks
- WASAPI loopback is Windows-only — no platform guards needed anywhere in the codebase