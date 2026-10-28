"""Best-effort suppression of mic text that is just the other side's audio.

Without a headset the microphone hears the speakers, so the same speech is transcribed
twice: once cleanly from loopback ("Them") and once from the mic ("You"). We remember
recent "Them" text and drop mic text that closely matches it.
"""
from __future__ import annotations

import re
import time
from collections import deque
from difflib import SequenceMatcher
from typing import Callable

MIN_WORDS = 4        # too short to judge ("yes", "okay") so never suppress
WINDOW_S = 10.0      # how long a "Them" utterance stays a candidate for echo
THRESHOLD = 0.8
MAX_REMEMBERED = 50


def _words(text: str) -> list[str]:
    return re.sub(r"[^\w\s]", "", text.lower()).split()


class EchoFilter:
    def __init__(self, now_fn: Callable[[], float] = time.monotonic) -> None:
        self._now = now_fn
        self._recent: deque[tuple[float, list[str]]] = deque(maxlen=MAX_REMEMBERED)

    def note_other(self, text: str) -> None:
        words = _words(text)
        if words:
            self._recent.append((self._now(), words))

    def is_echo(self, text: str) -> bool:
        words = _words(text)
        if len(words) < MIN_WORDS:
            return False
        cutoff = self._now() - WINDOW_S
        for ts, other in self._recent:
            if ts < cutoff:
                continue
            # Compare against the whole utterance and against its same-length prefix
            # (a mic partial is usually a prefix of the loopback text).
            best = max(
                SequenceMatcher(None, words, other).ratio(),
                SequenceMatcher(None, words, other[: len(words)]).ratio(),
            )
            if best >= THRESHOLD:
                return True
        return False

    def reset(self) -> None:
        self._recent.clear()
