"""WASAPI loopback + microphone capture via PyAudioWPatch."""
from __future__ import annotations

import threading
from collections import deque
from typing import Callable

import numpy as np
import pyaudiowpatch as pyaudio
from scipy.signal import resample

from backend.models import AudioDevice

TARGET_RATE = 16000
CHUNK_FRAMES = 1024
LOOPBACK_RATE = 44100
ROLLING_MAXLEN = int(3.5 * TARGET_RATE)  # 3.5s worth of samples


class AudioCapture:
    """Captures mic + WASAPI loopback, mixes to 16kHz mono, feeds a RollingBuffer."""

    def __init__(
        self,
        chunk_callback: Callable[[np.ndarray, float, float], None],
        mic_device_index: int | None = None,
        loopback_device_index: int | None = None,
    ) -> None:
        self._chunk_callback = chunk_callback
        self._mic_idx = mic_device_index
        self._loopback_idx = loopback_device_index

        self._pa = pyaudio.PyAudio()
        self._mic_buffer: deque[float] = deque(maxlen=ROLLING_MAXLEN)
        self._loopback_buffer: deque[float] = deque(maxlen=ROLLING_MAXLEN)

        self._stop_event = threading.Event()
        self._mic_thread: threading.Thread | None = None
        self._loopback_thread: threading.Thread | None = None
        self._emit_thread: threading.Thread | None = None

        # samples since last chunk advance
        self._samples_since_last_emit = 0
        self._lock = threading.Lock()

    def start(self) -> None:
        self._stop_event.clear()
        self._mic_thread = threading.Thread(target=self._capture_mic, daemon=True)
        self._loopback_thread = threading.Thread(target=self._capture_loopback, daemon=True)
        self._emit_thread = threading.Thread(target=self._emit_chunks, daemon=True)
        self._mic_thread.start()
        self._loopback_thread.start()
        self._emit_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._mic_thread:
            self._mic_thread.join(timeout=2)
        if self._loopback_thread:
            self._loopback_thread.join(timeout=2)
        if self._emit_thread:
            self._emit_thread.join(timeout=2)
        self._pa.terminate()

    def get_mic_rms(self) -> float:
        buf = list(self._mic_buffer)[-TARGET_RATE * 3 :]
        if not buf:
            return 0.0
        arr = np.array(buf, dtype=np.float32)
        rms = float(np.sqrt(np.mean(arr ** 2)))
        return min(rms, 1.0)

    def get_loopback_rms(self) -> float:
        buf = list(self._loopback_buffer)[-TARGET_RATE * 3 :]
        if not buf:
            return 0.0
        arr = np.array(buf, dtype=np.float32)
        rms = float(np.sqrt(np.mean(arr ** 2)))
        return min(rms, 1.0)

    def _capture_mic(self) -> None:
        mic_info = self._get_default_mic_info()
        native_rate = int(mic_info.get("defaultSampleRate", TARGET_RATE))
        idx = self._mic_idx if self._mic_idx is not None else int(mic_info["index"])
        stream = self._pa.open(
            format=pyaudio.paFloat32,
            channels=1,
            rate=native_rate,
            input=True,
            input_device_index=idx,
            frames_per_buffer=CHUNK_FRAMES,
        )
        try:
            while not self._stop_event.is_set():
                raw = stream.read(CHUNK_FRAMES, exception_on_overflow=False)
                arr = np.frombuffer(raw, dtype=np.float32)
                if native_rate != TARGET_RATE:
                    n_out = int(len(arr) * TARGET_RATE / native_rate)
                    arr = resample(arr, n_out).astype(np.float32)
                arr = np.clip(arr, -1.0, 1.0)
                with self._lock:
                    self._mic_buffer.extend(arr.tolist())
                    # Mic thread drives the emit clock (always streaming).
                    self._samples_since_last_emit += len(arr)
        finally:
            stream.stop_stream()
            stream.close()

    def _capture_loopback(self) -> None:
        loopback_info = self._get_default_loopback_info()
        native_rate = int(loopback_info.get("defaultSampleRate", LOOPBACK_RATE))
        idx = self._loopback_idx if self._loopback_idx is not None else int(loopback_info["index"])
        stream = self._pa.open(
            format=pyaudio.paFloat32,
            channels=loopback_info.get("maxInputChannels", 2),
            rate=native_rate,
            input=True,
            input_device_index=idx,
            frames_per_buffer=CHUNK_FRAMES,
        )
        try:
            while not self._stop_event.is_set():
                raw = stream.read(CHUNK_FRAMES, exception_on_overflow=False)
                arr = np.frombuffer(raw, dtype=np.float32)
                # Convert stereo → mono
                if loopback_info.get("maxInputChannels", 2) == 2:
                    arr = arr.reshape(-1, 2).mean(axis=1)
                # Resample to 16kHz
                if native_rate != TARGET_RATE:
                    n_out = int(len(arr) * TARGET_RATE / native_rate)
                    arr = resample(arr, n_out).astype(np.float32)
                arr = np.clip(arr, -1.0, 1.0)
                with self._lock:
                    self._loopback_buffer.extend(arr.tolist())
        finally:
            stream.stop_stream()
            stream.close()

    def _emit_chunks(self) -> None:
        """Every 2.5s of new samples, emit a 3s chunk to the callback."""
        import time
        ADVANCE_SAMPLES = int(2.5 * TARGET_RATE)
        CHUNK_SAMPLES = int(3.0 * TARGET_RATE)
        while not self._stop_event.is_set():
            time.sleep(0.1)
            with self._lock:
                if self._samples_since_last_emit < ADVANCE_SAMPLES:
                    continue
                # Take the most recent 3s from each clean single-source buffer.
                mic_tail = list(self._mic_buffer)[-CHUNK_SAMPLES:]
                lb_tail = list(self._loopback_buffer)[-CHUNK_SAMPLES:]
                mic_rms = self.get_mic_rms()
                lb_rms = self.get_loopback_rms()
                self._samples_since_last_emit = 0
            chunk = _mix_aligned(mic_tail, lb_tail, CHUNK_SAMPLES)
            if len(chunk) > 0:
                self._chunk_callback(chunk, mic_rms, lb_rms)

    def _get_default_mic_info(self) -> dict:
        try:
            return self._pa.get_default_input_device_info()
        except OSError:
            return {"index": 0, "defaultSampleRate": TARGET_RATE, "maxInputChannels": 1}

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


def _mix_aligned(mic_tail: list[float], lb_tail: list[float], chunk_samples: int) -> np.ndarray:
    """Sum mic + loopback sample-aligned by recency, each at half gain.

    The two source buffers may differ slightly in length (independent native
    rates after resample). Align both to the most-recent `chunk_samples` by
    right-justifying and zero-padding the front of the shorter one.
    """
    def _tail(samples: list[float]) -> np.ndarray:
        arr = np.array(samples[-chunk_samples:], dtype=np.float32)
        if len(arr) < chunk_samples:
            arr = np.concatenate([np.zeros(chunk_samples - len(arr), dtype=np.float32), arr])
        return arr

    if not mic_tail and not lb_tail:
        return np.empty(0, dtype=np.float32)
    mixed = _tail(mic_tail) * 0.5 + _tail(lb_tail) * 0.5
    return np.clip(mixed, -1.0, 1.0)


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
