# tests/test_transcriber_mode.py
from backend.transcriber import WhisperTranscriber


def test_assembler_class_by_mode():
    t_stream = WhisperTranscriber(model_name="base.en", transcribe_mode="streaming")
    t_legacy = WhisperTranscriber(model_name="base.en", transcribe_mode="legacy")
    assert t_stream._assembler_cls.__name__ == "StreamingUtteranceAssembler"
    assert t_legacy._assembler_cls.__name__ == "LegacyUtteranceAssembler"


def test_device_defaults_to_unknown_before_load():
    t = WhisperTranscriber(model_name="base.en")
    assert t.device in ("cpu", "cuda", "unknown")


def test_set_transcribe_mode_swaps_assembler():
    t = WhisperTranscriber(model_name="base.en", transcribe_mode="streaming")
    assert t._assembler_cls.__name__ == "StreamingUtteranceAssembler"
    t.set_transcribe_mode("legacy")
    assert t._assembler_cls.__name__ == "LegacyUtteranceAssembler"
    t.set_transcribe_mode("streaming")
    assert t._assembler_cls.__name__ == "StreamingUtteranceAssembler"
