from collections import deque

import numpy as np

from backend.audio_capture import drain_frame


def test_drain_frame_returns_none_when_short():
    buf = deque([0.1, 0.2, 0.3])
    assert drain_frame(buf, 4) is None
    assert len(buf) == 3  # untouched


def test_drain_frame_pops_exactly_n_as_float32():
    buf = deque([float(i) for i in range(10)])
    out = drain_frame(buf, 4)
    assert out is not None
    assert out.dtype == np.float32
    assert list(out) == [0.0, 1.0, 2.0, 3.0]
    assert len(buf) == 6  # 4 consumed from the front


def test_drain_frame_exact_length():
    buf = deque([1.0, 2.0])
    out = drain_frame(buf, 2)
    assert list(out) == [1.0, 2.0]
    assert len(buf) == 0
