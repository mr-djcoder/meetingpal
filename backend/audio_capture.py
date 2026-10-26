"""WASAPI loopback + microphone capture via PyAudioWPatch.

Both sources use PortAudio *callback* streams, so no thread ever blocks in a read.
(Blocking reads on a WASAPI loopback stall during silence, and tearing the stream down
under a blocked read was a source of 0xC0000005 access violations.) Each source feeds a
native-rate ring buffer; one emit thread cuts it into 0.5s frames, resamples them to
16 kHz mono, and hands them to the chunk callback.
"""
from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pyaudiowpatch as pyaudio
from scipy.signal import resample_poly

from backend.models import AudioDevice

TARGET_RATE = 16000
LOOPBACK_RATE = 44100
FRAME_S = 0.5
FRAME_SAMPLES = int(FRAME_S * TARGET_RATE)  # 0.5s frame = 8000 samples @ 16kHz
RING_SECONDS = 10.0       # per-source buffer cap; oldest audio is dropped beyond this
LEVEL_WINDOW_S = 3.0      # window for the meter RMS
CALLBACK_FRAMES = 1024
EMIT_POLL_S = 0.05
# A source that delivers no samples for this long is treated as silent: WASAPI loopback
# produces nothing while no audio plays, so we synthesize silent frames in wall-clock
# time. Downstream (utterance finalization, cloud keep-alive) relies on a steady stream.
SILENCE_GAP_S = 0.6


class _Ring:
    """Thread-safe FIFO of float32 samples plus a rolling RMS over the recent past."""

    def __init__(self, max_samples: int, level_window: int) -> None:
        self._chunks: deque[np.ndarray] = deque()
        self._len = 0
        self._max = max_samples
        self._lock = threading.Lock()
        self._energy: deque[tuple[int, float]] = deque()  # (n, sum of squares)
        self._level_window = level_window
        self._e_n = 0
        self._e_sum = 0.0

    def __len__(self) -> int:
        return self._len

    def append(self, arr: np.ndarray) -> None:
        if arr.size == 0:
            return
        with self._lock:
            self._chunks.append(arr)
            self._len += arr.size
            while self._len > self._max and self._chunks:
                self._len -= self._chunks.popleft().size  # drop oldest audio
            sq = float(np.dot(arr, arr))
            self._energy.append((arr.size, sq))
            self._e_n += arr.size
            self._e_sum += sq
            while len(self._energy) > 1 and self._e_n - self._energy[0][0] >= self._level_window:
                n, e = self._energy.popleft()
                self._e_n -= n
                self._e_sum -= e

    def read(self, n: int) -> np.ndarray | None:
        """Pop exactly n samples, or None (buffer untouched) if fewer are available."""
        with self._lock:
            if self._len < n:
                return None
            return self._take(n)

    def read_all(self) -> np.ndarray:
        with self._lock:
            return self._take(self._len)

    def _take(self, n: int) -> np.ndarray:
        out = np.empty(n, dtype=np.float32)
        filled = 0
        while filled < n:
            chunk = self._chunks.popleft()
            need = n - filled
            if chunk.size <= need:
                out[filled : filled + chunk.size] = chunk
                filled += chunk.size
            else:
                out[filled:] = chunk[:need]
                self._chunks.appendleft(chunk[need:])
                filled = n
        self._len -= n
        return out

    def rms(self) -> float:
        with self._lock:
            if self._e_n <= 0:
                return 0.0
            return min(1.0, math.sqrt(max(self._e_sum, 0.0) / self._e_n))


def to_16k_frame(raw: np.ndarray, native_rate: int) -> np.ndarray:
    """Resample one native-rate block to exactly FRAME_SAMPLES of 16 kHz mono float32.

    Whole 0.5s blocks are resampled at once (polyphase), so filter edge effects occur
    twice a second instead of at every small PortAudio buffer.
    """
    if native_rate == TARGET_RATE:
        out = raw
    else:
        g = math.gcd(TARGET_RATE, native_rate)
        out = resample_poly(raw, TARGET_RATE // g, native_rate // g)
    out = np.asarray(out, dtype=np.float32)
    if out.size < FRAME_SAMPLES:
        out = np.pad(out, (0, FRAME_SAMPLES - out.size))
    elif out.size > FRAME_SAMPLES:
        out = out[:FRAME_SAMPLES]
    return np.clip(out, -1.0, 1.0)


def downmix(interleaved: np.ndarray, channels: int) -> np.ndarray:
    """Average interleaved channels to mono (any channel count, not just stereo)."""
    if channels <= 1:
        return interleaved
    usable = (interleaved.size // channels) * channels
    return interleaved[:usable].reshape(-1, channels).mean(axis=1).astype(np.float32)


@dataclass
class _Source:
    name: str  # "mic" or "loopback"
    device_index: int
    native_rate: int
    channels: int
    ring: _Ring
    last_data_at: float = field(default_factory=time.monotonic)
    last_emit_at: float = field(default_factory=time.monotonic)
    stream: object | None = None

    @property
    def frame_native(self) -> int:
        return max(1, int(round(FRAME_S * self.native_rate)))


class AudioCapture:
    """Captures mic + WASAPI loopback and emits 0.5s 16 kHz mono frames per source."""

    def __init__(
        self,
        chunk_callback: Callable[[str, np.ndarray, float], None],
        mic_device_index: int | None = None,
        loopback_device_index: int | None = None,
        now_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self._chunk_callback = chunk_callback
        self._mic_idx = mic_device_index
        self._loopback_idx = loopback_device_index
        self._now = now_fn
        self._pa = pyaudio.PyAudio()
        self._sources: dict[str, _Source] = {}
        self._stop_event = threading.Event()
        self._emit_thread: threading.Thread | None = None

    # ── lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> list[str]:
        """Open both streams and start emitting. Returns a message per source that
        failed to open; raises RuntimeError if neither source could be opened."""
        self._stop_event.clear()
        failures: list[str] = []
        for name, opener in (("mic", self._open_mic), ("loopback", self._open_loopback)):
            try:
                opener()
            except Exception as exc:
                failures.append(f"{name} unavailable: {exc}")
        if not self._sources:
            self._terminate_pa()
            raise RuntimeError("; ".join(failures) or "no audio source could be opened")
        self._emit_thread = threading.Thread(target=self._emit_loop, daemon=True)
        self._emit_thread.start()
        return failures

    def stop(self) -> None:
        self._stop_event.set()
        # Callback streams: stopping from this thread cannot race a blocked read.
        for src in self._sources.values():
            stream = src.stream
            src.stream = None
            if stream is None:
                continue
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                pass
        if self._emit_thread:
            self._emit_thread.join(timeout=5)
        self._terminate_pa()

    def _terminate_pa(self) -> None:
        try:
            self._pa.terminate()
        except Exception:
            pass

    # ── levels ───────────────────────────────────────────────────────────────

    def get_mic_rms(self) -> float:
        src = self._sources.get("mic")
        return src.ring.rms() if src else 0.0

    def get_loopback_rms(self) -> float:
        src = self._sources.get("loopback")
        return src.ring.rms() if src else 0.0

    # ── stream setup ─────────────────────────────────────────────────────────

    def _open_mic(self) -> None:
        if self._mic_idx is not None:
            info = self._pa.get_device_info_by_index(self._mic_idx)
        else:
            info = self._get_default_mic_info()
        self._open("mic", info, channels=1)

    def _open_loopback(self) -> None:
        if self._loopback_idx is not None:
            info = self._pa.get_device_info_by_index(self._loopback_idx)
        else:
            info = self._get_default_loopback_info()
        self._open("loopback", info, channels=max(1, int(info.get("maxInputChannels", 2))))

    def _open(self, name: str, info: dict, channels: int) -> None:
        rate = int(info.get("defaultSampleRate", TARGET_RATE if name == "mic" else LOOPBACK_RATE))
        src = _Source(
            name=name,
            device_index=int(info["index"]),
            native_rate=rate,
            channels=channels,
            ring=_Ring(int(RING_SECONDS * rate), int(LEVEL_WINDOW_S * rate)),
            last_data_at=self._now(),
            last_emit_at=self._now(),
        )
        src.stream = self._pa.open(
            format=pyaudio.paFloat32,
            channels=channels,
            rate=rate,
            input=True,
            input_device_index=src.device_index,
            frames_per_buffer=CALLBACK_FRAMES,
            stream_callback=self._make_callback(src),
        )
        self._sources[name] = src

    def _make_callback(self, src: _Source):
        def callback(in_data, frame_count, time_info, status):
            try:
                arr = np.frombuffer(in_data, dtype=np.float32)
                mono = np.clip(downmix(arr, src.channels), -1.0, 1.0)
                src.ring.append(mono)
                src.last_data_at = self._now()
            except Exception:
                pass  # never raise into PortAudio's thread
            return (None, pyaudio.paContinue)

        return callback

    # ── frame emission ───────────────────────────────────────────────────────

    def _emit_loop(self) -> None:
        while not self._stop_event.is_set():
            time.sleep(EMIT_POLL_S)
            self.pump()

    def pump(self) -> None:
        """Emit every frame that is ready right now (one pass over both sources)."""
        now = self._now()
        for src in list(self._sources.values()):
            while True:
                frame = self._next_frame(src, now)
                if frame is None:
                    break
                self._chunk_callback(src.name, frame, src.ring.rms())

    def _next_frame(self, src: _Source, now: float) -> np.ndarray | None:
        raw = src.ring.read(src.frame_native)
        if raw is not None:
            src.last_emit_at = now
            return to_16k_frame(raw, src.native_rate)
        if now - src.last_data_at < SILENCE_GAP_S:
            return None  # data is flowing; wait for a full frame
        if len(src.ring):
            # Audio stopped mid-frame: flush the remainder, zero-padded to a full frame.
            tail = src.ring.read_all()
            src.last_emit_at = now
            return to_16k_frame(np.pad(tail, (0, src.frame_native - tail.size)), src.native_rate)
        if now - src.last_emit_at >= FRAME_S:
            src.last_emit_at = now
            return np.zeros(FRAME_SAMPLES, dtype=np.float32)
        return None

    # ── default devices ──────────────────────────────────────────────────────

    def _get_default_mic_info(self) -> dict:
        try:
            return self._pa.get_default_input_device_info()
        except OSError:
            return self._pa.get_device_info_by_index(0)

    def _get_default_loopback_info(self) -> dict:
        try:
            return self._pa.get_default_wasapi_loopback()
        except Exception:
            # Fallback: scan for a loopback device
            for i in range(self._pa.get_device_count()):
                info = self._pa.get_device_info_by_index(i)
                if "loopback" in info.get("name", "").lower():
                    return info
            raise RuntimeError("No WASAPI loopback device found")


def enumerate_devices(pa: pyaudio.PyAudio | None = None) -> list[AudioDevice]:
    """Return all microphone and WASAPI loopback devices."""
    owned = pa is None
    if pa is None:
        pa = pyaudio.PyAudio()
    devices: list[AudioDevice] = []
    try:
        default_mic = pa.get_default_input_device_info()
        default_mic_idx = int(default_mic["index"])
    except OSError:
        default_mic_idx = -1

    try:
        default_lb = pa.get_default_wasapi_loopback()
        default_lb_idx = int(default_lb["index"])
    except Exception:
        default_lb_idx = -1

    for i in range(pa.get_device_count()):
        info = pa.get_device_info_by_index(i)
        name: str = info.get("name", "")
        is_loopback = "loopback" in name.lower() or info.get("isLoopbackDevice", False)

        if is_loopback:
            devices.append(AudioDevice(
                index=i,
                name=name,
                device_type="loopback",
                channels=2,
                default_sample_rate=float(info.get("defaultSampleRate", LOOPBACK_RATE)),
                is_default=(i == default_lb_idx),
            ))
        elif info.get("maxInputChannels", 0) > 0:
            devices.append(AudioDevice(
                index=i,
                name=name,
                device_type="microphone",
                channels=int(info.get("maxInputChannels", 1)),
                default_sample_rate=float(info.get("defaultSampleRate", TARGET_RATE)),
                is_default=(i == default_mic_idx),
            ))

    if owned:
        pa.terminate()
    return devices
