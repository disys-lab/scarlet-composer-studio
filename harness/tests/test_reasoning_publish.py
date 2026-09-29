"""
reasoning.publishing_on_event - the wrapper that puts the head's own
reasoning onto the bus.

These are about the wrapper's contract, not about what converse emits
(tests/test_head_converse.py covers that): it must pass every event through
to the caller's own handler unchanged, it must be switchable off, and a
failure to publish must never propagate - it sits on the head's critical
path, wrapped around the callback converse invokes mid-conversation, so a
Redis hiccup there would otherwise take down the conversation it is only
meant to describe.
"""
from scarlet_agentic_harness import reasoning


class _FakeBus:
    def __init__(self, explode=False):
        self.sent = []
        self._explode = explode

    def Send(self, target, message):
        if self._explode:
            raise RuntimeError("redis is down")
        self.sent.append((target, message))


class _FakeBuses:
    def __init__(self, explode=False):
        self.global_bus = _FakeBus(explode)


def test_events_reach_the_bus_and_the_inner_handler(monkeypatch):
    monkeypatch.delenv("PUBLISH_REASONING", raising=False)
    buses = _FakeBuses()
    seen = []
    on_event = reasoning.publishing_on_event(buses, inner=seen.append)

    on_event({"conv_id": "c1", "type": "tool_call", "call_id": "x"})

    # The caller's own handler still sees the event it always saw - this
    # adds a destination rather than replacing one.
    assert seen == [{"conv_id": "c1", "type": "tool_call", "call_id": "x"}]

    target, message = buses.global_bus.sent[0]
    assert target == reasoning.REASONING_SINK
    # The wire type identifies these as reasoning, so a reader can tell
    # them from ordinary bus traffic; the event's own kind survives under
    # "event", so narration and dispatch stay distinguishable. Getting the
    # spread order wrong silently loses the former - which is exactly what
    # the first version of this did.
    assert message["type"] == reasoning.MSG_TYPE
    assert message["event"] == "tool_call"
    assert message["conv_id"] == "c1"
    assert message["call_id"] == "x"


def test_publishing_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("PUBLISH_REASONING", "false")
    buses = _FakeBuses()
    seen = []
    on_event = reasoning.publishing_on_event(buses, inner=seen.append)

    on_event({"conv_id": "c1", "type": "final", "content": "done"})

    # Nothing published - the events carry model output and real tool
    # results, so a deployment handling sensitive data can opt out.
    assert buses.global_bus.sent == []
    # ...but the local handler is unaffected: switching off publication is
    # not switching off the caller's own logging.
    assert len(seen) == 1


def test_a_publish_failure_is_swallowed():
    """A broken bus must not break the conversation being described."""
    buses = _FakeBuses(explode=True)
    seen = []
    on_event = reasoning.publishing_on_event(buses, inner=seen.append)

    on_event({"conv_id": "c1", "type": "narration", "content": "thinking"})  # must not raise

    assert len(seen) == 1


def test_reserved_sink_cannot_collide_with_a_real_agent_id():
    """
    Real agent ids are always f"{APP_ID}_{NODE_ADDRESS}". The sink is
    double-underscored so no configuration can produce it, and sending to
    it registers nothing - only constructing a Messenger registers, so it
    never appears as a phantom agent in GatherStatus.
    """
    assert reasoning.REASONING_SINK.startswith("__")
    assert reasoning.REASONING_SINK.endswith("__")
