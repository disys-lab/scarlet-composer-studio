"""
Head-side orchestration.

run_skill() is the generic dispatch logic every skill invocation goes
through - resolve live workers, decide a coordinator, dispatch, wait for the
result. It is deliberately skill-agnostic (never imports a specific Skill
subclass) so that adding a new skill never requires touching this function.

HeadAgent wraps run_skill() with an LLM tool-calling loop that turns a
human's free-text request into a skill invocation. The loop and the dispatch
mechanics are kept separate on purpose: run_skill() is fully testable today
against real scarlets/Redis with no LLM backend at all (see
tests/test_median_skill.py); HeadAgent only becomes testable once real LLM
credentials are available.
"""
import time
import uuid

from scarlet_agentic_harness.buses import Buses
from scarlet_agentic_harness.config import HarnessConfig
from scarlet_agentic_harness.context import HarnessContext
from scarlet_agentic_harness.skills.base import Skill


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
