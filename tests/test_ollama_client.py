import asyncio
import functools
import json
from datetime import datetime

import httpx

from backend import ollama_client
from backend.models import ChatMessage, TranscriptSegment
from backend.ollama_client import (
    MAX_TRANSCRIPT_CHARS,
    OllamaClient,
    build_messages,
    list_ollama_models,
)


def _segs(n, text="x"):
    return [
        TranscriptSegment(id=str(i), speaker="Them", text=f"{text}{i}",
                          wall_clock_time=datetime(2026, 1, 1, 10, 0))
        for i in range(n)
    ]


def _use_transport(monkeypatch, handler):
    real = httpx.AsyncClient
    monkeypatch.setattr(
        ollama_client.httpx, "AsyncClient",
        functools.partial(real, transport=httpx.MockTransport(handler)),
    )


def _collect(gen):
    async def run():
        return [e async for e in gen]
    return asyncio.run(run())


def test_messages_have_persona_transcript_history_and_question():
    history = [
        ChatMessage(session_id="s", role="user", content="earlier q"),
        ChatMessage(session_id="s", role="assistant", content="  "),  # empty turn skipped
        ChatMessage(session_id="s", role="assistant", content="earlier a"),
    ]
    msgs = build_messages("now?", _segs(2), history, "BE BRIEF")
    assert msgs[0]["role"] == "system" and msgs[0]["content"].startswith("BE BRIEF")
    assert "Them" in msgs[0]["content"]
    assert [m["content"] for m in msgs[1:]] == ["earlier q", "earlier a", "now?"]


def test_transcript_keeps_newest_lines_within_budget():
    segs = _segs(5000, text="word " * 10)
    msgs = build_messages("q", segs, [], None)
    system = msgs[0]["content"]
    assert len(system) < MAX_TRANSCRIPT_CHARS + 2000
    assert "word 4999" in system.replace('"', "") or "4999" in system  # newest kept
    assert "word 0" not in system  # oldest dropped


def test_ask_streams_tokens_and_requests_context_and_no_thinking(monkeypatch):
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        lines = [
            {"message": {"content": "Hello "}},
            {"message": {"content": "there."}},
            {"message": {"content": ""}, "done": True},
        ]
        return httpx.Response(200, content="\n".join(json.dumps(x) for x in lines))

    _use_transport(monkeypatch, handler)
    events = _collect(OllamaClient().ask("q", _segs(1), [], model="m1"))
    assert [e["text"] for e in events if e["type"] == "content_delta"] == ["Hello ", "there."]
    assert events[-1] == {"type": "message_stop"}
    assert seen["model"] == "m1" and seen["think"] is False
    assert seen["options"]["num_ctx"] >= 8192


def test_ask_reports_http_error(monkeypatch):
    _use_transport(monkeypatch, lambda r: httpx.Response(404, text='model "nope" not found'))
    events = _collect(OllamaClient().ask("q", [], [], model="nope"))
    assert events[0]["type"] == "error" and "not found" in events[0]["message"]


def test_ask_reports_ollama_not_running(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("refused")

    _use_transport(monkeypatch, handler)
    events = _collect(OllamaClient().ask("q", [], []))
    assert events[0]["type"] == "error" and "Is it running" in events[0]["message"]


def test_list_models_sorted_and_empty_when_down(monkeypatch):
    _use_transport(
        monkeypatch,
        lambda r: httpx.Response(200, json={"models": [{"name": "b:1"}, {"name": "a:2"}]}),
    )
    assert asyncio.run(list_ollama_models()) == ["a:2", "b:1"]

    def down(request):
        raise httpx.ConnectError("refused")

    _use_transport(monkeypatch, down)
    assert asyncio.run(list_ollama_models()) == []
