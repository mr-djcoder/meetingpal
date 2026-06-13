# MeetingPal Development Guidelines

Auto-generated from project constitution. Last updated: 2026-03-12

## Active Technologies
- TypeScript 5 (Electron/React), Python 3.11+ (001-meetingpal-core-app)
- JSON file (`%APPDATA%\MeetingPal\preferences.json`), Markdown files per session, Windows Credential Manager (keytar) (001-meetingpal-core-app)

- TypeScript + React 18 + Electron 30 (frontend/desktop shell)
- Python 3.11 + FastAPI + faster-whisper (backend sidecar)
- TailwindCSS + Zustand (UI styling and state)
- sounddevice + PyAudio (WASAPI audio capture)
- Silero VAD + pyannote.audio (voice activity detection + diarization)
- anthropic SDK (Claude API — claude-sonnet-4-6 default)

## Project Structure

```text
meetingpal/
├── electron/
│   ├── main.ts              # Electron main process, spawns Python sidecar
│   ├── preload.ts           # Context bridge (IPC)
│   └── sidecar.ts           # Manages Python process lifecycle
├── src/
│   ├── App.tsx
│   ├── components/
│   │   ├── TranscriptPanel.tsx
│   │   ├── AIChatPanel.tsx
│   │   ├── TopBar.tsx
│   │   ├── AudioVisualizer.tsx
│   │   └── Settings.tsx
│   ├── store/
│   │   ├── transcriptStore.ts
│   │   └── chatStore.ts
│   └── hooks/
│       ├── useWebSocket.ts
│       └── useRecording.ts
├── backend/
│   ├── main.py              # FastAPI app entrypoint
│   ├── audio_capture.py     # sounddevice + WASAPI loopback capture
│   ├── transcriber.py       # faster-whisper pipeline
│   ├── vad.py               # Silero VAD integration
│   ├── diarizer.py          # pyannote speaker diarization
│   ├── claude_client.py     # Anthropic SDK, streaming Q&A
│   └── storage.py           # Transcript save/load
├── specs/                   # Feature specs (speckit workflow)
├── package.json
├── requirements.txt
└── forge.config.ts          # Electron Forge — Windows Squirrel installer only
```

## Commands

```bash
# Frontend (Electron + React)
npm install
npm run dev          # Start Electron in development mode
npm run build        # Build React renderer
npm run make         # Package with Electron Forge (Windows only)

# Backend (Python sidecar)
pip install -r requirements.txt
python backend/main.py          # Run sidecar standalone for development
pyinstaller meetingpal.spec     # Bundle sidecar into .exe

# Speckit workflow
bash .specify/scripts/bash/create-new-feature.sh "<description>"   # Create feature branch + spec
bash .specify/scripts/bash/setup-plan.sh                            # Scaffold plan.md
bash .specify/scripts/bash/check-prerequisites.sh                   # Validate spec/plan exist
bash .specify/scripts/bash/update-agent-context.sh claude           # Refresh this file
```

## Code Style

- **TypeScript**: Strict mode enabled. No `any`. Prefer `interface` over `type` for object shapes. React functional components only.
- **Python**: Follow PEP 8. Type hints on all function signatures. No bare `except:` clauses.
- **Architecture**: Electron main process ↔ Python sidecar via localhost WebSocket/REST only. No direct renderer↔Python communication. All IPC goes through the context bridge in `preload.ts`.
- **Privacy**: Claude API key via `keytar` (Windows Credential Manager) only — never disk, never logs, never frontend state.
- **Platform**: Windows 10/11 64-bit only. No platform guards or conditional paths for macOS/Linux.

## Key Constraints

- Audio capture: WASAPI loopback (system audio) + default mic, mixed at 16kHz mono
- Transcription: faster-whisper local only — no audio leaves the machine
- Chunking: 3-second rolling chunks with 0.5s overlap for real-time transcription
- Claude context: last N transcript segments up to ~80K tokens per request
- Claude responses: SSE streaming, token-by-token to frontend
- Transcript storage: `C:\Users\<user>\Documents\MeetingPal\recordings\YYYY-MM-DD_HH-MM\`

## Recent Changes
- 001-meetingpal-core-app: Added TypeScript 5 (Electron/React), Python 3.11+

- Initial project setup
- 001-meetingpal-core-app: Full implementation complete (2026-03-16)
  - PyAudioWPatch WASAPI loopback + mic capture, mixed at 16kHz mono
  - faster-whisper real-time transcription (base.en default, GPU/CPU fallback)
  - Silero VAD gating on 3s rolling chunks with 0.5s overlap
  - Mic/loopback energy heuristic diarization → "You" / "Them" labels
  - Claude SSE streaming via FastAPI StreamingResponse + Anthropic SDK
  - keytar Windows Credential Manager for API key (never on disk)
  - Electron 30 + React 18 + TailwindCSS + Zustand state management
  - 5-step onboarding wizard (API key → audio setup → test → demo → ready)
  - Settings modal: model selection, device picker, theme, font size, auto-save
  - Transcript auto-save to dated folder (transcript.md + qa_log.md)
  - Copy/Export transcript (clipboard + .txt/.md via save dialog)
  - SidecarManager: spawn, health poll, crash restart (3×), SIGTERM/SIGKILL shutdown

<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->
