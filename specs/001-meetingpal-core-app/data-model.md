# Data Model: MeetingPal Core App

**Branch**: `001-meetingpal-core-app` | **Date**: 2026-03-12

---

## Entities

### RecordingSession

Represents a single meeting capture event, from Start Recording to Stop Recording.

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` (UUID4) | Unique session identifier |
| `started_at` | `datetime` | Wall-clock time when recording started |
| `stopped_at` | `datetime \| None` | Wall-clock time when recording stopped; `None` if active |
| `status` | `Literal["recording", "stopped"]` | Current session state |
| `save_path` | `str \| None` | Absolute path to the session folder on disk; `None` until saved |
| `segments` | `list[TranscriptSegment]` | Ordered list of all transcript segments |
| `chat_messages` | `list[ChatMessage]` | Ordered list of all Q&A exchanges |

**Constraints**:
- `stopped_at` must be ≥ `started_at` when set
- `status == "stopped"` iff `stopped_at` is not `None`
- Only one session may have `status == "recording"` at any time

**State transitions**:
```
(none) → recording  [user clicks Start Recording]
recording → stopped  [user clicks Stop Recording]
```

---

### TranscriptSegment

A single unit of confirmed transcribed speech within a session.

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` (UUID4) | Unique segment identifier |
| `session_id` | `str` | Parent `RecordingSession.id` |
| `speaker` | `Literal["You", "Them"]` | Speaker label |
| `wall_clock_time` | `datetime` | Absolute wall-clock time of segment start |
| `session_offset_seconds` | `float` | Seconds since session `started_at` |
| `text` | `str` | Transcribed text, stripped of leading/trailing whitespace |
| `is_final` | `bool` | Always `True` for stored segments; `False` only during in-flight WS emission |
| `audio_source` | `Literal["mic", "loopback", "mixed"]` | Which audio channel this segment came from |
| `confidence` | `float` | Derived from `1.0 - no_speech_prob` from faster-whisper; range [0.0, 1.0] |

**Constraints**:
- `text` must be non-empty
- `session_offset_seconds` ≥ 0.0
- `confidence` in [0.0, 1.0]

**WebSocket emission shape** (in-flight, before storage):
```jsonc
{
  "type": "transcript_segment",
  "speaker": "You",
  "wall_clock_time": "2026-03-12T10:32:15.123Z",
  "session_offset_seconds": 47.3,
  "text": "We need to finalize the Q2 budget by Friday.",
  "is_final": true,
  "confidence": 0.94
}
```

---

### ChatMessage

A single turn in the AI Q&A conversation, within a session.

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` (UUID4) | Unique message identifier |
| `session_id` | `str` | Parent `RecordingSession.id` |
| `role` | `Literal["user", "assistant"]` | Message originator |
| `content` | `str` | Full message text (for assistant, accumulated from stream) |
| `created_at` | `datetime` | Wall-clock time of message creation |
| `transcript_snapshot_count` | `int` | Number of transcript segments included as context when this message was sent |

**Constraints**:
- Messages alternate `user` / `assistant` roles
- `content` non-empty
- `role == "user"` messages are created immediately on submit; `role == "assistant"` messages are created and accumulated as SSE tokens arrive

---

### AudioDevice

A capturable audio device available on the user's Windows system.

| Field | Type | Description |
|-------|------|-------------|
| `index` | `int` | PyAudioWPatch device index |
| `name` | `str` | Human-readable device name (as shown in Windows Sound settings) |
| `device_type` | `Literal["microphone", "loopback"]` | Whether this is a mic input or WASAPI loopback device |
| `channels` | `int` | Number of audio channels (1 = mono, 2 = stereo) |
| `default_sample_rate` | `float` | Device's native sample rate (e.g., 44100, 48000, 16000) |
| `is_default` | `bool` | Whether this is the Windows default device of its type |

**Constraints**:
- `device_type == "loopback"` devices are always `channels == 2` (WASAPI loopback is stereo)
- `is_default` may be `True` for at most one device per `device_type`

---

### UserPreferences

Persistent user configuration stored in the app data directory as JSON (except API key — stored in Windows Credential Manager).

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `whisper_model` | `Literal["base.en", "small.en", "medium.en"]` | `"base.en"` | Transcription quality level |
| `claude_model` | `Literal["claude-sonnet-4-6", "claude-opus-4-6"]` | `"claude-sonnet-4-6"` | AI model tier |
| `mic_device_index` | `int \| None` | `None` (auto: Windows default) | Selected microphone PyAudio index |
| `loopback_device_index` | `int \| None` | `None` (auto: default WASAPI loopback) | Selected loopback device PyAudio index |
| `auto_save` | `bool` | `true` | Auto-save transcript on Stop Recording |
| `save_path` | `str` | `%USERPROFILE%\Documents\MeetingPal\recordings` | Root folder for saved sessions |
| `font_size` | `int` | `14` | Transcript panel font size in px; range [10, 24] |
| `theme` | `Literal["dark", "light"]` | `"dark"` | UI color theme |
| `onboarding_completed` | `bool` | `false` | Whether first-run wizard has been completed |

**Storage**: `%APPDATA%\MeetingPal\preferences.json`
**API key**: NOT stored here — stored in Windows Credential Manager via keytar (service: `MeetingPal`, account: `anthropic-api-key`)

---

### AudioLevelFrame

Ephemeral, not persisted. Emitted over WebSocket ~10 times per second to drive the waveform visualizer.

| Field | Type | Description |
|-------|------|-------------|
| `type` | `"audio_level"` | Frame type discriminator |
| `mic_level` | `float` | RMS amplitude of mic channel, range [0.0, 1.0] |
| `loopback_level` | `float` | RMS amplitude of loopback channel, range [0.0, 1.0] |
| `timestamp_ms` | `int` | Milliseconds since session start |

---

## In-Memory State (Backend, Per Session)

```
ActiveSession:
  session: RecordingSession
  audio_buffer: deque[float32]          # Rolling 3.5s audio buffer (3s chunk + 0.5s overlap)
  mic_buffer: deque[float32]            # Separate mic channel buffer (for speaker detection)
  loopback_buffer: deque[float32]       # Separate loopback channel buffer
  transcriber_queue: Queue[np.ndarray]  # Audio chunks awaiting transcription
  chat_history: list[ChatMessage]       # In-memory conversation history for Claude context
  transcript_segments: list[TranscriptSegment]  # All confirmed segments (grows over session)
  connected_websockets: set[WebSocket]  # Active frontend connections
```

---

## Saved Files (Per Session)

```
%USERPROFILE%\Documents\MeetingPal\recordings\YYYY-MM-DD_HH-MM\
  transcript.md      # Human-readable Markdown transcript
  qa_log.md          # Q&A conversation log
```

**transcript.md format**:
```markdown
# Meeting Transcript
**Date**: 2026-03-12 | **Duration**: 47:32

---

**[10:32 AM] You**: We need to finalize the Q2 budget by Friday.

**[10:33 AM] Them**: I can have the numbers ready by Thursday.
```

**qa_log.md format**:
```markdown
# Q&A Log
**Date**: 2026-03-12 | **Session**: 2026-03-12_10-30

---

**[10:45 AM] You asked**: What are the action items?

**[10:45 AM] MeetingPal**: Based on the discussion:
1. Budget numbers due Thursday (Owner: Them)
2. Final review call Friday morning

---
```
