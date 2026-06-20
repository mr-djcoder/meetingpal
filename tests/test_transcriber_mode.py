# tests/test_transcriber_mode.py
import backend.transcriber as tr
from backend.transcriber import WhisperTranscriber


class _FakeWM:
    """Stand-in for faster_whisper.WhisperModel — records how it was constructed."""
    def __init__(self, name, device, compute_type, cpu_threads=0):
        self.name = name
        self.device = device


def _patch_model_load(monkeypatch, cuda: bool):
    monkeypatch.setattr(tr, "_cuda_available", lambda: cuda)
    monkeypatch.setattr(tr, "WhisperModel", _FakeWM)
    monkeypatch.setattr(tr, "SileroVAD", lambda *a, **k: object())


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


def test_gpu_auto_upgrades_to_large_model(monkeypatch):
    _patch_model_load(monkeypatch, cuda=True)
    t = WhisperTranscriber(model_name="base.en")
    t.load_model()
    assert t.device == "cuda"
    assert t.active_model == "distil-large-v3"   # upgraded, not the CPU base.en
    assert t.model_loaded is True


def test_cpu_uses_configured_model(monkeypatch):
    _patch_model_load(monkeypatch, cuda=False)
    t = WhisperTranscriber(model_name="base.en")
    t.load_model()
    assert t.device == "cpu"
    assert t.active_model == "base.en"           # configured model kept on CPU
    assert t.model_loaded is True


def test_gpu_load_failure_falls_back_to_cpu(monkeypatch):
    monkeypatch.setattr(tr, "_cuda_available", lambda: True)
    monkeypatch.setattr(tr, "SileroVAD", lambda *a, **k: object())

    class _WM:
        def __init__(self, name, device, compute_type, cpu_threads=0):
            if device == "cuda":
                raise RuntimeError("no CUDA libs")
            self.name = name
            self.device = device

    monkeypatch.setattr(tr, "WhisperModel", _WM)
    t = WhisperTranscriber(model_name="small.en")
    t.load_model()
    assert t.device == "cpu"
    assert t.active_model == "small.en"
    assert t.model_loaded is True
