"""Auto-answer mode: detect a question from the other party and stream an LLM answer.

Importable WITHOUT the ML stack (no torch / faster-whisper) so its unit tests run
in a bare environment. The provider clients (Claude / Gemini) are injected.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable

INTERROGATIVES = {
    "what", "why", "how", "when", "where", "who", "which",
    "can", "could", "would", "should", "do", "does", "did",
    "is", "are", "was", "were", "will",
}
LEAD_PHRASES = ("tell me", "explain", "walk me through")


def is_question(text: str) -> bool:
    """Heuristic: does this finalized utterance look like a question to answer?"""
    t = text.strip()
    if not t:
        return False
    if t.endswith("?"):
        return True
    low = t.lower()
    words = low.split()
    if words and words[0].strip(",.!:;") in INTERROGATIVES:
        return True
    return any(low.startswith(p) for p in LEAD_PHRASES)


BroadcastFn = Callable[[dict], Awaitable[None]]


class AutoAnswerOrchestrator:
    """Runs at most one auto-answer at a time; a new question cancels the previous.

    `broadcast` is an async fn that ships an event dict to the renderer (WS). The
    provider clients are passed in to `maybe_answer` so this module stays decoupled
    from the heavy SDKs and is unit-testable with fakes.
    """

    def __init__(
        self,
        broadcast: BroadcastFn,
        *,
        min_interval_s: float = 2.0,
        now_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self._broadcast = broadcast
        self._min_interval_s = min_interval_s
        self._now = now_fn
        self._task: asyncio.Task | None = None
        self._last_fire = float("-inf")

    @property
    def task(self) -> asyncio.Task | None:
        return self._task

    async def maybe_answer(
        self,
        *,
        segment: Any,
        prefs: Any,
        claude_key: str | None,
        gemini_key: str | None,
        claude_client: Any,
        gemini_client: Any,
        segments: list,
        history: list,
    ) -> None:
        if not getattr(prefs, "auto_answer_enabled", False):
            return
        if not (segment.is_final and segment.speaker == "Them" and is_question(segment.text)):
            return
        now = self._now()
        if now - self._last_fire < self._min_interval_s:
            return

        provider = getattr(prefs, "auto_answer_provider", "claude")
        if provider == "gemini":
            client, key = gemini_client, gemini_key
        else:
            client, key = claude_client, claude_key
        if not key:
            await self._broadcast(
                {"type": "auto_answer_error", "message": f"No API key for provider '{provider}'."}
            )
            return

        self._last_fire = now
        if self._task and not self._task.done():
            self._task.cancel()

        model = getattr(prefs, "auto_answer_model", "")
        prompt = getattr(prefs, "auto_answer_prompt", None)
        self._task = asyncio.ensure_future(
            self._run(client, key, model, prompt, segment.text, segments, history)
        )

    async def _run(
        self,
        client: Any,
        key: str,
        model: str,
        system_prompt: str | None,
        question: str,
        segments: list,
        history: list,
    ) -> None:
        try:
            await self._broadcast({"type": "auto_answer_start", "question": question})
            async for event in client.ask(
                question=question, segments=segments, history=history,
                api_key=key, model=model, system_prompt=system_prompt,
            ):
                etype = event.get("type")
                if etype == "content_delta":
                    await self._broadcast({"type": "auto_answer_token", "text": event["text"]})
                elif etype == "error":
                    await self._broadcast(
                        {"type": "auto_answer_error", "message": event.get("message", "error")}
                    )
                    return
            await self._broadcast({"type": "auto_answer_done"})
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - defensive
            await self._broadcast({"type": "auto_answer_error", "message": str(exc)})
