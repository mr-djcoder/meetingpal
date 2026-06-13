"""Speaker diarization — Phase 1: mic/loopback energy heuristic."""
from __future__ import annotations

from typing import Literal

import numpy as np


def get_speaker(mic_rms: float, loopback_rms: float) -> Literal["You", "Them"]:
    """Return 'You' if mic energy dominates, else 'Them'.

    Uses the last-3s RMS from each separate buffer, pre-computed by AudioCapture.
    Conservative tie-break: both channels active → 'You'.
    """
    if mic_rms >= loopback_rms:
        return "You"
    return "Them"
