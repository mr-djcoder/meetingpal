"""Local LLM client (Ollama): streaming answers grounded in the meeting transcript.

Same event-dict contract as ClaudeClient.ask and GeminiClient.ask: yields
{"type":"content_delta","text":...} per chunk, a terminal {"type":"message_stop"},
or {"type":"error","message":...} on failure. Nothing leaves the machine.
"""
from __future__ import annotations

import json
from typing import AsyncGenerator

import httpx

from backend.claude_client import format_segment
from backend.models import ChatMessage, TranscriptSegment

OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_MODEL = "qwen3.5:27b"
# Ollama's default context is small (4096 tokens) and silently truncates the prompt from the
# front, which would drop the persona. Ask for a window that fits a long meeting.
NUM_CTX = 16384
MAX_TRANSCRIPT_CHARS = 36000  # ~9K tokens: newest lines that fit alongside persona + history
KEEP_ALIVE = "30m"  # keep the model in VRAM between questions; a cold load takes 30-60s
CONNECT_TIMEOUT_S = 5.0

DEFAULT_PERSONA = (
    "You are a sharp, concise real-time meeting assistant. Answer the user's "
    "question using the transcript context below. Be brief and immediately useful."
)


def _fit_transcript(segments: list[TranscriptSegment]) -> str:
    """Newest segments that fit MAX_TRANSCRIPT_CHARS, oldest first."""
    lines: list[str] = []
    used = 0
    for seg in reversed(segments):
        line = format_segment(seg)
        if used + len(line) > MAX_TRANSCRIPT_CHARS and lines:
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(reversed(lines))


def build_messages(
    question: str,
    segments: list[TranscriptSegment],
    history: list[ChatMessage],
    system_prompt: str | None,
) -> list[dict[str, str]]:
    persona = system_prompt or DEFAULT_PERSONA
    system = f"{persona}\n\n## Meeting Transcript\n\n{_fit_transcript(segments)}"
    messages = [{"role": "system", "content": system}]
    for turn in history:
        if turn.content.strip():  # an empty turn would confuse the model
            messages.append({"role": turn.role, "content": turn.content})
    messages.append({"role": "user", "content": question})
    return messages


class OllamaClient:
    async def ask(
        self,
        question: str,
        segments: list[TranscriptSegment],
        history: list[ChatMessage],
        api_key: str = "",  # unused; keeps the signature shared with the cloud clients
        model: str = DEFAULT_OLLAMA_MODEL,
        system_prompt: str | None = None,
    ) -> AsyncGenerator[dict, None]:
        body = {
            "model": model or DEFAULT_OLLAMA_MODEL,
            "messages": build_messages(question, segments, history, system_prompt),
            "stream": True,
            "think": False,  # reasoning tokens would delay the first visible word by seconds
            "keep_alive": KEEP_ALIVE,
            "options": {"num_ctx": NUM_CTX},
        }
        timeout = httpx.Timeout(300.0, connect=CONNECT_TIMEOUT_S)  # a cold load is slow
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", f"{OLLAMA_URL}/api/chat", json=body) as r:
                    if r.status_code != 200:
                        detail = (await r.aread()).decode("utf-8", "replace")[:300]
                        yield {"type": "error", "message": f"Ollama {r.status_code}: {detail}"}
                        return
                    async for line in r.aiter_lines():
                        if not line:
                            continue
                        chunk = json.loads(line)
                        if chunk.get("error"):
                            yield {"type": "error", "message": f"Ollama: {chunk['error']}"}
                            return
                        text = chunk.get("message", {}).get("content", "")
                        if text:
                            yield {"type": "content_delta", "text": text}
            yield {"type": "message_stop"}
        except httpx.ConnectError:
            yield {"type": "error",
                   "message": "Cannot reach Ollama at localhost:11434. Is it running?"}
        except Exception as exc:
            yield {"type": "error", "message": f"Ollama request failed: {exc}"}


async def list_ollama_models() -> list[str]:
    """Installed model names, or [] if Ollama is not reachable."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            r = await client.get(f"{OLLAMA_URL}/api/tags")
            r.raise_for_status()
            return sorted(m["name"] for m in r.json().get("models", []))
    except Exception:
        return []


async def warm_up(model: str) -> None:
    """Load the model into VRAM now so the first real question isn't a 30-60s cold start."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=CONNECT_TIMEOUT_S)) as client:
            await client.post(
                f"{OLLAMA_URL}/api/generate",
                json={"model": model, "keep_alive": KEEP_ALIVE, "options": {"num_ctx": NUM_CTX}},
            )
    except Exception:
        pass  # best effort; the real request reports any problem
