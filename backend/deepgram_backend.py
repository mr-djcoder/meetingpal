# backend/deepgram_backend.py
"""Deepgram cloud transcription backend — two WS connections, one per source."""
from __future__ import annotations

import numpy as np


def pcm_float32_to_int16(frame: np.ndarray) -> bytes:
    """Convert float32 [-1, 1] mono audio to little-endian int16 PCM bytes."""
    clipped = np.clip(frame, -1.0, 1.0)
    return (clipped * 32767.0).astype("<i2").tobytes()
