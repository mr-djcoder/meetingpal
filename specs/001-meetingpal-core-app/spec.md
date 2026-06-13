# Feature Specification: MeetingPal — Real-Time Meeting Transcription & AI Assistant

**Feature Branch**: `001-meetingpal-core-app`
**Created**: 2026-03-12
**Status**: Draft
**Input**: User description: Full MeetingPal desktop application — WASAPI audio capture, local transcription, speaker diarization, Claude AI Q&A, split-pane UI, onboarding wizard, settings, local storage.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Live Transcription During a Meeting (Priority: P1)

A busy professional joins a video call (on any platform — Google Meet, Teams, Zoom, Slack, or Hangouts). They open MeetingPal, click **Start Recording**, and the app begins capturing all audio playing through their speakers and their own microphone simultaneously — no extra setup, no driver installs. Within a few seconds of someone speaking, words appear in the left panel labeled with who said them ("You" for the user, "Them" for the other party). The transcript auto-scrolls as the conversation progresses, color-coded so the user can instantly tell who is speaking.

**Why this priority**: This is the core value proposition of the entire product. Without reliable, near-real-time transcription, nothing else matters.

**Independent Test**: Can be demonstrated standalone by opening the app, clicking Start Recording, speaking for 10 seconds, and verifying labeled transcript lines appear within 4 seconds.

**Acceptance Scenarios**:

1. **Given** the app is open and not recording, **When** the user clicks "Start Recording", **Then** the system begins capturing both microphone input and system speaker output simultaneously.
2. **Given** recording is active and someone speaks, **When** a continuous speech segment ends, **Then** a labeled transcript line appears in the left panel within 4 seconds of the speech occurring.
3. **Given** multiple people take turns speaking, **When** the transcript is displayed, **Then** each block is labeled "You" (blue tint) or "Them" (gray tint) and includes a timestamp.
4. **Given** a period of silence, **When** no speech is detected for several seconds, **Then** no spurious transcript lines are generated and system resources are not wasted.
5. **Given** the transcript feed is longer than the visible panel, **When** a new transcript segment arrives, **Then** the panel automatically scrolls to show the latest entry.

---

### User Story 2 — AI Q&A Against Live Meeting Context (Priority: P1)

During or after a meeting, the user wants an expert opinion on what was discussed. They type a question in the right panel — e.g., "What action items came up?" — and within moments a sharp, concise response streams in, referencing specific things that were actually said in the meeting. Suggested prompt chips let them ask common questions with a single click. The AI response feels like an attentive advisor who was present for the entire conversation.

**Why this priority**: The AI Q&A panel is the differentiating feature — it transforms a passive transcript into actionable intelligence. It is equally critical to the core value.

**Independent Test**: Can be tested by loading a pre-recorded transcript fixture into the backend, typing a question, and verifying the streamed response references content from that transcript.

**Acceptance Scenarios**:

1. **Given** the app has an active or completed transcript, **When** the user types a question and presses Send or Ctrl+Enter, **Then** the AI begins streaming a response within 3 seconds.
2. **Given** a streaming AI response, **When** the response is generating, **Then** tokens appear one by one in the chat panel — not all at once after a delay.
3. **Given** a question like "What did they say about the budget?", **When** the AI answers, **Then** the response directly references budget-related content from the transcript rather than giving a generic answer.
4. **Given** suggested prompt chips ("Summarize so far", "What are the action items?", "Catch me up — I zoned out", "What was just decided?", "Draft a follow-up email"), **When** the user clicks any chip, **Then** the chip text is submitted as a question and a contextual response streams in.
5. **Given** a multi-turn conversation in the chat panel, **When** the user asks a follow-up question, **Then** the AI retains context from previous exchanges in the same session.

---

### User Story 3 — First-Run Onboarding Wizard (Priority: P2)

A new user installs and launches MeetingPal for the first time. A guided 5-step wizard walks them through: entering their AI API key, confirming audio devices (both the microphone and the system speaker capture source are auto-detected and shown by name), running a quick audio test to verify both channels are working, viewing a short demo transcript with a mock AI response, and finally arriving at a "You're ready!" screen. The entire setup takes under 5 minutes.

**Why this priority**: First-run experience determines whether new users succeed or give up. Audio device configuration is the most common failure point and must be handled gracefully before the user ever tries to record.

**Independent Test**: Can be tested by clearing app state to simulate first run, launching the app, and walking through all 5 wizard steps to verify the flow completes and the main UI appears.

**Acceptance Scenarios**:

1. **Given** the app has never been run before (no stored API key), **When** the user launches the app, **Then** the onboarding wizard appears instead of the main interface.
2. **Given** Step 1 (API key entry), **When** the user enters a valid API key and proceeds, **Then** the key is stored securely in the OS credential store — never written to a file in plain text.
3. **Given** Step 2 (audio setup), **When** the step loads, **Then** the system automatically detects and displays the default system-audio capture device and the default microphone by their actual device names for user confirmation.
4. **Given** Step 3 (audio test), **When** the user plays a test clip, **Then** the waveform visualizer shows activity on both the microphone and system audio channels.
5. **Given** Step 4 (demo), **When** the demo plays, **Then** a sample transcript appears line by line and a mock AI response is displayed, illustrating the core workflow.
6. **Given** Step 5 (ready screen), **When** the user clicks "Start Using MeetingPal", **Then** the wizard closes and the main split-pane interface appears.

---

### User Story 4 — Settings & Customization (Priority: P3)

An experienced user wants to tune MeetingPal for their environment: switch to a higher-accuracy transcription model for an important meeting, choose a different microphone, change the AI model, adjust the transcript font size, toggle dark/light mode, and configure where meeting recordings are saved. All preferences persist across app restarts.

**Why this priority**: Settings are important for power users and edge-case hardware setups but the app delivers value without any customization.

**Independent Test**: Can be tested by opening Settings, changing each option, closing and reopening the app, and verifying all changes persist.

**Acceptance Scenarios**:

1. **Given** the Settings screen, **When** the user selects a different transcription quality level, **Then** subsequent transcriptions use that quality level until changed again.
2. **Given** multiple audio input devices, **When** the user selects a different microphone in Settings, **Then** new recordings capture audio from that device.
3. **Given** the API key field in Settings, **When** the user updates the API key, **Then** the new key is stored securely and used for all subsequent AI requests.
4. **Given** the auto-save toggle is enabled, **When** a recording session ends, **Then** the transcript is automatically saved to the configured folder without requiring user action.
5. **Given** the font size slider, **When** the user adjusts it, **Then** transcript text size updates immediately in the live preview.

---

### User Story 5 — Transcript Export & Session Persistence (Priority: P3)

After a meeting ends, the user clicks "Stop Recording". The transcript and Q&A log are saved to a dated folder in their Documents. They can also manually copy the transcript text or export it as a `.txt` or `.md` file at any time during or after a session, without needing to stop recording first.

**Why this priority**: Export and persistence are important for the user's workflow after meetings but do not affect in-meeting value.

**Independent Test**: Can be tested by running a recording session, stopping it, and verifying two files (transcript and Q&A log) appear in the expected folder with correct content.

**Acceptance Scenarios**:

1. **Given** an active or completed recording, **When** the user clicks "Stop Recording", **Then** the session's transcript and Q&A conversation are saved to a folder named with the date and time of the recording.
2. **Given** a transcript in progress, **When** the user clicks "Copy Transcript", **Then** the full transcript text is placed on the system clipboard.
3. **Given** a transcript in progress, **When** the user clicks "Export", **Then** they can choose `.txt` or `.md` format and save the file to any location.
4. **Given** a saved recording folder, **When** the user opens it in their file manager, **Then** they find a human-readable transcript file and a Q&A log file.

---

### Edge Cases

- What happens when no speech is detected for the entire recording session? (Empty transcript — no errors shown, "No speech detected" placeholder.)
- What happens when the AI API key is invalid or the API is unreachable? (Clear error message in the chat panel; transcription continues unaffected.)
- What happens when the system has no WASAPI-capable audio output device? (Onboarding Step 2 shows an error explaining the requirement; the user can still proceed with microphone-only capture.)
- What happens when the user's meeting exceeds 4 hours? (The transcript context window uses a sliding window — older segments are dropped from AI context but remain visible in the transcript panel and saved to disk.)
- What happens when the user's disk is full and auto-save is enabled? (A non-blocking warning is shown; recording and transcription continue in memory.)
- What happens when the user switches audio output device mid-meeting (e.g., headphones plugged in)? (Audio capture continues from the originally selected device or gracefully reconnects to the new default device with a status indicator update.)
- What happens when two people speak simultaneously? (Transcription captures the mixed audio as best it can; diarization may produce a single attributed segment rather than splitting overlapping speech.)

---

## Requirements *(mandatory)*

### Functional Requirements

**Audio Capture**

- **FR-001**: The system MUST capture system speaker output (all audio playing on the device) simultaneously with microphone input, mixing both into a single audio stream for transcription.
- **FR-002**: Audio capture MUST work without requiring any third-party drivers, virtual audio cables, or additional software installation on Windows 10 or Windows 11.
- **FR-003**: The system MUST allow the user to select both the microphone input device and the system audio capture device independently from a list of available devices.
- **FR-004**: The system MUST apply voice activity detection to automatically skip silent periods and avoid transcribing background noise or silence.

**Transcription**

- **FR-005**: All audio transcription MUST be performed locally on the user's device — no audio data may be sent to any external server or service.
- **FR-006**: Transcription MUST produce labeled segments identifying whether speech came from the user ("You") or another participant ("Them").
- **FR-007**: Each transcript segment MUST include the speaker label, a timestamp, and the transcribed text.
- **FR-008**: Transcript segments MUST begin appearing in the UI within 4 seconds of the corresponding speech ending during a live recording.
- **FR-009**: The user MUST be able to select from at least three transcription quality levels (fast/default, balanced, accurate) with higher quality levels trading speed for accuracy.

**AI Q&A**

- **FR-010**: The system MUST allow the user to ask questions in natural language and receive responses that are contextually grounded in the current meeting transcript.
- **FR-011**: AI responses MUST stream to the user token by token — not appear all at once after a delay.
- **FR-012**: The system MUST maintain multi-turn conversation history within a session so the user can ask follow-up questions without re-stating context.
- **FR-013**: The AI context MUST include the full transcript up to approximately 4 hours of meeting content; beyond that, a sliding window retaining the most recent content MUST be used.
- **FR-014**: The UI MUST provide at least 5 one-click suggested prompt chips ("Summarize so far", "What are the action items?", "Catch me up — I zoned out", "What was just decided?", "Draft a follow-up email").
- **FR-015**: The user MUST be able to select between at least two AI model tiers (standard and high-capability) in Settings.

**User Interface**

- **FR-016**: The main window MUST use a resizable split-pane layout with the live transcript on the left (~60% default) and the AI chat panel on the right (~40% default).
- **FR-017**: The transcript panel MUST auto-scroll to the latest segment as new content arrives; the user MUST be able to manually scroll up to review earlier content without the auto-scroll fighting them.
- **FR-018**: The top bar MUST show a prominent Start/Stop Recording toggle, a recording status indicator (red dot when active), and a running meeting timer.
- **FR-019**: The UI MUST include a collapsible audio waveform visualizer showing live levels for both the microphone and system audio capture channels.
- **FR-020**: The user MUST be able to copy the full transcript to the clipboard or export it as a `.txt` or `.md` file at any time.

**Settings & Configuration**

- **FR-021**: The AI API key MUST be stored exclusively in the operating system's secure credential store — never written to disk in plain text, never logged, never exposed in the UI after initial entry.
- **FR-022**: The settings screen MUST allow configuration of: API key, transcription quality level, microphone device, system audio capture device, AI model tier, auto-save toggle, save folder location, transcript font size, and dark/light mode.
- **FR-023**: All user preferences MUST persist across application restarts.

**Onboarding**

- **FR-024**: On first launch (no stored API key), the application MUST display a guided setup wizard before showing the main interface.
- **FR-025**: The onboarding wizard MUST auto-detect and display the names of the default microphone and system audio capture device for user confirmation.
- **FR-026**: The onboarding wizard MUST include an audio test step that visually confirms both the microphone and system audio channels are receiving signal.
- **FR-027**: The onboarding wizard MUST include a demo step showing a sample transcript and mock AI response so the user understands the product before their first real meeting.

**Storage & Export**

- **FR-028**: When auto-save is enabled and a recording session ends, the system MUST automatically save the full transcript as a markdown file and the Q&A conversation log as a separate markdown file in a folder named with the session date and time.
- **FR-029**: The default save location MUST be the user's Documents folder; this location MUST be configurable in Settings.

### Key Entities

- **Recording Session**: A bounded meeting capture event with a start time, stop time, and an ordered list of transcript segments. A session may be active (recording) or completed.
- **Transcript Segment**: A single unit of transcribed speech. Attributes: speaker label (You / Them), timestamp (wall-clock time), text content, finality flag (interim vs. confirmed).
- **Chat Message**: A single turn in the AI Q&A conversation. Attributes: role (user / assistant), content, timestamp. Belongs to a recording session.
- **Audio Device**: A capturable audio source or destination on the user's system. Attributes: device name, type (microphone input vs. system audio capture), availability.
- **User Preferences**: Persistent user configuration. Attributes: API key reference (not the key itself), transcription quality level, selected devices, AI model tier, save location, font size, theme, auto-save flag.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Transcript lines appear within 4 seconds of the corresponding speech segment ending during a live recording session.
- **SC-002**: The app installs and completes first-run onboarding in under 5 minutes on a standard Windows 10 or 11 machine with no pre-installed dependencies.
- **SC-003**: AI responses begin streaming within 3 seconds of the user submitting a question.
- **SC-004**: The app correctly captures both sides of a meeting (user microphone + remote participant audio) on at least Google Meet, Teams, Zoom, Slack Huddle, and Google Hangouts without platform-specific configuration.
- **SC-005**: 100% of audio transcription occurs on the local device — zero audio bytes are transmitted to any external server under any user workflow.
- **SC-006**: The API key persists in the secure credential store and is automatically retrieved on restart — the user never needs to re-enter it.
- **SC-007**: Saved transcript and Q&A log files are present in the expected folder within 5 seconds of clicking "Stop Recording" when auto-save is enabled.
- **SC-008**: The app runs without degradation across a 2-hour continuous recording session on a mid-range Windows laptop (8 GB RAM, 4-core CPU).
- **SC-009**: A new user with no prior knowledge of the app can complete onboarding and make their first AI query without consulting any documentation.
- **SC-010**: Speaker labels ("You" / "Them") are correctly applied in at least 80% of transcript segments during a standard two-party meeting.

---

## Assumptions

- The target user is a Windows 10 or Windows 11 (64-bit) user only. No other operating systems are in scope.
- Meetings are assumed to be primarily two-party (user + one remote participant). Multi-speaker meetings are supported on a best-effort basis with diarization labeled as "You" and "Them" only.
- The user must supply their own Anthropic API key; the app does not provide or proxy API access.
- System audio capture requires the user's audio to be routed through a standard Windows audio output device (speakers or headphones). Exotic virtual audio routing setups may not work without manual device selection.
- Meeting transcripts are in English by default. Multilingual support is out of scope for this specification.
- No cloud sync, account system, or telemetry of any kind is in scope.
- The app does not need to record video — audio only.
- Transcript retention policy: transcripts are kept locally indefinitely until the user manually deletes them; there is no automatic purge.