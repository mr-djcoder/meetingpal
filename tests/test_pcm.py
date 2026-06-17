import numpy as np
from backend.deepgram_backend import pcm_float32_to_int16


def test_pcm_conversion_scales_and_clips():
    x = np.array([0.0, 1.0, -1.0, 2.0, -2.0, 0.5], dtype=np.float32)
    raw = pcm_float32_to_int16(x)
    out = np.frombuffer(raw, dtype="<i2")
    assert out[0] == 0
    assert out[1] == 32767
    assert out[2] == -32767 or out[2] == -32768
    assert out[3] == 32767   # clipped
    assert out[4] <= -32767  # clipped
    assert abs(int(out[5]) - 16383) <= 2
    assert raw.__class__ is bytes
