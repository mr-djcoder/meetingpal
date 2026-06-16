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
    claude_model: Literal["claude-sonnet-4-6", "claude-opus-4-6"] = "claude-sonnet-4-6"
    mic_device_index: int | None = None
    loopback_device_index: int | None = None
    auto_save: bool = True
    save_path: str = field(default_factory=lambda: DEFAULT_SAVE_PATH)
    font_size: int = 14
    theme: Literal["dark", "light"] = "dark"
    onboarding_completed: bool = False
    always_on_top: bool = False
    window_opacity: float = 1.0


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


def save_session(session: "RecordingSession", prefs: UserPreferences) -> str:
    """Write transcript.md and qa_log.md to a dated session folder.

    Returns the absolute path to the created folder.
    """
    from backend.models import ChatMessage, TranscriptSegment  # avoid circular

    started = session.started_at
    folder_name = started.strftime("%Y-%m-%d_%H-%M")
    folder = Path(prefs.save_path) / folder_name
    folder.mkdir(parents=True, exist_ok=True)

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
