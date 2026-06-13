"""Anthropic Claude client — streaming SSE responses grounded in meeting transcript."""
from __future__ import annotations

import asyncio
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


class ClaudeClient:
    async def ask(
        self,
        question: str,
        segments: list[TranscriptSegment],
        history: list[ChatMessage],
        api_key: str,
        model: str = "claude-sonnet-4-6",
    ) -> AsyncGenerator[dict, None]:
        """Async generator yielding SSE event dicts."""
        client = anthropic.AsyncAnthropic(api_key=api_key)

        transcript_text = self._format_transcript(segments)
        system_prompt = f"{SYSTEM_PERSONA}\n\n## Meeting Transcript\n\n{transcript_text}"

        # Trim transcript to token budget
        system_prompt = await self._trim_to_tokens(
            client, system_prompt, MAX_TRANSCRIPT_TOKENS, segments
        )

        messages = self._build_messages(history, question)
        messages = await self._trim_history(client, messages, MAX_HISTORY_TOKENS)

        try:
            async with client.messages.stream(
                model=model,
                max_tokens=2048,
                system=system_prompt,
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
        lines = []
        for seg in segments:
            ts = seg.wall_clock_time.strftime("%I:%M %p").lstrip("0")
            lines.append(f'[{ts}] {seg.speaker}: "{seg.text}"')
        return "\n".join(lines)

    def _build_messages(self, history: list[ChatMessage], question: str) -> list[dict]:
        messages = []
        for msg in history:
            messages.append({"role": msg.role, "content": msg.content})
        messages.append({"role": "user", "content": question})
        return messages

    async def _trim_to_tokens(
        self,
        client: anthropic.AsyncAnthropic,
        system_prompt: str,
        max_tokens: int,
        segments: list[TranscriptSegment],
    ) -> str:
        try:
            resp = await client.messages.count_tokens(
                model="claude-sonnet-4-6",
                system=system_prompt,
                messages=[{"role": "user", "content": "hi"}],
            )
            token_count = resp.input_tokens
        except Exception:
            return system_prompt

        if token_count <= max_tokens:
            return system_prompt

        # Drop oldest segments until within budget
        working_segments = list(segments)
        while token_count > max_tokens and len(working_segments) > 1:
            working_segments = working_segments[1:]
            transcript_text = self._format_transcript(working_segments)
            new_prompt = f"{SYSTEM_PERSONA}\n\n## Meeting Transcript\n\n{transcript_text}"
            try:
                resp = await client.messages.count_tokens(
                    model="claude-sonnet-4-6",
                    system=new_prompt,
                    messages=[{"role": "user", "content": "hi"}],
                )
                token_count = resp.input_tokens
                system_prompt = new_prompt
            except Exception:
                break

        return system_prompt

    async def _trim_history(
        self,
        client: anthropic.AsyncAnthropic,
        messages: list[dict],
        max_tokens: int,
    ) -> list[dict]:
        if len(messages) <= 1:
            return messages
        try:
            resp = await client.messages.count_tokens(
                model="claude-sonnet-4-6",
                system="",
                messages=messages,
            )
            token_count = resp.input_tokens
        except Exception:
            return messages

        # Drop oldest exchange pairs (skip the last user message)
        while token_count > max_tokens and len(messages) > 3:
            messages = messages[2:]  # drop one user+assistant pair
            try:
                resp = await client.messages.count_tokens(
                    model="claude-sonnet-4-6",
                    system="",
                    messages=messages,
                )
                token_count = resp.input_tokens
            except Exception:
                break

        return messages
