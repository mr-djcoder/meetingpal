# Implementation Plan: MeetingPal Core App

**Branch**: `001-meetingpal-core-app` | **Date**: 2026-03-12 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/001-meetingpal-core-app/spec.md`

---

## Summary

Build MeetingPal — a Windows 10/11 desktop application that captures system audio via WASAPI loopback and microphone simultaneously, transcribes speech locally using faster-whisper, performs 2-speaker diarization (You/Them), and provides real-time AI Q&A powered by Claude via a streaming SSE interface. Architecture: Electron 30 + React 18 frontend (renderer + main process) communicating with a Python 3.11 FastAPI sidecar over localhost WebSocket and REST. Sidecar is bundled as a PyInstaller .exe and spawned by Electron on startup. API key stored in Windows Credential Manager via keytar.

---

## Technical Context

**Language/Version**: TypeScript 5 (Electron/React), Python 3.11+
**Primary Dependencies**:
- Frontend: Electron 30, React 18, TailwindCSS 3, Zustand 4, Vite
- Backend: FastAPI, uvicorn, PyAudioWPatch, faster-whisper, silero-vad, speechbrain, scikit-learn, anthropic SDK
**Storage**: JSON file (`%APPDATA%\MeetingPal\preferences.json`), Markdown files per session, Windows Credential Manager (keytar)
**Testing**: Vitest (frontend unit), pytest (backend unit), Playwright (E2E)
**Target Platform**: Windows 10/11, 64-bit only
**Project Type**: Desktop app (Electron + Python sidecar)
**Performance Goals**: Transcript latency ≤ 4s end-to-end; AI first token ≤ 3s; audio pipeline ≤ 22ms WASAPI shared-mode latency
**Constraints**: 100% local transcription (no audio leaves device); API key never on disk; no platform guards for macOS/Linux
**Scale/Scope**: Single-user, single-session-at-a-time, Windows only

---

## Constitution Check

*Pre-research gate — all items verified.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Windows-Only, Local-First | PASS | PyAudioWPatch is Windows WASAPI only; faster-whisper runs locally; no audio leaves device |
| II. Electron + Python Sidecar | PASS | Exact stack defined: Electron 30 + React 18 + FastAPI sidecar; localhost IPC only |
| III. Real-Time First | PASS | 3s rolling chunks, 0.5s overlap, WebSocket for transcript, SSE for Claude tokens |
| IV. Privacy by Design | PASS | keytar for API key; no telemetry; transcripts local only; audio never sent externally |
| V. Simplicity Over Abstraction | PASS | Single worker thread for transcription; no repository pattern; no feature flags |

*Post-design gate — re-checked after Phase 1.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Windows-Only, Local-First | PASS | PyAudioWPatch, PyInstaller Windows target, WASAPI exclusively in contracts |
| II. Electron + Python Sidecar | PASS | IPC contract verified: renderer → bridge → main → localhost only |
| III. Real-Time First | PASS | Data model WebSocket shape defined; `AudioLevelFrame` at 10fps; SSE for Claude |
| IV. Privacy by Design | PASS | `UserPreferences` explicitly excludes API key field; keytar contract documented |
| V. Simplicity Over Abstraction | PASS | 8 backend files, no unnecessary layers; 5 React components, 2 Zustand stores |

---

## Project Structure

### Documentation (this feature)

```text
specs/001-meetingpal-core-app/
├── plan.md              # This file
├── research.md          # Phase 0 — all decisions with rationale
├── data-model.md        # Phase 1 — entity definitions
├── quickstart.md        # Phase 1 — dev setup guide
├── contracts/
│   └── backend-api.md   # Phase 1 — REST, WebSocket, IPC contracts
├── checklists/
│   └── requirements.md  # Spec quality checklist
└── tasks.md             # Phase 2 — created by /speckit.tasks
```

### Source Code (repository root)

```text
electron/
├── main.ts              # App lifecycle, sidecar spawn, IPC handlers, keytar
├── preload.ts           # contextBridge — exposes window.electronAPI to renderer
└── sidecar.ts           # SidecarManager class: spawn, health poll, restart, shutdown

src/
├── App.tsx              # Root: routing between Onboarding and MainLayout
├── components/
│   ├── TopBar.tsx        # Record toggle, timer, platform selector, settings icon
│   ├── TranscriptPanel.tsx  # Left 60% — live transcript feed, export controls
│   ├── AIChatPanel.tsx   # Right 40% — Claude Q&A, suggested chips, streaming
│   ├── AudioVisualizer.tsx  # Waveform bars (mic + loopback levels)
│   └── Settings.tsx      # Settings modal/drawer
├── store/
│   ├── transcriptStore.ts   # Zustand: segments[], session status, timer
│   └── chatStore.ts         # Zustand: chatMessages[], streaming state
├── hooks/
│   ├── useWebSocket.ts    # Subscribes to transcript_segment and audio_level events
│   └── useRecording.ts    # Start/stop session, exposes isRecording, duration
└── onboarding/
    └── OnboardingWizard.tsx  # 5-step wizard (steps 1-5)

backend/
├── main.py              # FastAPI app, route registration, lifespan startup/shutdown
├── audio_capture.py     # PyAudioWPatch: open mic + loopback streams, rolling buffer, mixing
├── transcriber.py       # WhisperModel wrapper: worker thread, queue, segment emission
├── vad.py               # Silero VAD: gate function, threshold config
├── diarizer.py          # Phase 1: mic/loopback energy heuristic; Phase 2: embedding clustering
├── claude_client.py     # Anthropic SDK: build messages[], sliding window context, SSE generator
└── storage.py           # Save transcript.md and qa_log.md to session folder

meetingpal.spec          # PyInstaller spec file
requirements.txt         # Python dependencies
package.json             # Node.js dependencies, scripts
forge.config.ts          # Electron Forge: Squirrel installer, extraResources
```

---

## Complexity Tracking

*No constitution violations — no entries required.*

---

## Phase 0: Research Findings Summary

All NEEDS CLARIFICATION items resolved. See [research.md](research.md) for full rationale.

| Question | Decision |
|----------|----------|
| WASAPI loopback library | PyAudioWPatch (only Python library with native WASAPI loopback support) |
| Transcription thread model | Single worker thread + queue (faster-whisper not thread-safe for concurrent calls) |
| VAD approach | Silero VAD batch mode on 3s chunks (gate before transcription) |
| Speaker diarization | Phase 1: mic/loopback energy heuristic; Phase 2: SpeechBrain embeddings + k-means |
| Sidecar spawn | `spawn()` + hardcoded port 8001 + HTTP health polling |
| PyInstaller mode | `--onedir`, model weights downloaded at first startup |
| API key storage | keytar v7 in main process; passed as `Authorization: Bearer` header |
| Claude streaming | FastAPI `StreamingResponse` + `text/event-stream`; React uses `fetch` + `ReadableStream` |

---

## Phase 1: Design Decisions

### Audio Pipeline Design

```
WASAPI Loopback stream (44.1kHz stereo)
  ↓ downsample + mono convert (scipy)
  ↓ → separate energy monitor → AudioLevelFrame (loopback_level)
Microphone stream (16kHz mono)
  ↓ → separate energy monitor → AudioLevelFrame (mic_level)
  ↓
Both channels → speaker heuristic (which channel has more energy?) → speaker label
  ↓
Mix 0.5 * mic + 0.5 * loopback → 16kHz mono float32
  ↓
RollingBuffer (3.5s deque, advance by 2.5s per chunk = 0.5s overlap)
  ↓
Silero VAD gate
  ↓ (if speech detected)
TranscriptionQueue (thread-safe Queue)
  ↓
WhisperWorkerThread: model.transcribe(chunk, vad_filter=True, beam_size=5)
  ↓
TranscriptSegment (with speaker label, confidence, timestamp)
  ↓
WebSocket broadcast → Electron main → webContents.send → renderer
  ↓
transcriptStore.addSegment() → TranscriptPanel re-renders
```

### Claude Context Strategy

```
POST /api/ask received
  ↓
Build system prompt:
  [MeetingPal persona] + [transcript segments formatted as [HH:MM AM/PM] You/Them: "..."]
  ↓ if system_prompt > 60K tokens → drop oldest segments until ≤ 60K
Retrieve conversation history from chatStore (messages[])
  ↓ if history > 20K tokens → drop oldest exchange pairs until ≤ 20K
Append new user message
  ↓
client.messages.stream(model, system, messages)
  ↓
SSE events → FastAPI StreamingResponse → fetch ReadableStream → chatStore.appendToken()
  ↓
On message_stop → chatStore.finalizeMessage()
```

### Onboarding Flow

```
App launch → check UserPreferences.onboarding_completed
  → false → render OnboardingWizard
  → true  → render MainLayout

OnboardingWizard steps:
  Step 1: ApiKeyStep — input + store via window.electronAPI.setApiKey()
  Step 2: AudioSetupStep — GET /api/devices, show defaults, confirm
  Step 3: AudioTestStep — start 10s test session, show AudioVisualizer live
  Step 4: DemoStep — play mock transcript + mock AI response with typewriter effect
  Step 5: ReadyStep — set onboarding_completed=true, transition to MainLayout
```

### State Management

**transcriptStore** (Zustand):
```typescript
interface TranscriptStore {
  sessionId: string | null;
  isRecording: boolean;
  sessionStartedAt: Date | null;
  segments: TranscriptSegment[];
  // Actions
  startSession(id: string): void;
  stopSession(): void;
  addSegment(segment: TranscriptSegment): void;
  clearSession(): void;
}
```

**chatStore** (Zustand):
```typescript
interface ChatStore {
  messages: ChatMessage[];
  isStreaming: boolean;
  streamingContent: string;  // Accumulates tokens during stream
  // Actions
  addUserMessage(content: string): string;  // returns message id
  appendToken(token: string): void;
  finalizeAssistantMessage(): void;
  clearHistory(): void;
}
```