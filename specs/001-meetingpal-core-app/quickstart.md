# Quickstart: MeetingPal Development Setup

**Branch**: `001-meetingpal-core-app` | **Date**: 2026-03-12
**Platform**: Windows 10/11 64-bit only

---

## Prerequisites

- **Node.js** 20+ (LTS) — for Electron/React frontend
- **Python 3.11** — for the FastAPI sidecar
- **Git** — for version control
- **NVIDIA GPU** (optional but recommended) — for real-time transcription at higher quality levels

---

## 1. Clone & Install Frontend Dependencies

```bash
git clone <repo-url> MeetingPal
cd MeetingPal
npm install
```

`npm install` triggers `postinstall` which runs `electron-rebuild -w keytar -f` to compile the native keytar module against the local Electron version.

---

## 2. Install Python Backend Dependencies

```bash
cd MeetingPal
pip install -r requirements.txt
```

Key packages installed:
- `pyaudiowpatch` — WASAPI loopback audio capture (Windows-specific PyAudio fork)
- `faster-whisper` — Local speech-to-text
- `silero-vad` — Voice activity detection
- `speechbrain` — Speaker embedding for diarization (Phase 2)
- `scikit-learn` — Clustering for diarization
- `anthropic` — Claude API SDK
- `fastapi` + `uvicorn` — HTTP + WebSocket server

---

## 3. Run in Development Mode

**Terminal 1 — Python sidecar**:
```bash
cd MeetingPal
python backend/main.py --port 8001 --dev
```

On first startup the sidecar downloads the Whisper `base.en` model (~150MB) and caches it in `%USERPROFILE%\.cache\huggingface\hub\`. Subsequent starts skip the download.

You should see:
```
[MeetingPal Sidecar] Loading Whisper base.en model...
[MeetingPal Sidecar] Model loaded in 3.2s
[MeetingPal Sidecar] Uvicorn running on http://localhost:8001
```

**Terminal 2 — Electron + React**:
```bash
cd MeetingPal
npm run dev
```

Vite builds the React renderer and Electron opens the dev window. The Electron main process connects to the already-running sidecar at `localhost:8001`.

In dev mode, Electron does **not** spawn its own sidecar — it expects one to be already running. This allows rapid backend iteration without restarting Electron.

---

## 4. First-Run Onboarding

On first launch (no stored API key), the onboarding wizard appears:

1. **Step 1**: Enter your Anthropic API key — get one at console.anthropic.com
2. **Step 2**: Confirm detected audio devices (should auto-detect default mic + loopback)
3. **Step 3**: Audio test — play any audio on your PC; the waveform should show loopback activity
4. **Step 4**: Demo transcript — mock meeting transcript and AI response appear
5. **Step 5**: Click "Start Using MeetingPal"

---

## 5. Build & Package (Windows Only)

### Bundle Python Sidecar

```bash
# From repo root
pip install pyinstaller
pyinstaller meetingpal.spec
# Output: dist/meetingpal/meetingpal.exe (~500MB-1GB)
```

### Package Electron App (Squirrel Installer)

```bash
npm run make
# Output: out/make/squirrel.windows/x64/MeetingPal-Setup.exe
```

`npm run make` copies `dist/meetingpal/` into `resources/sidecar/` during packaging.

---

## 6. Key File Locations (Runtime)

| What | Where |
|------|-------|
| User preferences | `%APPDATA%\MeetingPal\preferences.json` |
| Whisper model cache | `%USERPROFILE%\.cache\huggingface\hub\` |
| Whisper model (first run download) | `%APPDATA%\MeetingPal\models\` |
| Saved recordings | `%USERPROFILE%\Documents\MeetingPal\recordings\YYYY-MM-DD_HH-MM\` |
| Electron logs | `%APPDATA%\MeetingPal\logs\main.log` |
| Sidecar logs | `%APPDATA%\MeetingPal\logs\sidecar.log` |
| API key | Windows Credential Manager → service: `MeetingPal`, account: `anthropic-api-key` |

---

## 7. Useful Dev Commands

```bash
# Frontend
npm run dev          # Start Electron in dev mode
npm run build        # Build React renderer only
npm run make         # Package with Squirrel installer (Windows only)

# Backend
python backend/main.py               # Run sidecar standalone
python backend/main.py --port 8002   # Custom port
python -m pyaudiowpatch              # List all audio devices (debug WASAPI)

# PyInstaller
pyinstaller meetingpal.spec          # Bundle sidecar
pyinstaller meetingpal.spec --clean  # Force clean rebuild

# Speckit
bash .specify/scripts/bash/update-agent-context.sh claude   # Refresh CLAUDE.md
bash .specify/scripts/bash/check-prerequisites.sh           # Validate spec/plan exist
```

---

## 8. Common Development Issues

**"No WASAPI loopback device found"**
- Ensure audio is routed through Windows default playback device
- Run `python -m pyaudiowpatch` and look for devices with `[Loopback]` in the name
- Update Realtek/audio drivers if no loopback devices appear

**"keytar module not found" or "keytar.node is not valid"**
- Run `npm run postinstall` or `npx electron-rebuild -w keytar -f`
- Ensure you're using the same Node.js architecture (x64) as Electron

**"Whisper model loading very slow"**
- First run downloads ~150MB — normal. Subsequent starts use cache.
- On CPU-only machines, base.en takes ~3-5s to load, ~200-400ms per chunk to transcribe

**"CUDA not available"**
- Sidecar automatically falls back to CPU+int8 — no action needed
- To verify: sidecar logs show `device=cpu` or `device=cuda` at startup

**Transcription not appearing**
- Check that Silero VAD is detecting speech: sidecar logs `[VAD] speech_detected=True`
- Verify both mic and loopback streams are opened: look for `[Audio] Streams opened: mic=<name>, loopback=<name>`
