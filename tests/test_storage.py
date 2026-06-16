import importlib
from dataclasses import asdict


def test_new_overlay_fields_default(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    import backend.storage as storage
    importlib.reload(storage)  # rebind PREFS_DIR/PREFS_FILE under the temp APPDATA

    prefs = storage.UserPreferences()
    assert prefs.always_on_top is False
    assert prefs.window_opacity == 1.0


def test_overlay_fields_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    import backend.storage as storage
    importlib.reload(storage)

    prefs = storage.UserPreferences(always_on_top=True, window_opacity=0.55)
    storage.save_preferences(prefs)
    loaded = storage.load_preferences()
    assert loaded.always_on_top is True
    assert loaded.window_opacity == 0.55


def test_unknown_keys_ignored_old_files_still_load(tmp_path, monkeypatch):
    # An older preferences.json without the new keys must still load with defaults.
    monkeypatch.setenv("APPDATA", str(tmp_path))
    import backend.storage as storage
    importlib.reload(storage)

    storage.PREFS_DIR.mkdir(parents=True, exist_ok=True)
    storage.PREFS_FILE.write_text('{"theme": "dark", "font_size": 14}', encoding="utf-8")
    loaded = storage.load_preferences()
    assert loaded.always_on_top is False
    assert loaded.window_opacity == 1.0
