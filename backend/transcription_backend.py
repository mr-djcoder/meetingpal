# backend/transcription_backend.py
"""Pluggable transcription backend interface and the local implementation."""
from __future__ import annotations

from datetime import datetime
from typing import Protocol

import numpy as np


class TranscriptionBackend(Protocol):
    def start(self, session_id: str, started_at: datetime) -> None: ...
    def feed(self, source: str, frame: np.ndarray, rms: float) -> None: ...
    def stop(self) -> None: ...
    def ready(self) -> bool: ...


class LocalBackend:
    """Wraps the existing WhisperTranscriber behind the backend interface."""

    def __init__(self, transcriber) -> None:
        self._t = transcriber

    def start(self, session_id: str, started_at: datetime) -> None:
        self._t.start(session_id, started_at)

    def feed(self, source: str, frame: np.ndarray, rms: float) -> None:
        self._t.enqueue(source, frame, rms)

    def stop(self) -> None:
        self._t.stop()

    def ready(self) -> bool:
        return bool(getattr(self._t, "model_loaded", False))

    @property
    def device(self) -> str:
        return getattr(self._t, "device", "unknown")
