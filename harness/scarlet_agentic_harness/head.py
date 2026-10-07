"""
The head's conversation loop.

`converse` turns one human message into zero or more skill invocations
and a final natural-language reply, driving the LLM's tool calls through
`dispatch.run_skill` and joining their asynchronous results.

Dispatch itself lives in dispatch.py and is generic - see that module's
docstring. Only what is genuinely head-specific remains here: the
conversation loop, its result type, and the joiner that waits on
concurrent skill calls.
"""

import threading
import uuid
from dataclasses import dataclass, field
from typing import Callable

from scarlets.utils.RedisLogger import RedisLogger

from scarlet_agentic_harness.buses import Buses
from scarlet_agentic_harness.config import HarnessConfig
from scarlet_agentic_harness.conversation_store import ConversationStore
from scarlet_agentic_harness.dialogue import AgentDialogue
from scarlet_agentic_harness.dispatch import ChatClient, run_skill
from scarlet_agentic_harness.skills.base import Skill


class ConversationDidNotConclude(RuntimeError):
    """
    Raised when the model keeps calling tools past `max_turns` without ever producing a final answer.

    Delivered via `converse`'s `on_done` error argument, not a real raise
    across threads. A real safety limit, not a soft warning: without
    one, a model stuck in a tool-calling loop runs indefinitely.

    Parameters
    ----------
    message : str
    messages : list of dict
        Full transcript so far, for post-mortem.

    Attributes
    ----------
    messages : list of dict
    """

    def __init__(self, message: str, messages: list[dict]):
        super().__init__(message)
        self.messages = messages  # full transcript so far, for post-mortem


@dataclass
class ConverseResult:
    """
    `converse`'s result, delivered via `on_done`, not a return value.

    Attributes
    ----------
    answer : str
        The final natural-language reply.
    messages : list of dict
        The full canonical-shape transcript (every turn, every tool
        call, every tool result) - kept for post-hoc audit, not just
        what `on_event` saw as it happened.
    """
    answer: str
    messages: list[dict] = field(default_factory=list)


class _Joiner:
    """
    Collect N async tool-call results for one turn, then run `on_all_done` exactly once.

    Results are keyed by call id in the turn's original order - not
    completion order, which varies now that each tool call dispatches
    independently instead of one after another. The decrement-and-check
    is done atomically under one lock so exactly one thread ever
    observes "that was the last one", regardless of which call's result
    arrives last.

    Parameters
    ----------
    calls : list of dict
        This turn's tool calls, each with an ``"id"`` key.
    on_all_done : callable
        ``(results_by_id: dict) -> None``, called once every call has a
        result, with results in `calls`' original order.
    """

    def __init__(self, calls: list[dict], on_all_done: Callable[[dict], None]):
        self._calls = calls
        self._on_all_done = on_all_done
        self._results: dict[str, dict] = {}
        self._remaining = len(calls)
        self._lock = threading.Lock()

    def submit(self, call_id: str, result: dict) -> None:
        """
        Record one call's result; run `on_all_done` if this was the last one.

        Parameters
        ----------
        call_id : str
        result : dict
        """
        with self._lock:
            self._results[call_id] = result
            self._remaining -= 1
            done = self._remaining == 0
        if done:
            ordered = {call["id"]: self._results[call["id"]] for call in self._calls}
            self._on_all_done(ordered)


def converse(
    human_message: str,
    config: HarnessConfig,
    buses: Buses,
    skills: dict[str, Skill],
    llm_client: ChatClient,
    on_done: Callable[["ConverseResult | None", Exception | None], None],
    # Callers in this package pass config.converse_max_turns explicitly.
    # This default exists for tests and ad-hoc callers; it tracks the
    # config default rather than the old hardcoded 5, so forgetting the
    # kwarg degrades to "generous" instead of to "fails on any realistic
    # multi-skill request".
    max_turns: int = 30,
    on_event: Callable[[dict], None] | None = None,
    store: ConversationStore | None = None,
    dialogue: AgentDialogue | None = None,
) -> None:
    """
    Turn one human message into zero or more skill invocations and a final natural-language reply.

    Does not block and does not return anything - ``on_done(result,
    error)`` fires exactly once, on some later thread, with either a
    `ConverseResult` or a `ConversationDidNotConclude` (never both).

    A single call can involve multiple tool-call turns, and a single
    turn can request multiple tool calls at once - those dispatch
    concurrently (via `run_skill`, itself non-blocking) rather than one
    after another. The turn only advances once every call in it has
    replied (see `_Joiner`), and results are placed back into the
    transcript in the original call order regardless of which finished
    first, so the model always sees a deterministic conversation shape.

    `llm_client.chat` itself is still an ordinary blocking call - only
    the bus-mediated waiting (skill results, and check-in replies) is
    non-blocking. Blocking the thread currently running a turn for the
    LLM round-trip doesn't stall anything else, since it isn't a
    router's polling thread.

    Parameters
    ----------
    human_message : str
    config : HarnessConfig
    buses : Buses
    skills : dict of str to Skill
        Every skill this conversation may call, keyed by name.
    llm_client : ChatClient
    on_done : callable
        ``(result: ConverseResult | None, error: Exception | None) -> None``.
    max_turns : int, optional
        Safety limit on tool-calling turns. Default `5`.
    on_event : callable or None, optional
        If given, called synchronously (on whichever thread is running
        that turn, in order for that turn) for:

        - ``{"type": "question", "content": ...}`` once, first, carrying
          the message that started the conversation.

        - ``{"type": "narration", "turn": i, "content": ...}`` whenever
          a turn carries non-empty content alongside tool calls.
        - ``{"type": "tool_call", "turn": i, "call_id", "skill", "params"}``
          right before dispatch.
        - ``{"type": "dispatch", "turn": i, "call_id", "skill",
          "request_id", "attempt"}`` each time `run_skill` mints a
          request id for this call - once per attempt, so a retried call
          emits several. This is the only link between a tool call and
          the bus traffic it caused; nothing downstream can derive it.
        - ``{"type": "tool_result", "turn": i, "call_id", "skill", "result"}``
          right after a reply arrives.
        - ``{"type": "final", "content": ...}`` when the loop concludes.
    store : ConversationStore or None, optional
        Defaults to a fresh `ConversationStore` if not given.
    dialogue : AgentDialogue or None, optional
        If given, every `run_skill` call this conversation makes gets
        deliberation on timeout instead of an immediate mechanical
        retry, reusing this same `llm_client` for the deliberation call
        itself.
    """
    store = store if store is not None else ConversationStore()
    conv_id = str(uuid.uuid4())
    tools = [s.as_tool_schema() for s in skills.values()]
    store.create(conv_id, {"messages": [{"role": "user", "content": human_message}]})

    def emit(event: dict) -> None:
        if on_event is not None:
            # conv_id is stamped here rather than left to the caller
            # because it is minted inside this function - a caller cannot
            # know it before calling, and without it concurrent
            # conversations are indistinguishable in a shared event
            # stream. Every event carries it so any consumer can group a
            # whole exchange without tracking state of its own.
            on_event({"conv_id": conv_id, **event})

    # The question that started all this. Without it a consumer sees a
    # conversation's reasoning and its answer but never what was asked -
    # converse keeps the human message in its ConversationStore, which is
    # in-process and forgotten when the conversation ends.
    emit({"type": "question", "content": human_message})

    def finish(result: ConverseResult | None, error: Exception | None) -> None:
        store.forget(conv_id)
        on_done(result, error)

    def do_turn(turn_index: int) -> None:
        if turn_index >= max_turns:
            messages = store.get(conv_id)["messages"]
            finish(None, ConversationDidNotConclude(
                f"model did not produce a final answer within {max_turns} turns", messages))
            return

        messages = store.get(conv_id)["messages"]
        turn = llm_client.chat(messages, tools=tools)
        store.append(conv_id, "messages", turn)

        if not turn["tool_calls"]:
            answer = turn["content"] or ""
            emit({"type": "final", "content": answer})
            finish(ConverseResult(answer=answer, messages=store.get(conv_id)["messages"]), None)
            return

        if turn.get("content"):
            # Only the "narration alongside a tool call" case counts as a
            # separate event - a turn with no tool_calls already emits
            # "final" above with the same content.
            emit({"type": "narration", "turn": turn_index, "content": turn["content"]})

        calls = turn["tool_calls"]

        def on_all_results(results_by_id: dict) -> None:
            for call in calls:
                store.append(conv_id, "messages", {
                    "role": "tool", "tool_call_id": call["id"], "content": results_by_id[call["id"]],
                })
            do_turn(turn_index + 1)

        joiner = _Joiner(calls, on_all_results)

        for call in calls:
            skill = skills.get(call["name"])
            emit({"type": "tool_call", "turn": turn_index, "call_id": call["id"], "skill": call["name"], "params": call["arguments"]})
            if skill is None:
                result = {"status": "error", "detail": f"unknown skill {call['name']!r}"}
                emit({"type": "tool_result", "turn": turn_index, "call_id": call["id"], "skill": call["name"], "result": result})
                joiner.submit(call["id"], result)
            else:
                def on_result(result: dict, call=call) -> None:
                    emit({"type": "tool_result", "turn": turn_index, "call_id": call["id"], "skill": call["name"], "result": result})
                    joiner.submit(call["id"], result)

                # The only place the mapping from a tool call to the
                # request_id(s) it produced is knowable. run_skill mints a
                # fresh request_id per *attempt*, so a single call can span
                # several - and nothing downstream can reconstruct which
                # dispatch belonged to which call without being told. A
                # reader correlating by timestamp instead would get it
                # wrong the moment two calls overlap, which is the normal
                # case here: the model routinely issues several tool calls
                # in one turn.
                def on_dispatch(request_id: str, attempt: int, call=call) -> None:
                    emit({
                        "type": "dispatch", "turn": turn_index, "call_id": call["id"],
                        "skill": call["name"], "request_id": request_id, "attempt": attempt,
                    })

                run_skill(
                    skill, call["arguments"], config, buses, on_result,
                    dialogue=dialogue, llm_client=llm_client, on_dispatch=on_dispatch,
                    # A compound skill needs the registry to resolve its plan's
                    # steps, and on_event so each step shows as its own turn.
                    # Without these, run_skill's compound branch errors out and
                    # the model quietly falls back to composing the result by
                    # hand - which it does inconsistently, and sometimes wrong.
                    skills=skills, on_event=on_event,
                )

    do_turn(0)
