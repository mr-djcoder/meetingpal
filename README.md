# MeetingPal

Real-time meeting transcription and AI assistant for Windows. Captures system audio (WASAPI loopback) **and** your microphone, transcribes locally with faster-whisper, labels speakers, and answers questions about the live conversation using Claude — all without audio ever leaving the machine.

> **Platform:** Windows 10/11 64-bit only. **Privacy:** transcription is fully local; the only outbound calls are to the Claude API for Q&A.

## Stack

| Layer | Tech |
|-------|------|
| Desktop shell | Electron 30 |
| UI | React 18 + TypeScript 5 + TailwindCSS + Zustand |
| Backend sidecar | Python 3.11+ + FastAPI (localhost WebSocket/REST) |
| Transcription | faster-whisper (local, `base.en` default, GPU→CPU int8 fallback) |
| Audio capture | PyAudioWPatch (WASAPI loopback + mic, mixed to 16kHz mono) |
| Voice activity | Silero VAD |
| AI Q&A | Anthropic SDK — `claude-sonnet-4-6` default, SSE streaming |
| Secrets | Windows Credential Manager via keytar |

## Architecture

Electron main process spawns the Python sidecar as a child process. They talk over **localhost WebSocket + REST only** — the renderer never talks to Python directly; all IPC goes through the context bridge in `electron/preload.ts`.

```
renderer (React) ──IPC──► Electron main ──ws/REST──► Python sidecar (FastAPI :8001)
                                                       ├─ audio_capture (mic + WASAPI loopback)
                                                       ├─ vad (Silero)
                                                       ├─ transcriber (faster-whisper)
                                                       └─ claude_client (Anthropic SDK)
```

## Project structure

```
meetingpal/
├── electron/        # main process, preload bridge, sidecar lifecycle
├── src/             # React renderer (components, store, hooks, onboarding)
├── backend/         # Python sidecar (FastAPI, audio, transcribe, VAD, Claude)
├── specs/           # Feature specs (speckit workflow)
├── docs/            # Design specs
├── package.json
├── requirements.txt
└── forge.config.ts  # Electron Forge — Windows Squirrel installer
```

## Prerequisites

- Windows 10/11 64-bit
- Node.js 20+ and npm
- Python 3.11+ (a local `.venv` is expected; see note below)
- An Anthropic API key (entered in-app on first run; stored in Windows Credential Manager)

> **Note:** the committed `requirements.txt` pins a Python 3.11-era dependency set. The current dev `.venv` runs Python 3.13 with newer torch/numpy. Align the venv to the pins (or update the pins) before packaging a release.

## Setup

```bash
# Frontend
npm install

# Backend (use a virtual environment)
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Running (development)

```bash
npm run dev
```

This launches Electron, builds the renderer + main/preload via Vite, and spawns the Python sidecar automatically. The sidecar dev-spawn picks `python` off PATH — launch from a shell with `.venv` active so it uses the project interpreter (not the WindowsApps stub).

Run the sidecar standalone for backend work:

```bash
python -m backend.main --port 8001
```

## Build / package (Windows only)

```bash
npm run build              # Build React renderer
pyinstaller meetingpal.spec  # Bundle the Python sidecar into an .exe
npm run make               # Package with Electron Forge (Squirrel installer)
```

## Privacy & security

- **Audio never leaves the machine** — transcription is local via faster-whisper.
- **API key** is stored only in Windows Credential Manager (keytar). Never written to disk, logs, or frontend state.
- `.env*`, `*.key`, `preferences.json`, model weights, and logs are git-ignored. Do not commit secrets.

## Key constraints

- Audio: WASAPI loopback (system) + default mic, mixed at 16kHz mono.
- Claude context: recent transcript segments up to ~80K tokens per request.
- Transcript storage: `Documents/MeetingPal/recordings/YYYY-MM-DD_HH-MM/`.

## Status

Core app implemented (capture, transcription, VAD, diarization, Claude streaming Q&A, onboarding, settings, transcript save/export). Active work: caption-style **utterance assembler** to replace per-chunk fragments with whole-statement transcript lines — see `docs/superpowers/specs/2026-06-13-utterance-assembler-design.md`.
