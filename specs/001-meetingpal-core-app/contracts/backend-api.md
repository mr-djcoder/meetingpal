# Backend API Contracts: MeetingPal Sidecar

**Branch**: `001-meetingpal-core-app` | **Date**: 2026-03-12
**Base URL**: `http://localhost:8001`
**Auth**: `Authorization: Bearer <anthropic-api-key>` on all `/api/*` endpoints

---

## REST Endpoints

### GET /health
Readiness probe. Electron main polls this until 200 before creating the window.

**Response 200**:
```json
{ "status": "healthy", "model_loaded": true, "sidecar_version": "1.0.0" }
```
`model_loaded` is `false` while faster-whisper is still loading; Electron may show a loading indicator.

---

### GET /api/devices
List available audio input devices (microphones + WASAPI loopback devices).

**Response 200**:
```json
{
  "devices": [
    {
      "index": 0,
      "name": "Microphone (Realtek High Definition Audio)",
      "device_type": "microphone",
      "channels": 1,
      "default_sample_rate": 44100.0,
      "is_default": true
    },
    {
      "index": 7,
      "name": "Speakers (Realtek High Definition Audio) [Loopback]",
      "device_type": "loopback",
      "channels": 2,
      "default_sample_rate": 44100.0,
      "is_default": true
    }
  ]
}
```

---

### POST /api/session/start
Begin a new recording session. Starts audio capture and transcription pipeline.

**Request body**:
```json
{
  "mic_device_index": null,
  "loopback_device_index": null,
  "whisper_model": "base.en"
}
```
`null` values use the system defaults.

**Response 200**:
```json
{
  "session_id": "3f8a1b2c-4d5e-6f7a-8b9c-0d1e2f3a4b5c",
  "started_at": "2026-03-12T10:30:00.000Z",
  "status": "recording"
}
```

**Response 409** (session already active):
```json
{ "error": "A recording session is already active", "session_id": "..." }
```

---

### POST /api/session/stop
Stop the active recording session. Flushes remaining audio, emits final segments, saves files if auto-save enabled.

**Request body**: `{}` (empty)

**Response 200**:
```json
{
  "session_id": "3f8a1b2c-4d5e-6f7a-8b9c-0d1e2f3a4b5c",
  "stopped_at": "2026-03-12T11:17:32.000Z",
  "duration_seconds": 2852,
  "segment_count": 847,
  "save_path": "C:\\Users\\djvuan\\Documents\\MeetingPal\\recordings\\2026-03-12_10-30"
}
```
`save_path` is `null` if auto-save is disabled.

**Response 404** (no active session):
```json
{ "error": "No active recording session" }
```

---

### POST /api/ask
Ask Claude a question about the meeting. Returns an SSE stream.

**Request body**:
```json
{
  "question": "What are the action items?",
  "session_id": "3f8a1b2c-4d5e-6f7a-8b9c-0d1e2f3a4b5c",
  "claude_model": "claude-sonnet-4-6"
}
```
`claude_model` defaults to `"claude-sonnet-4-6"` if omitted.

**Response headers**:
```
Content-Type: text/event-stream
Cache-Control: no-cache
Transfer-Encoding: chunked
```

**SSE event stream**:
```
event: message_start
data: {"message_id": "msg_01XFDUDYJgAACcwz", "model": "claude-sonnet-4-6"}

event: content_delta
data: {"text": "Based"}

event: content_delta
data: {"text": " on"}

event: content_delta
data: {"text": " the discussion"}

event: message_stop
data: {"message_id": "msg_01XFDUDYJgAACcwz", "stop_reason": "end_turn", "input_tokens": 4321, "output_tokens": 87}

event: error
data: {"error": "API key invalid or quota exceeded"}
```

`event: error` terminates the stream on failure.

---

### GET /api/session/{session_id}/transcript
Retrieve the full transcript for a session (active or stopped).

**Response 200**:
```json
{
  "session_id": "3f8a1b2c-...",
  "segments": [
    {
      "id": "seg-001",
      "speaker": "You",
      "wall_clock_time": "2026-03-12T10:32:15.123Z",
      "session_offset_seconds": 135.1,
      "text": "We need to finalize the Q2 budget by Friday.",
      "is_final": true,
      "confidence": 0.94
    }
  ]
}
```

---

### GET /api/preferences
Get current user preferences.

**Response 200**: `UserPreferences` object (see data-model.md). API key field is omitted.

---

### PUT /api/preferences
Update user preferences. Partial updates supported (only provided fields are changed).

**Request body** (example — all fields optional):
```json
{
  "whisper_model": "small.en",
  "theme": "light",
  "font_size": 16
}
```

**Response 200**: Updated `UserPreferences` object.

---

### POST /api/key
Store or update the Anthropic API key in Windows Credential Manager.

**Request body**:
```json
{ "api_key": "sk-ant-..." }
```

**Response 200**:
```json
{ "stored": true }
```

**Note**: This endpoint is called by Electron main via IPC — the renderer never directly calls it. The Electron main process retrieves the key from keytar and injects it as a header on all `/api/*` requests.

---

## WebSocket: `ws://localhost:8001/ws`

Persistent connection maintained by Electron main process. All real-time pushes from sidecar to frontend flow through this channel.

### Server → Client Messages

**Transcript segment** (emitted for each confirmed segment):
```json
{
  "type": "transcript_segment",
  "speaker": "You",
  "wall_clock_time": "2026-03-12T10:32:15.123Z",
  "session_offset_seconds": 135.1,
  "text": "We need to finalize the Q2 budget by Friday.",
  "is_final": true,
  "confidence": 0.94
}
```

**Audio level frame** (emitted ~10 fps during recording):
```json
{
  "type": "audio_level",
  "mic_level": 0.32,
  "loopback_level": 0.18,
  "timestamp_ms": 135100
}
```

**Session status update**:
```json
{
  "type": "session_status",
  "status": "recording",
  "session_id": "3f8a1b2c-..."
}
```

**Sidecar error**:
```json
{
  "type": "error",
  "code": "WASAPI_DEVICE_NOT_FOUND",
  "message": "The selected loopback device is no longer available.",
  "recoverable": false
}
```

### Error Codes

| Code | Meaning | Recoverable |
|------|---------|-------------|
| `WASAPI_DEVICE_NOT_FOUND` | Selected audio device missing | No — stop session |
| `WASAPI_LOOPBACK_UNAVAILABLE` | No WASAPI loopback devices on system | No — show setup help |
| `TRANSCRIPTION_OVERLOAD` | Audio queue growing faster than transcription | Yes — auto-recovers |
| `MODEL_NOT_LOADED` | Whisper model not yet ready | Yes — wait for health check |
| `CLAUDE_AUTH_ERROR` | API key invalid or expired | No — prompt re-entry |
| `CLAUDE_QUOTA_EXCEEDED` | Rate limit or quota hit | Yes — retry after delay |

---

## IPC Contracts: Electron Context Bridge

Exposed on `window.electronAPI` in the renderer via preload.ts.

```typescript
interface ElectronAPI {
  // Audio & session
  getDevices(): Promise<AudioDevice[]>;
  startSession(options: StartSessionOptions): Promise<SessionInfo>;
  stopSession(): Promise<SessionSummary>;

  // AI Q&A — returns void; AI tokens arrive via onAiToken listener
  askQuestion(question: string, model?: ClaudeModel): Promise<void>;

  // Preferences
  getPreferences(): Promise<UserPreferences>;
  setPreferences(partial: Partial<UserPreferences>): Promise<UserPreferences>;

  // API key management (main process ↔ keytar only; renderer just calls this)
  setApiKey(key: string): Promise<void>;
  hasApiKey(): Promise<boolean>;

  // Real-time listeners (call removeListener on unmount)
  onTranscriptSegment(cb: (segment: TranscriptSegment) => void): () => void;
  onAudioLevel(cb: (frame: AudioLevelFrame) => void): () => void;
  onAiToken(cb: (token: string) => void): () => void;
  onAiDone(cb: (summary: AiMessageSummary) => void): () => void;
  onError(cb: (error: SidecarError) => void): () => void;

  // Export
  copyTranscript(sessionId: string): Promise<void>;
  exportTranscript(sessionId: string, format: 'txt' | 'md'): Promise<string>;  // returns saved path
}
```
