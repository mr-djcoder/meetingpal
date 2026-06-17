"""Google Gemini client — streaming responses grounded in the meeting transcript.

Mirrors backend.claude_client.ClaudeClient.ask's event-dict contract:
yields {"type":"content_delta","text":...} per token, a terminal
{"type":"message_stop"}, or {"type":"error","message":...} on failure.
The google-genai SDK is imported lazily so this module loads without it.
"""
from __future__ import annotations

from typing import AsyncGenerator

from backend.models import ChatMessage, TranscriptSegment

DEFAULT_PERSONA = (
    "You are a sharp, concise real-time meeting assistant. Answer the user's "
    "question using the transcript context below. Be brief and immediately useful."
)

# Static fallback if the live ListModels call fails (IDs churn — confirm live).
FALLBACK_GEMINI_MODELS = [
    "gemini-3.5-flash",
    "gemini-2.5-pro",
    "gemini-3.1-flash-lite",
]


class GeminiClient:
    async def ask(
        self,
        question: str,
        segments: list[TranscriptSegment],
        history: list[ChatMessage],
        api_key: str,
        model: str = "gemini-3.5-flash",
        system_prompt: str | None = None,
    ) -> AsyncGenerator[dict, None]:
        try:
            from google import genai
            from google.genai import types
        except Exception as exc:  # pragma: no cover - SDK missing
            yield {"type": "error", "message": f"google-genai not available: {exc}"}
            return

        persona = system_prompt or DEFAULT_PERSONA
        system = f"{persona}\n\n## Meeting Transcript\n\n{self._format_transcript(segments)}"

        try:
            client = genai.Client(api_key=api_key)
            cfg = types.GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=2048,
            )
            stream = await client.aio.models.generate_content_stream(
                model=model, contents=question, config=cfg
            )
            async for chunk in stream:
                text = getattr(chunk, "text", None)
                if text:
                    yield {"type": "content_delta", "text": text}
            yield {"type": "message_stop"}
        except Exception as exc:
            yield {"type": "error", "message": str(exc)}

    def _format_transcript(self, segments: list[TranscriptSegment]) -> str:
        lines = []
        for seg in segments:
            ts = seg.wall_clock_time.strftime("%I:%M %p").lstrip("0")
            lines.append(f'[{ts}] {seg.speaker}: "{seg.text}"')
        return "\n".join(lines)


async def list_gemini_models(api_key: str) -> list[str]:
    """Best-effort list of Gemini model IDs that support generateContent.

    Falls back to FALLBACK_GEMINI_MODELS on any failure (no key, network, SDK).
    """
    try:
        from google import genai
    except Exception:
        return list(FALLBACK_GEMINI_MODELS)
    try:
        client = genai.Client(api_key=api_key)
        out: list[str] = []
        pager = await client.aio.models.list()
        async for m in pager:
            actions = getattr(m, "supported_actions", None) or []
            if actions and "generateContent" not in actions:
                continue
            name = (getattr(m, "name", "") or "").replace("models/", "")
            if name and "embedding" not in name and "aqa" not in name:
                out.append(name)
        return out or list(FALLBACK_GEMINI_MODELS)
    except Exception:
        return list(FALLBACK_GEMINI_MODELS)
