import threading

import numpy as np

from backend.audio_capture import (
    FRAME_SAMPLES,
    SILENCE_GAP_S,
    AudioCapture,
    _Ring,
    _Source,
    downmix,
    to_16k_frame,
)


def test_ring_read_returns_none_when_short_and_leaves_buffer():
    ring = _Ring(1000, 100)
    ring.append(np.arange(3, dtype=np.float32))
    assert ring.read(4) is None
    assert len(ring) == 3


def test_ring_read_pops_exactly_n_across_chunks():
    ring = _Ring(1000, 100)
    ring.append(np.array([0, 1, 2], dtype=np.float32))
    ring.append(np.array([3, 4, 5, 6], dtype=np.float32))
    out = ring.read(5)
    assert out.dtype == np.float32
    assert list(out) == [0, 1, 2, 3, 4]
    assert len(ring) == 2
    assert list(ring.read_all()) == [5, 6]


def test_ring_drops_oldest_beyond_capacity():
    ring = _Ring(5, 100)
    ring.append(np.array([1, 2, 3], dtype=np.float32))
    ring.append(np.array([4, 5, 6], dtype=np.float32))
    assert len(ring) == 3
    assert list(ring.read_all()) == [4, 5, 6]


def test_ring_rms_tracks_recent_window():
    ring = _Ring(10_000, 1000)
    ring.append(np.full(500, 0.5, dtype=np.float32))
    assert abs(ring.rms() - 0.5) < 1e-3
    for _ in range(10):  # push the 0.5 block out of the 1000-sample window
        ring.append(np.zeros(500, dtype=np.float32))
    assert ring.rms() < 0.01


def test_ring_is_thread_safe_under_concurrent_use():
    ring = _Ring(1_000_000, 1000)

    def writer():
        for _ in range(500):
            ring.append(np.ones(100, dtype=np.float32))

    t = threading.Thread(target=writer)
    t.start()
    got = 0
    while t.is_alive() or len(ring) >= 100:
        if ring.read(100) is not None:
            got += 100
    t.join()
    assert got + len(ring) == 500 * 100


def test_to_16k_frame_is_exact_length_for_common_rates():
    for rate in (16000, 22050, 44100, 48000):
        raw = np.zeros(int(0.5 * rate), dtype=np.float32)
        out = to_16k_frame(raw, rate)
        assert out.shape == (FRAME_SAMPLES,)
        assert out.dtype == np.float32


def test_to_16k_frame_preserves_a_tone():
    rate = 48000
    t = np.arange(int(0.5 * rate)) / rate
    raw = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    out = to_16k_frame(raw, rate)
    assert abs(float(np.sqrt(np.mean(out ** 2))) - 0.5 / np.sqrt(2)) < 0.03


def test_downmix_handles_more_than_two_channels():
    six = np.tile(np.array([0.6, 0.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float32), 4)
    mono = downmix(six, 6)
    assert mono.shape == (4,)
    assert np.allclose(mono, 0.1)


def test_downmix_mono_passthrough_and_ragged_tail():
    arr = np.array([1, 2, 3], dtype=np.float32)
    assert downmix(arr, 1) is arr
    assert downmix(np.array([1, 1, 1, 1, 9], dtype=np.float32), 2).shape == (2,)


class _Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def _capture_with_source(clock, rate=16000):
    """AudioCapture wired to a fake clock, without touching PortAudio."""
    cap = AudioCapture.__new__(AudioCapture)
    emitted = []
    cap._chunk_callback = lambda name, frame, rms: emitted.append((name, frame))
    cap._now = clock
    src = _Source(
        name="loopback", device_index=0, native_rate=rate, channels=1,
        ring=_Ring(rate * 10, rate * 3), last_data_at=clock(), last_emit_at=clock(),
    )
    cap._sources = {"loopback": src}
    return cap, src, emitted


def test_pump_emits_full_frames_while_data_flows():
    clock = _Clock()
    cap, src, emitted = _capture_with_source(clock)
    src.ring.append(np.full(FRAME_SAMPLES, 0.2, dtype=np.float32))
    src.last_data_at = clock()
    cap.pump()
    assert len(emitted) == 1
    assert emitted[0][1].shape == (FRAME_SAMPLES,)
    assert float(emitted[0][1][0]) > 0.1


def test_pump_synthesizes_silence_when_source_goes_quiet():
    """WASAPI loopback delivers nothing during silence; downstream still needs frames."""
    clock = _Clock()
    cap, src, emitted = _capture_with_source(clock)
    cap.pump()
    assert emitted == []  # not quiet long enough yet
    clock.t += SILENCE_GAP_S + 0.1
    cap.pump()
    assert len(emitted) == 1
    assert not emitted[0][1].any()
    clock.t += 0.2
    cap.pump()
    assert len(emitted) == 1  # paced at one frame per 0.5s
    clock.t += 0.4
    cap.pump()
    assert len(emitted) == 2


def test_pump_flushes_partial_frame_after_audio_stops():
    clock = _Clock()
    cap, src, emitted = _capture_with_source(clock)
    src.ring.append(np.full(1000, 0.3, dtype=np.float32))
    src.last_data_at = clock()
    cap.pump()
    assert emitted == []  # still waiting for the rest of the frame
    clock.t += SILENCE_GAP_S + 0.1
    cap.pump()
    assert len(emitted) == 1
    frame = emitted[0][1]
    assert frame.shape == (FRAME_SAMPLES,)
    assert float(frame[0]) > 0.2 and float(frame[-1]) == 0.0  # zero-padded remainder
