import numpy as np

from backend.audio_capture import mix_frame


def test_mix_frame_sums_at_half_gain():
    mic = np.array([1.0, 1.0, 1.0], dtype=np.float32)
    lb = np.array([0.4, 0.4, 0.4], dtype=np.float32)
    out = mix_frame(mic, lb)
    assert np.allclose(out, [0.7, 0.7, 0.7])
    assert out.dtype == np.float32


def test_mix_frame_clips_to_unit_range():
    mic = np.array([1.0, -1.0], dtype=np.float32)
    lb = np.array([1.0, -1.0], dtype=np.float32)
    out = mix_frame(mic, lb)
    assert np.allclose(out, [1.0, -1.0])  # 0.5+0.5 = 1.0, clipped


def test_mix_frame_pads_shorter_source_with_zeros():
    mic = np.array([1.0, 1.0, 1.0, 1.0], dtype=np.float32)
    lb = np.array([1.0, 1.0], dtype=np.float32)
    out = mix_frame(mic, lb)
    assert len(out) == 4
    # lb zero-padded at the front (right-justified by recency)
    assert np.allclose(out, [0.5, 0.5, 1.0, 1.0])
