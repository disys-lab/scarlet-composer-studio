"""
Head-side orchestration.

run_skill() is the generic dispatch logic every skill invocation goes
through - resolve live workers, decide a coordinator, dispatch, wait for the
result. It is deliberately skill-agnostic (never imports a specific Skill
subclass) so that adding a new skill never requires touching this function.
It retries transient mid-computation failures (a coordinator that never
responds, a coordinator that reports a worker dropped out) with a fresh
worker survey and a fresh coordinator, up to `max_attempts` - see the
`retryable` flag convention in its docstring below. It waits for the
coordinator's reply via buses.global_router (never buses.global_bus.Receive()
directly - see router.py/buses.py for why sharing Receive() across
concurrent callers is unsafe with scarlets' actual transport).

converse() wraps run_skill() with an LLM tool-calling loop that turns a
human's free-text request into zero or more skill invocations and a final
natural-language reply - the actual "multi-turn, possibly-composing-skills"
loop described for the variance example. It takes an `llm_client` argument
typed only as anything with a `.chat(messages, tools) -> dict` method (see
llm/client.py's canonical message shape) - not the concrete LLMClient class -
specifically so it's testable with a scripted fake today, with zero changes
needed once a real LLM backend exists. It returns a ConverseResult carrying
the full message transcript (not just the final string) and takes an
optional `on_event` callback fired synchronously as the turn unfolds -
narration, tool calls, and tool results that used to be silently discarded
the moment a turn also contained tool_calls are now both retained (in
`.messages`) and observable in real time (via `on_event`). Previously
nothing outside this function ever saw a model's "I'm going to do X because
Y" narration if it happened to accompany a tool call in the same turn -
only a bare final answer, or nothing at all, survived. See
tests/test_head_converse.py (control flow, no Redis) and
tests/test_converse_end_to_end.py (real subprocess workers + real Redis,
LLM decisions still scripted).
"""
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Protocol

from scarlet_agentic_harness.buses import Buses
from scarlet_agentic_harness.config import HarnessConfig
from scarlet_agentic_harness.context import HarnessContext
from scarlet_agentic_harness.skills.base import Skill


class ChatClient(Protocol):
    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict: ...


def _wait_for_result(buses: Buses, request_id: str, timeout: float) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        remaining = max(0.0, deadline - time.time())
        msg = buses.global_router.receive_for(request_id, timeout=(min(1.0, remaining) or 0.01))
        if msg:
            return msg.get("body", {})
    return {"status": "error", "detail": "coordinator did not respond in time", "retryable": True}


def run_skill(
    skill: Skill,
    params: dict,
    config: HarnessConfig,
    buses: Buses,
    max_attempts: int = 2,
    reply_slack: float = 10.0,
) -> dict:
    """
    Dispatch one invocation of `skill` across currently-registered workers
    and return the final result dict (shape: {"status": "ok"/"error", ...}).
    Runs on the head. Workers are discovered fresh via GatherStatus() on
    every call (and again on every retry attempt), per DESIGN_v3.md section
    8.5 - never a hardcoded topology, which is exactly what lets a retry
    naturally exclude a worker that went offline mid-computation without any
    special-cased "remove this worker" logic.

    A failed attempt is retried (fresh request_id, fresh worker survey,
    possibly a new coordinator) only if the result carries `"retryable":
    True` - set by a Skill's coordinate() for failures that are plausibly
    transient (a contributor never signaled ready, an AllGather/Aggregate
    call failed, the coordinator never replied at all). Failures that would
    just happen again regardless of which worker runs them (e.g. combine's
    "bad expression" errors) are not retryable, and skills that don't set
    the flag at all default to not-retryable - the conservative choice, so
    a skill written before this existed doesn't get retried by accident.
    "no worker currently reports this capability" is a precondition check
    before any dispatch happens, not a mid-computation failure, so it is
    never retried here.

    reply_slack: extra seconds beyond the coordinator's own coordinate_timeout
    that the head waits for a reply before giving up on that attempt - real
    slack accounts for message round-trip time on top of the coordinator's
    internal deadline. Overridable mainly so tests can shrink it instead of
    waiting through a real ~10s timeout to prove retry behavior.
    """
    ctx = HarnessContext(config, buses)
    last_result: dict = {}

    for _attempt in range(1, max_attempts + 1):
        workers_info = buses.gather_workers()
        workers = [w for w, rec in workers_info.items() if skill.name in rec.get("capabilities", [])]
        if not workers:
            return {"status": "error", "detail": f"no online worker currently reports the {skill.name!r} capability"}

        request_id = str(uuid.uuid4())
        coordinator = skill.coordinator_for(ctx, workers)

        request = {
            "request_id": request_id,
            "skill": skill.name,
            "mapper_name": f"{skill.name}_{request_id}",
            "coordinator": coordinator,
            "workers": workers,
            "params": params,
        }

        for worker_id in workers:
            msg_type = "skill_coordinate" if worker_id == coordinator else "skill_contribute"
            buses.global_bus.Send(worker_id, {"type": msg_type, **request})

        if coordinator == config.agent_id:
            # Only reached if a skill explicitly overrides coordinator_for()
            # to return the head - not the default (Skill's base default is
            # a random worker, so the head stays a pure router under
            # concurrent load rather than becoming a bottleneck for every
            # skill's aggregation step). The head never runs contribute():
            # it holds no data of its own in this design, it only
            # orchestrates.
            result = skill.coordinate(ctx, request, workers)
        else:
            try:
                result = _wait_for_result(buses, request_id, skill.coordinate_timeout + reply_slack)
            finally:
                # Router queues are keyed by request_id (a UUID, never
                # reused) - without this, every invocation leaks one queue
                # for the head's process lifetime. See router.py.
                buses.global_router.forget(request_id)

        if result.get("status") == "ok":
            return result
        last_result = result
        if not result.get("retryable", False):
            return result
        # else: transient failure - loop again with a fresh survey/attempt
        # if one remains; falling out of the loop returns last_result below.

    return last_result


class ConversationDidNotConclude(RuntimeError):
    """Raised if the model keeps calling tools past max_turns without ever
    producing a final answer - a real safety limit, not a soft warning:
    without one, a model stuck in a tool-calling loop runs indefinitely."""

    def __init__(self, message: str, messages: list[dict]):
        super().__init__(message)
        self.messages = messages  # full transcript so far, for post-mortem


@dataclass
class ConverseResult:
    """
    converse()'s return value. `answer` is the same final string it always
    returned; `messages` is the full canonical-shape transcript (every turn,
    every tool call, every tool result) that used to be discarded the moment
    the function returned - kept for post-hoc audit, not just what
    on_event saw as it happened.
    """
    answer: str
    messages: list[dict] = field(default_factory=list)


def converse(
    human_message: str,
    config: HarnessConfig,
    buses: Buses,
    skills: dict[str, Skill],
    llm_client: ChatClient,
    max_turns: int = 5,
    on_event: Callable[[dict], None] | None = None,
) -> ConverseResult:
    """
    Turn one human message into zero or more skill invocations and a final
    natural-language reply. A single call can involve multiple tool-call
    turns - this is what makes the variance-via-two-sum-calls composition
    possible without any new infrastructure: the model can request another
    skill, or several in one turn, after seeing an earlier result, and
    run_skill() is called fresh each time with zero knowledge of the turn
    before it.

    If `on_event` is given, it is called synchronously (in this thread, in
    order) for:
      - {"type": "narration", "turn": i, "content": ...} whenever a turn
        carries non-empty content - including when it *also* carries tool
        calls, which is exactly the case that used to vanish silently.
      - {"type": "tool_call", "turn": i, "call_id", "skill", "params"}
        right before dispatch.
      - {"type": "tool_result", "turn": i, "call_id", "skill", "result"}
        right after dispatch.
      - {"type": "final", "content": ...} when the loop concludes with a
        direct answer.
    A raising on_event propagates immediately - it runs in-line, not as a
    fire-and-forget side channel, so a caller using it to gate execution
    (e.g. "ask a human before running this") can actually block or abort.
    """
    tools = [s.as_tool_schema() for s in skills.values()]
    messages: list[dict] = [{"role": "user", "content": human_message}]

    def emit(event: dict) -> None:
        if on_event is not None:
            on_event(event)

    for turn_index in range(max_turns):
        turn = llm_client.chat(messages, tools=tools)
        messages.append(turn)

        if not turn["tool_calls"]:
            answer = turn["content"] or ""
            emit({"type": "final", "content": answer})
            return ConverseResult(answer=answer, messages=messages)

        if turn.get("content"):
            # Only the "narration alongside a tool call" case counts as a
            # separate event - a turn with no tool_calls already emits
            # "final" above with the same content, and double-emitting both
            # for that turn would misrepresent one turn as two events.
            emit({"type": "narration", "turn": turn_index, "content": turn["content"]})

        for call in turn["tool_calls"]:
            skill = skills.get(call["name"])
            emit({"type": "tool_call", "turn": turn_index, "call_id": call["id"], "skill": call["name"], "params": call["arguments"]})
            if skill is None:
                result = {"status": "error", "detail": f"unknown skill {call['name']!r}"}
            else:
                result = run_skill(skill, call["arguments"], config, buses)
            emit({"type": "tool_result", "turn": turn_index, "call_id": call["id"], "skill": call["name"], "result": result})
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})

    raise ConversationDidNotConclude(f"model did not produce a final answer within {max_turns} turns", messages)
