from backend.storage import UserPreferences


def test_backend_prefs_defaults():
    p = UserPreferences()
    assert p.transcription_engine == "local"
    assert p.cloud_provider == "deepgram"
    assert p.local_transcribe_mode == "streaming"
