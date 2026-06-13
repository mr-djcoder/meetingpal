# MeetingPal Constitution

## Core Principles

### I. Windows-Only, Local-First
This is a Windows 10/11 desktop application — no macOS, no Linux, no cross-platform abstractions. All audio capture uses WASAPI loopback natively (no third-party drivers). All transcription runs 100% on-device via faster-whisper. Audio never leaves the machine. Only the text transcript is sent to Anthropic when the user explicitly asks a question.

### II. Electron + Python Sidecar Architecture
The frontend is Electron 30+ (main process + renderer) with React 18 + TypeScript. The backend is a Python 3.11+ FastAPI sidecar spawned as a child process by Electron main. IPC between them is localhost WebSocket and REST only — no direct Python↔renderer communication. The sidecar is bundled via PyInstaller into `resources/sidecar/meetingpal-backend.exe`.

### III. Real-Time First
Every feature that involves audio, transcription, or AI responses must prioritize latency. Audio chunks are 3-second rolling windows with 0.5s overlap. Transcription segments are emitted over WebSocket as `{ timestamp, text, is_final }`. Claude responses stream token-by-token via SSE. Nothing blocks the UI thread.

### IV. Privacy by Design (NON-NEGOTIABLE)
- Claude API key is stored exclusively in Windows Credential Manager via `keytar` — never written to disk in plaintext
- No telemetry, no cloud sync, no user accounts
- Transcripts saved locally to `C:\Users\<user>\Documents\MeetingPal\recordings\` only
- The word "privacy" in any user-facing string must be backed by the actual implementation

### V. Simplicity Over Abstraction
Start with the simplest working implementation. No premature abstractions. Three similar code paths are better than a factory. No feature flags unless a feature is being actively toggled. YAGNI — if the spec doesn't require it, don't build it.

## Technical Constraints

- **Target**: Windows 10/11, 64-bit only — no platform guards or conditional paths for other OSes
- **Language/Version**: TypeScript (Electron/React), Python 3.11+
- **Frontend stack**: Electron 30+, React 18, TailwindCSS, Zustand, WebSocket client
- **Backend stack**: FastAPI, faster-whisper, sounddevice + PyAudio (WASAPI), Silero VAD, pyannote.audio, anthropic SDK
- **AI models**: claude-sonnet-4-6 (default), claude-opus-4-6 (optional)
- **Whisper models**: base.en (default), small.en, medium.en (user-selectable)
- **Packaging**: Electron Forge + Squirrel installer, PyInstaller sidecar, base.en weights bundled (~150MB)
- **Audio**: 16kHz mono, both mic (default input) + system audio (WASAPI loopback), mixed before Whisper

## Development Workflow

- Every feature starts with a spec in `specs/###-feature-name/spec.md`
- Implementation plan goes in `specs/###-feature-name/plan.md` before any code is written
- Constitution check is required before Phase 0 research and again after Phase 1 design
- No code is written until the spec and plan are approved

## Governance

This constitution supersedes all other practices. All feature branches and PRs must verify compliance. Complexity must be justified in the Complexity Tracking table. Amendments require a documented rationale and updated ratification date.

**Version**: 1.0.0 | **Ratified**: 2026-03-12 | **Last Amended**: 2026-03-12