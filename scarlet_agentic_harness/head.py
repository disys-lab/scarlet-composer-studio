"""
Head-side orchestration.

run_skill() is the generic dispatch logic every skill invocation goes
through - resolve live workers, decide a coordinator, dispatch, wait for the
result. It is deliberately skill-agnostic (never imports a specific Skill
subclass) so that adding a new skill never requires touching this function.

converse() wraps run_skill() with an LLM tool-calling loop that turns a
human's free-text request into zero or more skill invocations and a final
natural-language reply - the actual "multi-turn, possibly-composing-skills"
loop described for the variance example. It takes an `llm_client` argument
typed only as anything with a `.chat(messages, tools) -> dict` method (see
llm/client.py's canonical message shape) - not the concrete LLMClient class -
specifically so it's testable with a scripted fake today, with zero changes
needed once a real LLM backend exists. See tests/test_head_converse.py
(control flow, no Redis) and tests/test_converse_end_to_end.py (real
subprocess workers + real Redis, LLM decisions still scripted).
"""
import time
import uuid
from typing import Protocol

from scarlet_agentic_harness.buses import Buses
from scarlet_agentic_harness.config import HarnessConfig
from scarlet_agentic_harness.context import HarnessContext
from scarlet_agentic_harness.skills.base import Skill


class ChatClient(Protocol):
    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict: ...


def run_skill(skill: Skill, params: dict, config: HarnessConfig, buses: Buses) -> dict:
    """
    Dispatch one invocation of `skill` across currently-registered workers
    and return the final result dict (shape: {"status": "ok"/"error", ...}).
    Runs on the head. Workers are discovered fresh via GatherStatus() on
    every call, per DESIGN_v3.md section 8.5 - never a hardcoded topology.
    """
    ctx = HarnessContext(config, buses)

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
        # Only reached if a skill explicitly overrides coordinator_for() to
        # return the head - not the default (Skill's base default is a
        # random worker, so the head stays a pure router under concurrent
        # load rather than becoming a bottleneck for every skill's
        # aggregation step). When it is reached: run coordinate() in-process,
        # no message round trip needed. The head never runs contribute():
        # it holds no data of its own in this
        # design, it only orchestrates.
        return skill.coordinate(ctx, request, workers)

    deadline = time.time() + skill.coordinate_timeout + 10  # slack over the coordinator's own internal timeout
    while time.time() < deadline:
        msg = buses.global_bus.Receive(timeout=1)
        if not msg:
            continue
        body = msg.get("body", {})
        if body.get("type") == "skill_result" and body.get("request_id") == request_id:
            return body

    return {"status": "error", "detail": f"coordinator {coordinator} did not respond in time"}


class ConversationDidNotConclude(RuntimeError):
    """Raised if the model keeps calling tools past max_turns without ever
    producing a final answer - a real safety limit, not a soft warning:
    without one, a model stuck in a tool-calling loop runs indefinitely."""


def converse(
    human_message: str,
    config: HarnessConfig,
    buses: Buses,
    skills: dict[str, Skill],
    llm_client: ChatClient,
    max_turns: int = 5,
) -> str:
    """
    Turn one human message into zero or more skill invocations and a final
    natural-language reply. A single call can involve multiple tool-call
    turns - this is what makes the variance-via-two-sum-calls composition
    possible without any new infrastructure: the model can request another
    skill, or several in one turn, after seeing an earlier result, and
    run_skill() is called fresh each time with zero knowledge of the turn
    before it.
    """
    tools = [s.as_tool_schema() for s in skills.values()]
    messages: list[dict] = [{"role": "user", "content": human_message}]

    for _ in range(max_turns):
        turn = llm_client.chat(messages, tools=tools)
        messages.append(turn)

        if not turn["tool_calls"]:
            return turn["content"] or ""

        for call in turn["tool_calls"]:
            skill = skills.get(call["name"])
            if skill is None:
                result = {"status": "error", "detail": f"unknown skill {call['name']!r}"}
            else:
                result = run_skill(skill, call["arguments"], config, buses)
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})

    raise ConversationDidNotConclude(f"model did not produce a final answer within {max_turns} turns")
