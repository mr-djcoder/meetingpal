import importlib


def test_auto_answer_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    import backend.storage as storage
    importlib.reload(storage)

    prefs = storage.UserPreferences()
    assert prefs.auto_answer_enabled is False
    assert prefs.auto_answer_provider == "claude"
    assert prefs.auto_answer_model == "claude-haiku-4-5-20251001"
    assert "first person" in prefs.auto_answer_prompt


def test_auto_answer_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    import backend.storage as storage
    importlib.reload(storage)

    prefs = storage.UserPreferences(
        auto_answer_enabled=True,
        auto_answer_prompt="Custom",
        auto_answer_provider="gemini",
        auto_answer_model="gemini-3.5-flash",
    )
    storage.save_preferences(prefs)
    loaded = storage.load_preferences()
    assert loaded.auto_answer_enabled is True
    assert loaded.auto_answer_prompt == "Custom"
    assert loaded.auto_answer_provider == "gemini"
    assert loaded.auto_answer_model == "gemini-3.5-flash"


def test_old_prefs_file_still_loads(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    import backend.storage as storage
    importlib.reload(storage)

    storage.PREFS_DIR.mkdir(parents=True, exist_ok=True)
    storage.PREFS_FILE.write_text('{"theme": "dark"}', encoding="utf-8")
    loaded = storage.load_preferences()
    assert loaded.auto_answer_enabled is False
    assert loaded.auto_answer_provider == "claude"


def _reload(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    import backend.storage as storage
    importlib.reload(storage)
    return storage


def _session(started):
    from backend.models import RecordingSession, TranscriptSegment
    s = RecordingSession(started_at=started)
    s.segments.append(TranscriptSegment(id="a", speaker="You", text="hello", is_final=True))
    return s


def test_same_minute_sessions_get_distinct_folders(tmp_path, monkeypatch):
    from datetime import datetime
    storage = _reload(tmp_path, monkeypatch)
    prefs = storage.UserPreferences(save_path=str(tmp_path / "rec"))
    started = datetime(2026, 3, 1, 9, 30, 15)
    first, second = _session(started), _session(started)
    f1 = storage.save_session(first, prefs)
    f2 = storage.save_session(second, prefs)
    assert f1 != f2
    assert (tmp_path / "rec").exists() and len(list((tmp_path / "rec").iterdir())) == 2


def test_folder_is_allocated_once_per_session(tmp_path, monkeypatch):
    from datetime import datetime
    storage = _reload(tmp_path, monkeypatch)
    prefs = storage.UserPreferences(save_path=str(tmp_path / "rec"))
    s = _session(datetime(2026, 3, 1, 9, 30, 15))
    assert storage.allocate_session_folder(s, prefs) == storage.allocate_session_folder(s, prefs)
    assert storage.save_session(s, prefs) == s.folder


def test_journal_survives_without_save_session(tmp_path, monkeypatch):
    """A crash before stop must still leave the finalized text on disk."""
    import json
    from datetime import datetime
    storage = _reload(tmp_path, monkeypatch)
    prefs = storage.UserPreferences(save_path=str(tmp_path / "rec"))
    s = _session(datetime(2026, 3, 1, 9, 30, 15))
    storage.journal_segment(s, prefs, s.segments[0])
    lines = (open(f"{s.folder}/segments.jsonl", encoding="utf-8").read().splitlines())
    assert json.loads(lines[0])["text"] == "hello"
