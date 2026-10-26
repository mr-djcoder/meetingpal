import asyncio
from datetime import datetime

from backend.claude_client import (
    SEGMENTS_PER_BLOCK,
    ClaudeClient,
    build_system_blocks,
)
from backend.models import ChatMessage, TranscriptSegment


def _segs(n):
    return [
        TranscriptSegment(id=str(i), speaker="Them", text=f"line {i}",
                          wall_clock_time=datetime(2026, 1, 1, 10, 0))
        for i in range(n)
    ]


def test_blocks_start_with_persona_and_header():
    blocks = build_system_blocks("PERSONA", _segs(3))
    assert blocks[0]["text"] == "PERSONA"
    assert blocks[1]["text"].startswith("## Meeting Transcript")
    assert all(b["text"] for b in blocks)  # the API rejects empty text blocks


def test_empty_transcript_still_produces_non_empty_blocks():
    blocks = build_system_blocks("P", [])
    assert len(blocks) == 2 and blocks[1]["text"]


def test_cache_breakpoint_sits_on_last_full_block_only():
    blocks = build_system_blocks("P", _segs(SEGMENTS_PER_BLOCK * 2 + 5))
    marked = [i for i, b in enumerate(blocks) if "cache_control" in b]
    assert marked == [2]  # persona=0, full=1, full=2, partial=3 (uncached)


def test_no_cache_breakpoint_without_a_full_block():
    blocks = build_system_blocks("P", _segs(SEGMENTS_PER_BLOCK - 1))
    assert not any("cache_control" in b for b in blocks)


def test_older_blocks_are_stable_as_transcript_grows():
    a = build_system_blocks("P", _segs(SEGMENTS_PER_BLOCK + 3))
    b = build_system_blocks("P", _segs(SEGMENTS_PER_BLOCK + 20))
    assert a[:2] == b[:2]  # persona + first full block identical: cacheable prefix


class _FakeMessages:
    """count_tokens fake: 10 tokens per transcript line; records calls."""

    def __init__(self):
        self.calls = 0

    async def count_tokens(self, model, system, messages):
        self.calls += 1
        text = system if isinstance(system, str) else " ".join(b["text"] for b in system)
        text += " ".join(m["content"] for m in messages)
        n = text.count("line ") * 10 + len(messages)

        class R:
            input_tokens = n
        return R()


class _FakeClient:
    def __init__(self):
        self.messages = _FakeMessages()


def test_fit_segments_keeps_everything_under_budget():
    client = _FakeClient()
    kept = asyncio.run(ClaudeClient()._fit_segments(client, "m", "P", _segs(10), 1000))
    assert len(kept) == 10 and client.messages.calls == 1


def test_fit_segments_trims_in_bounded_calls_and_keeps_newest():
    client = _FakeClient()
    kept = asyncio.run(ClaudeClient()._fit_segments(client, "m", "P", _segs(1000), 500))
    assert kept[-1].id == "999"
    assert len(kept) < 1000
    assert client.messages.calls <= 4  # was one API call per dropped segment


def test_fit_segments_survives_count_failure():
    class Boom:
        class messages:
            @staticmethod
            async def count_tokens(**kw):
                raise RuntimeError("network")

    kept = asyncio.run(ClaudeClient()._fit_segments(Boom(), "m", "P", _segs(5), 1))
    assert len(kept) == 5


def test_build_messages_skips_empty_turns():
    hist = [
        ChatMessage(role="user", content="q1"),
        ChatMessage(role="assistant", content=""),
        ChatMessage(role="user", content="q2"),
    ]
    msgs = ClaudeClient()._build_messages(hist, "now")
    assert [m["content"] for m in msgs] == ["q1", "q2", "now"]


def test_trim_history_starts_with_user_turn():
    msgs = []
    for i in range(10):
        msgs.append({"role": "user", "content": f"line q{i}"})
        msgs.append({"role": "assistant", "content": f"line a{i}"})
    msgs.append({"role": "user", "content": "now"})
    out = asyncio.run(ClaudeClient()._trim_history(_FakeClient(), "m", msgs, 50))
    assert out[0]["role"] == "user" and out[-1]["content"] == "now"
    assert len(out) < len(msgs)
