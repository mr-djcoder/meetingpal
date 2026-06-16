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
