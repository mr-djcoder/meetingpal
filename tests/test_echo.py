from backend.echo import EchoFilter


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_mic_text_matching_recent_loopback_is_echo():
    f = EchoFilter(now_fn=_Clock())
    f.note_other("so what is the plan for the next quarter")
    assert f.is_echo("so what is the plan for the next quarter")
    assert f.is_echo("What is the plan for the next quarter?")


def test_partial_prefix_of_loopback_is_echo():
    f = EchoFilter(now_fn=_Clock())
    f.note_other("we should ship the new release on friday afternoon")
    assert f.is_echo("we should ship the new release")


def test_unrelated_speech_is_not_echo():
    f = EchoFilter(now_fn=_Clock())
    f.note_other("so what is the plan for the next quarter")
    assert not f.is_echo("I think we should hire two more engineers")


def test_short_phrases_are_never_suppressed():
    f = EchoFilter(now_fn=_Clock())
    f.note_other("yes okay sure")
    assert not f.is_echo("yes okay sure")


def test_old_loopback_text_expires():
    clock = _Clock()
    f = EchoFilter(now_fn=clock)
    f.note_other("so what is the plan for the next quarter")
    clock.t += 60
    assert not f.is_echo("so what is the plan for the next quarter")


def test_reset_forgets_everything():
    f = EchoFilter(now_fn=_Clock())
    f.note_other("so what is the plan for the next quarter")
    f.reset()
    assert not f.is_echo("so what is the plan for the next quarter")
