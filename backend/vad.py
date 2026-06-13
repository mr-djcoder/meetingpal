"""Silero VAD integration — gates audio chunks before transcription."""
from __future__ import annotations

import torch
import numpy as np
from silero_vad import load_silero_vad, get_speech_timestamps

torch.set_num_threads(1)


class SileroVAD:
    def __init__(self, threshold: float = 0.5) -> None:
        self._threshold = threshold
        # Use the pip `silero-vad` package (offline, bundled model weights).
        # Avoids torch.hub.load, which prompts "trust this repo? (y/N)" on stdin
        # and raises EOFError when run as a headless sidecar.
        self._model = load_silero_vad()

    def is_speech(self, chunk: np.ndarray) -> bool:
        """Return True if the chunk contains speech above the threshold."""
        tensor = torch.from_numpy(chunk.copy()).float()
        result = get_speech_timestamps(
            tensor,
            self._model,
            sampling_rate=16000,
            threshold=self._threshold,
        )
        return len(result) > 0

    def is_speech_frame(self, frame: np.ndarray) -> bool:
        """Speech check tuned for short (~0.5s) frames."""
        tensor = torch.from_numpy(frame.copy()).float()
        result = get_speech_timestamps(
            tensor,
            self._model,
            sampling_rate=16000,
            threshold=self._threshold,
            min_speech_duration_ms=100,
        )
        return len(result) > 0

    def reset(self) -> None:
        """Reset VAD state — call between sessions."""
        self._model.reset_states()
