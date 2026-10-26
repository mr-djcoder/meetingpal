"""Anthropic Claude client — streaming SSE responses grounded in meeting transcript."""
from __future__ import annotations

import math
from typing import AsyncGenerator

import anthropic

from backend.models import ChatMessage, TranscriptSegment

SYSTEM_PERSONA = (
    "You are MeetingPal, a world-class executive consultant and strategic advisor "
    "who has been silently listening to a live meeting. You have full context of "
    "everything said so far, provided in the transcript below. Your job is to help "
    "the user — a busy professional — in real time during the meeting. Be concise, "
    "sharp, and immediately useful. Prioritize insights from the transcript over "
    "general knowledge. Never mention that you are an AI unless directly asked. "
    "Respond as a trusted advisor would in a 1:1 chat."
)

MAX_TRANSCRIPT_TOKENS = 60_000
MAX_HISTORY_TOKENS = 20_000
TRIM_PASSES = 4  # bounded count_tokens round trips when over budget

# Transcript is sent as fixed-size blocks so the older, full blocks form a stable prefix
# that prompt caching can reuse across asks (only the newest partial block changes).
SEGMENTS_PER_BLOCK = 40
TRANSCRIPT_HEADER = "## Meeting Transcript\n\n"


def format_segment(seg: TranscriptSegment) -> str:
    ts = seg.wall_clock_time.strftime("%I:%M %p").lstrip("0")
    return f'[{ts}] {seg.speaker}: "{seg.text}"'


def build_system_blocks(persona: str, segments: list[TranscriptSegment]) -> list[dict]:
    """System prompt as content blocks: persona, then the transcript in fixed chunks.

    The last *full* chunk carries the cache breakpoint; later (partial) chunk is uncached.
    """
    blocks: list[dict] = [{"type": "text", "text": persona}]
    if not segments:
        blocks.append({"type": "text", "text": TRANSCRIPT_HEADER + "(no speech transcribed yet)"})
        return blocks

    last_full = -1
    chunks: list[list[TranscriptSegment]] = []
    for i in range(0, len(segments), SEGMENTS_PER_BLOCK):
        chunk = segments[i : i + SEGMENTS_PER_BLOCK]
        chunks.append(chunk)
        if len(chunk) == SEGMENTS_PER_BLOCK:
            last_full = len(chunks) - 1

    for idx, chunk in enumerate(chunks):
        text = "\n".join(format_segment(s) for s in chunk)
        if idx == 0:
            text = TRANSCRIPT_HEADER + text
        block: dict = {"type": "text", "text": text}
        if idx == last_full:
            block["cache_control"] = {"type": "ephemeral"}
        blocks.append(block)
    return blocks


class ClaudeClient:
    async def ask(
        self,
        question: str,
        segments: list[TranscriptSegment],
        history: list[ChatMessage],
        api_key: str,
        model: str = "claude-sonnet-4-6",
        system_prompt: str | None = None,
    ) -> AsyncGenerator[dict, None]:
        """Async generator yielding SSE event dicts.

        `system_prompt`, when given (auto-answer mode), overrides the default
        persona while keeping the transcript grounding.
        """
        client = anthropic.AsyncAnthropic(api_key=api_key)

        persona = system_prompt or SYSTEM_PERSONA
        kept = await self._fit_segments(client, model, persona, segments, MAX_TRANSCRIPT_TOKENS)
        system = build_system_blocks(persona, kept)

        messages = self._build_messages(history, question)
        messages = await self._trim_history(client, model, messages, MAX_HISTORY_TOKENS)

        try:
            async with client.messages.stream(
                model=model,
                max_tokens=2048,
                system=system,
                messages=messages,
            ) as stream:
                async for text in stream.text_stream:
                    yield {"type": "content_delta", "text": text}

                final = await stream.get_final_message()
                usage = final.usage
                yield {
                    "type": "message_stop",
                    "stop_reason": final.stop_reason,
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                }
        except anthropic.AuthenticationError as exc:
            yield {"type": "error", "message": f"API key invalid or quota exceeded: {exc}"}
        except anthropic.RateLimitError as exc:
            yield {"type": "error", "message": f"Rate limit exceeded: {exc}"}
        except Exception as exc:
            yield {"type": "error", "message": str(exc)}

    def _format_transcript(self, segments: list[TranscriptSegment]) -> str:
        return "\n".join(format_segment(s) for s in segments)

    def _build_messages(self, history: list[ChatMessage], question: str) -> list[dict]:
        # The API rejects empty text content, so never replay an empty turn.
        messages = [
            {"role": m.role, "content": m.content} for m in history if m.content.strip()
        ]
        messages.append({"role": "user", "content": question})
        return messages

    async def _count(self, client: anthropic.AsyncAnthropic, model: str, system, messages) -> int | None:
        try:
            resp = await client.messages.count_tokens(model=model, system=system, messages=messages)
            return resp.input_tokens
        except Exception:
            return None  # counting is best-effort; never block the answer on it

    async def _fit_segments(
        self,
        client: anthropic.AsyncAnthropic,
        model: str,
        persona: str,
        segments: list[TranscriptSegment],
        budget: int,
    ) -> list[TranscriptSegment]:
        """Drop the oldest segments until the prompt fits, in a bounded number of passes.

        Each pass sizes the cut from the measured overshoot instead of dropping one
        segment per API round trip.
        """
        kept = list(segments)
        probe = [{"role": "user", "content": "hi"}]
        for _ in range(TRIM_PASSES):
            count = await self._count(client, model, build_system_blocks(persona, kept), probe)
            if count is None or count <= budget or len(kept) <= 1:
                return kept
            keep_n = max(1, int(len(kept) * (budget / count) * 0.9))
            kept = kept[-keep_n:]
        return kept

    async def _trim_history(
        self,
        client: anthropic.AsyncAnthropic,
        model: str,
        messages: list[dict],
        max_tokens: int,
    ) -> list[dict]:
        if len(messages) <= 1:
            return messages
        for _ in range(TRIM_PASSES):
            count = await self._count(client, model, "", messages)
            if count is None or count <= max_tokens or len(messages) <= 2:
                break
            drop = max(1, math.ceil(len(messages) * (1 - max_tokens / count)))
            messages = messages[drop:]
            while len(messages) > 1 and messages[0]["role"] != "user":
                messages = messages[1:]  # a conversation must open with a user turn
        return messages
