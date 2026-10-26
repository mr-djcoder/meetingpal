"""Session persistence and user preferences storage."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from backend.models import ChatMessage, RecordingSession, TranscriptSegment

APPDATA = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
PREFS_DIR = Path(APPDATA) / "MeetingPal"
PREFS_FILE = PREFS_DIR / "preferences.json"

DEFAULT_SAVE_PATH = str(
    Path.home() / "Documents" / "MeetingPal" / "recordings"
)


@dataclass
class UserPreferences:
    whisper_model: Literal["base.en", "small.en", "medium.en"] = "base.en"
    chat_provider: Literal["claude", "gemini", "ollama"] = "claude"  # who answers the chat panel
    chat_gemini_model: str = "gemini-3.5-flash"
    chat_ollama_model: str = "qwen3.5:27b"
    claude_model: str = "claude-sonnet-4-6"  # widened — new Claude IDs (haiku-4-5, opus-4-8)
    mic_device_index: int | None = None
    loopback_device_index: int | None = None
    auto_save: bool = True
    save_path: str = field(default_factory=lambda: DEFAULT_SAVE_PATH)
    font_size: int = 14
    theme: Literal["dark", "light"] = "dark"
    onboarding_completed: bool = False
    auto_answer_enabled: bool = False
    auto_answer_prompt: str = (
        "You are me in this conversation. Answer the other person's question "
        "concisely, in the first person, using the meeting context."
    )
    auto_answer_provider: str = "claude"
    auto_answer_model: str = "claude-haiku-4-5-20251001"
    chat_panel_visible: bool = True
    custom_titlebar: bool = True
    window_opacity: float = 1.0
    always_on_top: bool = False
    transcription_engine: Literal["local", "cloud"] = "local"
    cloud_provider: str = "deepgram"
    local_transcribe_mode: Literal["streaming", "legacy"] = "streaming"
    transcript_split: float = 60.0  # % width of the transcript panel
    transcript_visible: bool = False
    suppress_echo: bool = True  # drop mic text that duplicates the other side (speakers, no headset)


def load_preferences() -> UserPreferences:
    """Load preferences from disk, returning defaults if file does not exist."""
    if not PREFS_FILE.exists():
        return UserPreferences()
    try:
        with open(PREFS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        defaults = asdict(UserPreferences())
        defaults.update({k: v for k, v in data.items() if k in defaults})
        return UserPreferences(**defaults)
    except Exception:
        return UserPreferences()


def save_preferences(prefs: UserPreferences) -> None:
    """Atomically write preferences to disk."""
    PREFS_DIR.mkdir(parents=True, exist_ok=True)
    data = asdict(prefs)
    fd, tmp_path = tempfile.mkstemp(dir=PREFS_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, PREFS_FILE)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


JOURNAL_NAME = "segments.jsonl"


def allocate_session_folder(session: "RecordingSession", prefs: UserPreferences) -> Path:
    """Create (once) and return this session's output folder.

    Named to the second, with a numeric suffix on collision, so two sessions started
    close together never overwrite each other. The path is cached on the session.
    """
    if session.folder:
        return Path(session.folder)
    base = Path(prefs.save_path) / session.started_at.strftime("%Y-%m-%d_%H-%M-%S")
    folder = base
    n = 2
    while folder.exists():
        folder = base.with_name(f"{base.name}_{n}")
        n += 1
    folder.mkdir(parents=True, exist_ok=True)
    session.folder = str(folder)
    return folder


def journal_segment(session: "RecordingSession", prefs: UserPreferences, seg: "TranscriptSegment") -> None:
    """Append one finalized segment to the session journal (survives a sidecar crash)."""
    folder = allocate_session_folder(session, prefs)
    record = {
        "id": seg.id,
        "speaker": seg.speaker,
        "time": seg.wall_clock_time.isoformat(),
        "offset": seg.session_offset_seconds,
        "text": seg.text,
    }
    with open(folder / JOURNAL_NAME, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def save_session(session: "RecordingSession", prefs: UserPreferences) -> str:
    """Write transcript.md and qa_log.md to the session folder.

    Returns the absolute path to the created folder.
    """
    started = session.started_at
    folder = allocate_session_folder(session, prefs)

    # transcript.md
    duration_str = _format_duration(session)
    lines = [
        "# Meeting Transcript",
        f"**Date**: {started.strftime('%Y-%m-%d')} | **Duration**: {duration_str}",
        "",
        "---",
        "",
    ]
    for seg in session.segments:
        ts = seg.wall_clock_time.strftime("%I:%M %p").lstrip("0")
        lines.append(f"**[{ts}] {seg.speaker}**: {seg.text}")
        lines.append("")

    (folder / "transcript.md").write_text("\n".join(lines), encoding="utf-8")

    # qa_log.md
    session_label = started.strftime("%Y-%m-%d_%H-%M")
    qa_lines = [
        "# Q&A Log",
        f"**Date**: {started.strftime('%Y-%m-%d')} | **Session**: {session_label}",
        "",
        "---",
        "",
    ]
    messages = session.chat_messages
    for i in range(0, len(messages) - 1, 2):
        user_msg = messages[i]
        asst_msg = messages[i + 1] if i + 1 < len(messages) else None
        ts = user_msg.created_at.strftime("%I:%M %p").lstrip("0")
        qa_lines.append(f"**[{ts}] You asked**: {user_msg.content}")
        qa_lines.append("")
        if asst_msg:
            ats = asst_msg.created_at.strftime("%I:%M %p").lstrip("0")
            qa_lines.append(f"**[{ats}] MeetingPal**: {asst_msg.content}")
            qa_lines.append("")
        qa_lines.append("---")
        qa_lines.append("")

    (folder / "qa_log.md").write_text("\n".join(qa_lines), encoding="utf-8")

    return str(folder)


def _format_duration(session: "RecordingSession") -> str:
    end = session.stopped_at or datetime.now()
    total = int((end - session.started_at).total_seconds())
    m, s = divmod(total, 60)
    return f"{m:02d}:{s:02d}"
