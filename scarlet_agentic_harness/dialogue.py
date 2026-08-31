"""
AgentDialogue — generalized agent-to-agent natural-language conversation.

The same LLM-mediated "narrate, decide, respond" loop head.converse()
already runs between a human and the head, generalized so any two agents
can have it, riding the same buses everything else uses. Deliberately one
generic message envelope (type "agent_message", carrying only
conversation_id + free-form content) rather than a new fixed-schema
message type per use case - a status-check protocol with its own rigid
fields would reduce the model to filling in a form, not actually reasoning
about what to say. See the conversation history behind this module for why
that was rejected in favor of this.

Not built on MessageRouter's on_key(): an incoming agent_message can be
EITHER a reply to a conversation this agent started, OR a brand-new
conversation someone else started - only the message itself reveals which,
and MessageRouter's key_fn can't express "keyed, but fall through to
default_handler if nobody's waiting" without weakening the guarantee
skill_result depends on (an unclaimed reply there must be dropped, not
handed to some fallback - see buses.py's _global_bus_key). So AgentDialogue
keeps its own small dict, fed by the bus's default_handler (the same
integration point worker.start_dispatch() already uses for skill
dispatch - see worker.py), not the router's own key-matching.

Grounding: a responder's reply is not free-floating narration. `context_fn`
(if given) is called fresh on every incoming message and its result is
injected as real local context before the LLM reasons about what to say -
so a coordinator asked "how's it going" can answer from its own actual
in-flight state, not invent something plausible-sounding. See head.py's
docstring / the variance walkthrough for why this matters.

Scope note: a responder's reply call passes no `tools` - it can narrate
grounded in context_fn's snapshot, but it doesn't get its own nested
tool-calling loop to actively look things up mid-reply. That's a real,
deliberate scope boundary for this first version, not an oversight - it
keeps this from needing the same multi-turn machinery converse() has, and
context_fn already covers the motivating case (expose what's relevant,
always, rather than hoping the model remembers to ask for it).
"""
import json
import threading
import uuid
from typing import Callable, Protocol


class ChatClient(Protocol):
    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict: ...


def _system_prompt(agent_id: str, context: dict) -> str:
    """
    Establishes identity before the responder's LLM call, not just context.
    Found via a real-LLM test (tests/test_real_llm_dialogue.py): without
    this, a real model given only a bare "Local context: {...}" system
    message answered like a third party asked to interpret someone else's
    report handed to it ("I don't actually have visibility into this
    distributed system... I'm reading the context you provided in the
    prompt") - accurate as a description of the API call, but exactly
    backwards for what any grounded reply needs to sound like: the injected
    context IS this agent's own real state, and it should answer as
    itself, directly, not hedge about lacking visibility into data that
    was in fact just handed to it as its own.

    Deliberately says nothing about *what kind* of message this is (status,
    a question, a negotiation, anything else) - head.py's check-in is the
    only caller today, but this module's own generic message envelope (see
    the module docstring) exists so AgentDialogue isn't locked to that one
    use case, and this prompt shouldn't be either. Whatever the incoming
    content actually is/asks is in `history` already (see _respond()) -
    the model reasons about that directly, same as any other turn.
    """
    lines = [
        f"You are agent {agent_id!r}. Another agent has sent you a message as part of a "
        f"conversation between agents in a distributed system you're involved in.",
    ]
    if context:
        lines.append(
            f"The following is your own real, current state - not a report someone else "
            f"handed you, it is what you actually know about your own situation right now: "
            f"{json.dumps(context)}"
        )
    lines.append(
        "Answer directly and confidently based on that when it's relevant. Don't caveat "
        "that you lack visibility into the system - the information above is your visibility."
    )
    return " ".join(lines)


class AgentDialogue:
    def __init__(
        self,
        bus,
        llm_client: ChatClient,
        context_fn: Callable[[], dict] | None = None,
    ):
        """
        bus: a single Messenger instance (buses.global_bus or
          buses.local_bus) - one AgentDialogue per bus, matching how
          MessageRouter is one-per-bus too. Replies go out on this same bus.
        llm_client: anything with .chat(messages, tools=None) -> dict (see
          llm/client.py's canonical message shape) - typed structurally, not
          as the concrete LLMClient class, for the same testability reason
          head.converse()'s llm_client argument is.
        context_fn: called fresh before every reply this agent formulates,
          not before messages it merely relays - its return value (a plain
          dict) is what grounds that reply in real local state. Optional;
          omitting it means replies are ungrounded narration only.
        """
        self._bus = bus
        self._llm_client = llm_client
        self._context_fn = context_fn or (lambda: {})
        self._lock = threading.Lock()
        self._waiting: dict[str, Callable[[str, str], None]] = {}  # conv_id -> reply handler (I'm the initiator)
        self._sessions: dict[str, list[dict]] = {}  # conv_id -> transcript (I'm the responder)

    def start(self, target_agent_id: str, opening_message: str, on_reply: Callable[[str, str], None]) -> str:
        """
        Send the first message of a new conversation. Non-blocking.
        on_reply(content, sender) fires once, on a new thread, when the
        other side answers - call start()/reply() again from inside it to
        continue, or don't, to let the conversation end there.
        """
        conv_id = str(uuid.uuid4())
        with self._lock:
            self._waiting[conv_id] = on_reply
        self._bus.Send(target_agent_id, {
            "type": "agent_message", "conversation_id": conv_id, "content": opening_message,
        })
        return conv_id

    def reply(self, target_agent_id: str, conv_id: str, message: str, on_reply: Callable[[str, str], None]) -> None:
        """Continue a conversation you started, after hearing back - same
        registration discipline as start(), same conv_id."""
        with self._lock:
            self._waiting[conv_id] = on_reply
        self._bus.Send(target_agent_id, {
            "type": "agent_message", "conversation_id": conv_id, "content": message,
        })

    def handle(self, msg: dict) -> None:
        """
        Wire this into a bus's default_handler (see worker.start_dispatch())
        for "agent_message" traffic. Always fast and non-blocking itself -
        both branches below spawn their own thread, so a caller never needs
        to remember to do that.
        """
        body = msg.get("body", {})
        if body.get("type") != "agent_message":
            return
        conv_id = body.get("conversation_id")
        content = body.get("content", "")
        sender = msg.get("from")

        with self._lock:
            waiter = self._waiting.pop(conv_id, None)
        if waiter is not None:
            threading.Thread(target=waiter, args=(content, sender), daemon=True).start()
            return

        threading.Thread(target=self._respond, args=(conv_id, sender, content), daemon=True).start()

    def _respond(self, conv_id: str, sender: str, content: str) -> None:
        with self._lock:
            history = self._sessions.setdefault(conv_id, [])
        history = list(history)  # work on a local copy, write back under lock below
        history.append({"role": "user", "content": content})

        context = self._context_fn()
        messages = [{"role": "system", "content": _system_prompt(self._bus.agentId, context)}] + history

        turn = self._llm_client.chat(messages)
        reply_text = turn.get("content") or ""
        history.append({"role": "assistant", "content": reply_text})

        with self._lock:
            self._sessions[conv_id] = history

        self._bus.Send(sender, {"type": "agent_message", "conversation_id": conv_id, "content": reply_text})

    def forget(self, conv_id: str) -> None:
        """Drop tracked state for a conversation - call once you know it's
        concluded (e.g. the initiator decided not to reply again), same
        cleanup discipline as router.py/conversation_store.py's forget()."""
        with self._lock:
            self._waiting.pop(conv_id, None)
            self._sessions.pop(conv_id, None)
