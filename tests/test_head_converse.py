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

    def fake_run_skill(skill, params, config, buses, on_result):
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

    def fake_run_skill(skill, params, config, buses, on_result):
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
    def fake_run_skill(skill, params, config, buses, on_result):
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
    def fake_run_skill(skill, params, config, buses, on_result):
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
    assert event_types == ["narration", "tool_call", "tool_result", "final"]
    assert events[0]["content"] == "I'll call dummy to check something first."
    assert events[1] == {"type": "tool_call", "turn": 0, "call_id": "call_1", "skill": "dummy", "params": {}}
    assert events[2]["result"] == {"status": "ok", "result": 7}
    assert events[3]["content"] == "the answer is 7"
