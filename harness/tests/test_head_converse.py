"""
head.converse()'s loop logic, isolated from the distributed mechanics -
head.run_skill() is monkeypatched here on purpose: that function already has
its own real, subprocess-backed end-to-end coverage
(tests/test_median_skill.py, tests/test_converse_end_to_end.py). These tests
are only about the loop's control flow: does it call the right skill with
the right args, does it handle multiple tool calls in one turn, does it stop
when the model stops calling tools, does it give up after max_turns. No
Redis, no subprocesses, no network.

converse() is fire-and-forget (delivers its result via on_done, not a
return value - see head.py) - converse_sync() (tests/helpers.py) blocks the
test thread on a threading.Event until that fires, and re-raises whatever
error came back, so these tests keep their original synchronous shape.
Fakes standing in for run_skill() must match its real async signature
(..., on_result) and call on_result(...) themselves - synchronously is
fine here, since converse()'s logic doesn't care whether a callback fires
inline or from another thread.
"""
from scarlet_agentic_harness import head as head_mod
from scarlet_agentic_harness.skills.base import Skill
from tests.fakes import ScriptedLLMClient, assistant_final, assistant_tool_call
from tests.helpers import converse_sync


class _DummySkill(Skill):
    name = "dummy"
    description = "unused in these tests"

    def contribute(self, ctx, request):
        raise AssertionError("contribute() should never run - run_skill is monkeypatched")

    def coordinate(self, ctx, request, workers):
        raise AssertionError("coordinate() should never run - run_skill is monkeypatched")


def test_no_tool_call_returns_content_directly(monkeypatch):
    calls = []
    monkeypatch.setattr(head_mod, "run_skill", lambda *a, **kw: calls.append((a, kw)))

    llm = ScriptedLLMClient([assistant_final("no tools needed, here's the answer")])
    result = converse_sync("hello", config=None, buses=None, skills={"dummy": _DummySkill()}, llm_client=llm)

    assert result.answer == "no tools needed, here's the answer"
    assert calls == []  # run_skill never invoked


def test_single_tool_call_dispatches_and_returns_final_content(monkeypatch):
    captured = {}

    def fake_run_skill(skill, params, config, buses, on_result, **_kwargs):
        captured["skill"] = skill.name
        captured["params"] = params
        on_result({"status": "ok", "result": 42})

    monkeypatch.setattr(head_mod, "run_skill", fake_run_skill)

    llm = ScriptedLLMClient([
        assistant_tool_call("call_1", "dummy", {"x": 1}),
        assistant_final("the answer is 42"),
    ])
    skills = {"dummy": _DummySkill()}
    result = converse_sync("what's dummy(1)?", config=None, buses=None, skills=skills, llm_client=llm)

    assert result.answer == "the answer is 42"
    assert captured == {"skill": "dummy", "params": {"x": 1}}

    # the tool result must have been fed back into the conversation before
    # the second chat() call, matching the canonical tool-message shape
    second_call_messages, _ = llm.calls[1]
    tool_messages = [m for m in second_call_messages if m["role"] == "tool"]
    assert len(tool_messages) == 1
    assert tool_messages[0]["tool_call_id"] == "call_1"
    assert tool_messages[0]["content"] == {"status": "ok", "result": 42}


def test_multiple_tool_calls_in_one_turn_all_get_dispatched(monkeypatch):
    seen = []

    def fake_run_skill(skill, params, config, buses, on_result, **_kwargs):
        seen.append(params)
        on_result({"status": "ok", "result": params})

    monkeypatch.setattr(head_mod, "run_skill", fake_run_skill)

    llm = ScriptedLLMClient([
        {
            "role": "assistant", "content": None,
            "tool_calls": [
                {"id": "c1", "name": "dummy", "arguments": {"which": "first"}},
                {"id": "c2", "name": "dummy", "arguments": {"which": "second"}},
            ],
        },
        assistant_final("combined answer"),
    ])
    result = converse_sync("do two things", config=None, buses=None, skills={"dummy": _DummySkill()}, llm_client=llm)

    assert result.answer == "combined answer"
    assert sorted(seen, key=lambda p: p["which"]) == [{"which": "first"}, {"which": "second"}]

    second_call_messages, _ = llm.calls[1]
    tool_call_ids = {m["tool_call_id"] for m in second_call_messages if m["role"] == "tool"}
    assert tool_call_ids == {"c1", "c2"}


def test_unknown_tool_name_reports_error_without_crashing(monkeypatch):
    monkeypatch.setattr(head_mod, "run_skill", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("should not be called")))

    llm = ScriptedLLMClient([
        assistant_tool_call("call_1", "does_not_exist"),
        assistant_final("sorry, I don't have that capability"),
    ])
    result = converse_sync("do something unsupported", config=None, buses=None, skills={"dummy": _DummySkill()}, llm_client=llm)

    assert result.answer == "sorry, I don't have that capability"
    second_call_messages, _ = llm.calls[1]
    tool_msg = [m for m in second_call_messages if m["role"] == "tool"][0]
    assert tool_msg["content"]["status"] == "error"


def test_gives_up_after_max_turns(monkeypatch):
    def fake_run_skill(skill, params, config, buses, on_result, **_kwargs):
        on_result({"status": "ok", "result": 1})
    monkeypatch.setattr(head_mod, "run_skill", fake_run_skill)

    # a model that never stops calling tools
    llm = ScriptedLLMClient([assistant_tool_call(f"call_{i}", "dummy") for i in range(10)])

    try:
        converse_sync("loop forever", config=None, buses=None, skills={"dummy": _DummySkill()}, llm_client=llm, max_turns=3)
        assert False, "expected ConversationDidNotConclude"
    except head_mod.ConversationDidNotConclude as exc:
        # the partial transcript survives the failure too - a caller
        # debugging why the model never concluded needs exactly this.
        assert len(exc.messages) > 0

    assert len(llm.calls) == 3  # stopped exactly at the limit, not before/after


def test_converse_retains_full_transcript_and_emits_events(monkeypatch):
    def fake_run_skill(skill, params, config, buses, on_result, **_kwargs):
        on_result({"status": "ok", "result": 7})
    monkeypatch.setattr(head_mod, "run_skill", fake_run_skill)

    llm = ScriptedLLMClient([
        {
            "role": "assistant",
            "content": "I'll call dummy to check something first.",
            "tool_calls": [{"id": "call_1", "name": "dummy", "arguments": {}}],
        },
        assistant_final("the answer is 7"),
    ])

    events = []
    result = converse_sync(
        "what's dummy?", config=None, buses=None, skills={"dummy": _DummySkill()},
        llm_client=llm, on_event=events.append,
    )

    assert result.answer == "the answer is 7"
    # Full transcript retained - previously only the bare final string
    # survived; the narration and tool exchange are both preserved here.
    assert any(m.get("role") == "tool" and m["content"] == {"status": "ok", "result": 7} for m in result.messages)

    # The narration that accompanied the tool call is not silently dropped -
    # this is exactly the case that used to vanish (a turn with both content
    # and tool_calls only ever surfaced its tool_calls before).
    event_types = [e["type"] for e in events]
    # "question" comes first and carries the message that started the
    # conversation - converse keeps that only in its in-process store, so
    # without this event a consumer sees the reasoning and the answer but
    # never what was asked.
    assert event_types == ["question", "narration", "tool_call", "tool_result", "final"]
    assert events[0]["content"] == "what's dummy?"
    assert events[1]["content"] == "I'll call dummy to check something first."
    assert events[3]["result"] == {"status": "ok", "result": 7}
    assert events[4]["content"] == "the answer is 7"

    # Every event carries the conversation id. converse mints it, so no
    # caller can know it up front, and without it a shared event stream
    # cannot tell two concurrent conversations apart - reasoning.py relies
    # on this to group a whole exchange.
    conv_ids = {e["conv_id"] for e in events}
    assert len(conv_ids) == 1 and next(iter(conv_ids))

    assert {k: v for k, v in events[2].items() if k != "conv_id"} == {
        "type": "tool_call", "turn": 0, "call_id": "call_1", "skill": "dummy", "params": {},
    }

    # No "dispatch" event appears here because run_skill is monkeypatched
    # out above - that event is emitted from inside the real one, carrying
    # the request_id minted per attempt.


def test_dispatch_events_link_each_tool_call_to_its_request_ids(monkeypatch):
    """
    A tool call and the bus traffic it causes are only connectable through
    the "dispatch" event.

    run_skill mints a fresh request_id per *attempt*, inside itself, and
    reports nothing back but the final result - so one tool call can span
    several request_ids and nothing downstream can tell which dispatch
    belonged to which call. Correlating by timestamp instead would be wrong
    as soon as two calls overlap, which is the normal case: the model
    routinely issues several tool calls in a single turn.

    This fakes a retry (two attempts, two ids) and checks both are reported
    against the call that caused them.
    """
    def fake_run_skill(skill, params, config, buses, on_result, **kwargs):
        on_dispatch = kwargs.get("on_dispatch")
        # Two attempts, as a real retry would produce.
        on_dispatch("req-attempt-1", 1)
        on_dispatch("req-attempt-2", 2)
        on_result({"status": "ok", "result": 7})
    monkeypatch.setattr(head_mod, "run_skill", fake_run_skill)

    llm = ScriptedLLMClient([
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "call_abc", "name": "dummy", "arguments": {}}],
        },
        assistant_final("done"),
    ])

    events = []
    converse_sync(
        "go", config=None, buses=None, skills={"dummy": _DummySkill()},
        llm_client=llm, on_event=events.append,
    )

    dispatches = [e for e in events if e["type"] == "dispatch"]
    assert [d["request_id"] for d in dispatches] == ["req-attempt-1", "req-attempt-2"]
    assert {d["call_id"] for d in dispatches} == {"call_abc"}
    assert [d["attempt"] for d in dispatches] == [1, 2]
    # Ordered so a reader sees the call before anything attributed to it.
    assert events.index(next(e for e in events if e["type"] == "tool_call")) < events.index(dispatches[0])


def test_an_llm_error_on_a_later_turn_reports_instead_of_hanging(monkeypatch):
    """
    Turn 0 runs on the caller's thread; turns 1+ run on a bus callback
    thread when the joiner fires. An exception there used to die silently -
    on_done never fired and the caller waited forever.

    Observed live: the endpoint returned HTTP 400 mid-conversation, the
    client correctly did not retry, and the notebook sat idle for eleven
    minutes until its cell limit killed it. The failure was instant; only
    the reporting of it hung.
    """
    import threading
    from scarlet_agentic_harness import head as head_mod
    from scarlet_agentic_harness.config import HarnessConfig

    class _Boom:
        """Answers turn 0 with a tool call, then raises on turn 1."""
        def __init__(self): self.calls = 0
        def chat(self, messages, tools=None):
            self.calls += 1
            if self.calls == 1:
                return {"role": "assistant", "content": None, "tool_calls": [
                    {"id": "c1", "name": "fake", "arguments": {}}]}
            raise RuntimeError("Error code: 400 - Bad Request")

    class _Fake:
        name = "fake"
        def as_tool_schema(self): return {"type": "function", "function": {"name": "fake"}}

    # Answer on a REAL worker thread, so turn 1 runs where the joiner
    # actually fires it. Answering inline would run turn 1 on the caller's
    # thread, where an exception propagates anyway and the bug is invisible.
    def _async_run_skill(skill, params, cfg, buses, on_result, **kw):
        threading.Thread(target=on_result,
                         args=({"status": "ok", "result": 1},),
                         daemon=True).start()

    monkeypatch.setattr(head_mod, "run_skill", _async_run_skill)

    done = threading.Event()
    box = {}
    cfg = HarnessConfig(role="head", app_id="t", node_address="n",
                        device_group="t_sub", head_bus="t_head",
                        llm_base_url=None, llm_api_key=None, llm_model=None)

    def _on_done(result, error):
        box.update(result=result, error=error)
        done.set()

    head_mod.converse("q", cfg, None, {"fake": _Fake()}, _Boom(), _on_done,
                      max_turns=5, on_event=None, store=None, dialogue=None)

    # Bounded: without the fix this never fires and the suite would hang.
    assert done.wait(timeout=10), "on_done never fired - the caller would hang forever"
    assert isinstance(box["error"], RuntimeError)
    assert "400" in str(box["error"])
