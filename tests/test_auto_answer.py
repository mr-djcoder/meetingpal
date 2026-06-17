import asyncio
from dataclasses import dataclass

from backend.auto_answer import AutoAnswerOrchestrator, is_question


# ── heuristic ───────────────────────────────────────────────────────────────

def test_is_question_positive():
    assert is_question("What's your experience with Kafka?")
    assert is_question("How would you scale this")
    assert is_question("Tell me about yourself")
    assert is_question("Is that correct?")
    assert is_question("Walk me through your approach.")


def test_is_question_negative():
    assert not is_question("I think we should ship it.")
    assert not is_question("")
    assert not is_question("Okay, sounds good.")
    assert not is_question("Right.")


# ── orchestrator ────────────────────────────────────────────────────────────

@dataclass
class Seg:
    text: str
    speaker: str = "Them"
    is_final: bool = True


class Prefs:
    def __init__(self, enabled=True, provider="claude", model="m"):
        self.auto_answer_enabled = enabled
        self.auto_answer_provider = provider
        self.auto_answer_model = model
        self.auto_answer_prompt = "Answer as me."


class FakeClient:
    """ask() yields two deltas then ends."""
    def __init__(self):
        self.calls = 0

    async def ask(self, *, question, segments, history, api_key, model, system_prompt=None):
        self.calls += 1
        yield {"type": "content_delta", "text": "Hello "}
        yield {"type": "content_delta", "text": "world"}
        yield {"type": "message_stop"}


class HangClient:
    """ask() starts then hangs (to test cancel-replace)."""
    def __init__(self):
        self.cancelled = False

    async def ask(self, *, question, segments, history, api_key, model, system_prompt=None):
        try:
            yield {"type": "content_delta", "text": "start"}
            await asyncio.Event().wait()  # never resolves
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        yield {"type": "content_delta", "text": "unreachable"}


def run(coro):
    return asyncio.run(coro)


def make(broadcast, **kw):
    return AutoAnswerOrchestrator(broadcast, **kw)


def test_them_question_fires_start_token_done():
    events = []
    async def bc(e): events.append(e)

    async def body():
        client = FakeClient()
        orch = make(bc, now_fn=lambda: 100.0)
        await orch.maybe_answer(
            segment=Seg("What is your name?"), prefs=Prefs(),
            claude_key="k", gemini_key=None, claude_client=client, gemini_client=None,
            segments=[], history=[],
        )
        await orch.task
    run(body())
    types = [e["type"] for e in events]
    assert types[0] == "auto_answer_start"
    assert "auto_answer_token" in types
    assert types[-1] == "auto_answer_done"
    assert events[0]["question"] == "What is your name?"


def test_you_speech_does_not_fire():
    events = []
    async def bc(e): events.append(e)
    async def body():
        orch = make(bc)
        await orch.maybe_answer(
            segment=Seg("What is your name?", speaker="You"), prefs=Prefs(),
            claude_key="k", gemini_key=None, claude_client=FakeClient(), gemini_client=None,
            segments=[], history=[],
        )
        assert orch.task is None
    run(body())
    assert events == []


def test_non_question_does_not_fire():
    events = []
    async def bc(e): events.append(e)
    async def body():
        orch = make(bc)
        await orch.maybe_answer(
            segment=Seg("Sounds good to me."), prefs=Prefs(),
            claude_key="k", gemini_key=None, claude_client=FakeClient(), gemini_client=None,
            segments=[], history=[],
        )
        assert orch.task is None
    run(body())


def test_disabled_does_not_fire():
    events = []
    async def bc(e): events.append(e)
    async def body():
        orch = make(bc)
        await orch.maybe_answer(
            segment=Seg("What is it?"), prefs=Prefs(enabled=False),
            claude_key="k", gemini_key=None, claude_client=FakeClient(), gemini_client=None,
            segments=[], history=[],
        )
        assert orch.task is None
    run(body())


def test_missing_key_broadcasts_error():
    events = []
    async def bc(e): events.append(e)
    async def body():
        orch = make(bc)
        await orch.maybe_answer(
            segment=Seg("What is it?"), prefs=Prefs(provider="gemini"),
            claude_key="k", gemini_key=None, claude_client=FakeClient(), gemini_client=FakeClient(),
            segments=[], history=[],
        )
    run(body())
    assert events and events[0]["type"] == "auto_answer_error"


def test_min_interval_skips_second():
    events = []
    async def bc(e): events.append(e)
    t = {"v": 100.0}

    async def body():
        client = FakeClient()
        orch = make(bc, now_fn=lambda: t["v"], min_interval_s=2.0)
        await orch.maybe_answer(
            segment=Seg("What is one?"), prefs=Prefs(), claude_key="k", gemini_key=None,
            claude_client=client, gemini_client=None, segments=[], history=[],
        )
        await orch.task
        t["v"] = 101.0  # < 2s later
        await orch.maybe_answer(
            segment=Seg("What is two?"), prefs=Prefs(), claude_key="k", gemini_key=None,
            claude_client=client, gemini_client=None, segments=[], history=[],
        )
        assert client.calls == 1  # second skipped
    run(body())


def test_new_question_after_interval_cancels_previous():
    events = []
    async def bc(e): events.append(e)
    t = {"v": 100.0}

    async def body():
        hang = HangClient()
        fresh = FakeClient()
        orch = make(bc, now_fn=lambda: t["v"], min_interval_s=2.0)
        await orch.maybe_answer(
            segment=Seg("First question?"), prefs=Prefs(), claude_key="k", gemini_key=None,
            claude_client=hang, gemini_client=None, segments=[], history=[],
        )
        await asyncio.sleep(0.01)  # let it start + hang
        first_task = orch.task
        t["v"] = 103.0  # past interval
        await orch.maybe_answer(
            segment=Seg("Second question?"), prefs=Prefs(), claude_key="k", gemini_key=None,
            claude_client=fresh, gemini_client=None, segments=[], history=[],
        )
        await asyncio.sleep(0.01)
        assert first_task.cancelled() or hang.cancelled
        await orch.task  # second completes
        assert fresh.calls == 1
    run(body())
