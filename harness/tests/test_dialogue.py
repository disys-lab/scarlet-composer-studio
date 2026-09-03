"""
Unit tests for AgentDialogue - no Redis, no subprocess. AgentDialogue never
calls Receive() itself (see dialogue.py - it's fed via handle(), the same
integration point a router's default_handler uses for real), so two linked
fake buses are enough to test a genuine two-sided conversation: each
LinkedBus.Send() hands the message directly to the other side's
AgentDialogue.handle(), the same shape a real Messenger send would produce.
"""
import threading

from scarlet_agentic_harness import local_config
from scarlet_agentic_harness.dialogue import AgentDialogue


class LinkedBus:
    """Stands in for a Messenger - Send() delivers straight to the other
    side's AgentDialogue.handle(), skipping Redis/the router entirely
    (legitimate here since AgentDialogue only ever consumes messages via
    handle(), never Receive())."""

    def __init__(self, agent_id: str):
        self.agentId = agent_id  # matches real Messenger's attribute name - dialogue.py reads this for identity framing
        self.other_dialogue: AgentDialogue | None = None

    def Send(self, target_agent_id: str, body: dict) -> None:
        self.other_dialogue.handle({"from": self.agentId, "to": target_agent_id, "body": body})


class FakeDialogueLLM:
    """Records every call it receives and returns pre-scripted replies in
    order - same spirit as tests/fakes.py's ScriptedLLMClient, but shaped
    for AgentDialogue's plain chat(messages) call (no tools)."""

    def __init__(self, replies: list[str]):
        self._replies = list(replies)
        self.calls: list[list[dict]] = []

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        self.calls.append(messages)
        content = self._replies.pop(0)
        return {"role": "assistant", "content": content, "tool_calls": []}


def _linked_pair(llm_a, llm_b, context_fn_b=None):
    bus_a = LinkedBus("agent_a")
    bus_b = LinkedBus("agent_b")
    dialogue_a = AgentDialogue(bus_a, llm_a)
    dialogue_b = AgentDialogue(bus_b, llm_b, context_fn=context_fn_b)
    bus_a.other_dialogue = dialogue_b
    bus_b.other_dialogue = dialogue_a
    return dialogue_a, dialogue_b


def test_start_and_reply_roundtrip():
    llm_a = FakeDialogueLLM([])  # A never has to reason - it just gets a reply
    llm_b = FakeDialogueLLM(["all good here, almost done"])
    dialogue_a, dialogue_b = _linked_pair(llm_a, llm_b)

    got = {}
    done = threading.Event()

    def on_reply(content, sender):
        got["content"] = content
        got["sender"] = sender
        done.set()

    dialogue_a.start("agent_b", "how's it going?", on_reply)

    assert done.wait(timeout=2)
    assert got == {"content": "all good here, almost done", "sender": "agent_b"}
    # B's LLM actually saw A's opening message as a user-role turn
    assert llm_b.calls[0][-1] == {"role": "user", "content": "how's it going?"}


def test_responder_grounds_reply_in_context_fn():
    llm_a = FakeDialogueLLM([])
    llm_b = FakeDialogueLLM(["reply"])
    context = {"in_flight": ["req-1"], "ready_count": 2}
    dialogue_a, dialogue_b = _linked_pair(llm_a, llm_b, context_fn_b=lambda: context)

    done = threading.Event()
    dialogue_a.start("agent_b", "status?", lambda content, sender: done.set())

    assert done.wait(timeout=2)
    system_messages = [m for m in llm_b.calls[0] if m["role"] == "system"]
    assert len(system_messages) == 1
    assert "req-1" in system_messages[0]["content"]
    assert "ready_count" in system_messages[0]["content"]


def test_responder_grounds_reply_in_real_local_data_sources(tmp_path, monkeypatch):
    # Real local_config.describe_sources() (real YAML file, not a scripted
    # dict) wired through context_fn exactly as __main__.py does it - the
    # actual seam Component 5 (on-request semantic tag discovery) closed:
    # a peer's responder LLM sees this worker's own real, redacted local
    # sources (see local_config.py's module docstring) and can reason
    # about whether one of them answers "does anyone have roll_speed for
    # equipment 1234", including a differently-named match like
    # RollSpeed_1234 here - proving the plumbing that reasoning depends on
    # actually delivers the right content, not just that the mechanism
    # works in the abstract (see test_responder_grounds_reply_in_context_fn
    # above for that).
    monkeypatch.setattr(local_config, "CONFIG_PATH", tmp_path / "config.yaml")
    (tmp_path / "config.yaml").write_text("""
sources:
  - name: RollSpeed_1234
    type: postgres
    mode: local
    description: "Roll speed for equipment 1234, sampled every 5s."
    host: 127.0.0.1
    port: 5432
    database: plant
    user: reader
    password: super-secret-should-never-appear-in-a-prompt
""")

    llm_a = FakeDialogueLLM([])
    llm_b = FakeDialogueLLM(["I have RollSpeed_1234 for that equipment"])
    dialogue_a, dialogue_b = _linked_pair(
        llm_a, llm_b,
        context_fn_b=lambda: {"local_data_sources": local_config.describe_sources()},
    )

    done = threading.Event()
    dialogue_a.start("agent_b", "does anyone have roll_speed for equipment 1234?", lambda content, sender: done.set())

    assert done.wait(timeout=2)
    system_prompt = [m for m in llm_b.calls[0] if m["role"] == "system"][0]["content"]
    assert "RollSpeed_1234" in system_prompt
    assert "Roll speed for equipment 1234" in system_prompt
    assert "super-secret-should-never-appear-in-a-prompt" not in system_prompt


def test_no_context_fn_still_establishes_identity_but_no_grounding_claim():
    # A system message is always present now (identity framing - see
    # dialogue.py's _system_prompt, added after a real-LLM test showed a
    # model without it answering like a third party asked to interpret
    # someone else's report, rather than the agent itself). Without a
    # context_fn, that framing is still there, but it must not claim to
    # be grounding the reply in real state it was never actually given.
    llm_a = FakeDialogueLLM([])
    llm_b = FakeDialogueLLM(["reply"])
    dialogue_a, dialogue_b = _linked_pair(llm_a, llm_b)  # context_fn_b omitted

    done = threading.Event()
    dialogue_a.start("agent_b", "status?", lambda content, sender: done.set())

    assert done.wait(timeout=2)
    system_messages = [m for m in llm_b.calls[0] if m["role"] == "system"]
    assert len(system_messages) == 1
    assert "agent_b" in system_messages[0]["content"]
    assert "your own real, current state" not in system_messages[0]["content"]


def test_multi_turn_conversation_keeps_the_responders_history():
    llm_a = FakeDialogueLLM([])
    llm_b = FakeDialogueLLM(["first reply", "second reply"])
    dialogue_a, dialogue_b = _linked_pair(llm_a, llm_b)

    first_done = threading.Event()
    second_done = threading.Event()
    received = []

    def on_first_reply(content, sender):
        received.append(content)
        first_done.set()

    def on_second_reply(content, sender):
        received.append(content)
        second_done.set()

    conv_id = dialogue_a.start("agent_b", "opening", on_first_reply)
    assert first_done.wait(timeout=2)
    assert received == ["first reply"]

    dialogue_a.reply("agent_b", conv_id, "follow-up question", on_second_reply)
    assert second_done.wait(timeout=2)
    assert received == ["first reply", "second reply"]

    # B's second LLM call saw the full accumulated history, not just the
    # follow-up in isolation - proves the session actually persisted.
    # First message is the identity-framing system prompt (see dialogue.py's
    # _system_prompt) - exclude it, this assertion is about the history.
    second_call_messages = llm_b.calls[1]
    assert second_call_messages[0]["role"] == "system"
    contents = [m["content"] for m in second_call_messages[1:]]
    assert contents == ["opening", "first reply", "follow-up question"]


def test_handle_ignores_messages_that_are_not_agent_message():
    llm_b = FakeDialogueLLM([])
    dialogue_b = AgentDialogue(LinkedBus("agent_b"), llm_b)
    dialogue_b.handle({"from": "agent_a", "body": {"type": "skill_contribute", "skill": "sum"}})
    assert llm_b.calls == []  # never reached the LLM at all


def test_forget_clears_tracked_state():
    # Direct dict manipulation, not start() - start() triggers a real send
    # to a responder on another thread, which would race this test's own
    # assertion against however fast that thread pops the same key.
    dialogue_a = AgentDialogue(LinkedBus("agent_a"), FakeDialogueLLM([]))
    dialogue_a._waiting["conv-1"] = lambda content, sender: None
    assert "conv-1" in dialogue_a._waiting
    dialogue_a.forget("conv-1")
    assert "conv-1" not in dialogue_a._waiting
