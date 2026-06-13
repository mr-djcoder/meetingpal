import numpy as np

from backend.vad import SileroVAD


def test_silence_is_not_speech():
    vad = SileroVAD()
    silence = np.zeros(int(0.5 * 16000), dtype=np.float32)
    assert vad.is_speech_frame(silence) is False


def test_returns_bool():
    vad = SileroVAD()
    frame = np.zeros(int(0.5 * 16000), dtype=np.float32)
    assert isinstance(vad.is_speech_frame(frame), bool)
