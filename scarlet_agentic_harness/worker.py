"""
Worker-side dispatch.

For any well-defined, already-invoked skill, the worker does not run its own
LLM call at all - the head's LLM already decided which skill applies and
sent a fully structured instruction, so re-interpreting it with another LLM
call would just reintroduce the ambiguity-compounding problem one hop later.
handle_message() is a thin, deterministic lookup from message type -> Skill
handler.

Note: a worker handles one skill invocation at a time. While acting as
coordinator, it blocks inside skill.coordinate() (which does its own
local_bus polling) rather than continuing to service the outer dispatch
loop. Fine for this build; a known limitation to revisit if concurrent
invocations on the same worker are ever needed.
"""
from scarlet_agentic_harness.buses import Buses
from scarlet_agentic_harness.config import HarnessConfig
from scarlet_agentic_harness.context import HarnessContext
from scarlet_agentic_harness.skills.base import Skill


def handle_message(msg: dict, config: HarnessConfig, buses: Buses, skills: dict[str, Skill]) -> None:
    body = msg.get("body", {})
    msg_type = body.get("type")
    if msg_type not in ("skill_contribute", "skill_coordinate"):
        return  # not a skill dispatch message - ignore

    skill = skills.get(body.get("skill"))
    if skill is None:
        buses.global_bus.Send(msg["from"], {
            "type": "skill_result",
            "request_id": body.get("request_id"),
            "status": "error",
            "detail": f"unknown skill {body.get('skill')!r}",
        })
        return

    ctx = HarnessContext(config, buses)
    skill.contribute(ctx, body)

    if msg_type == "skill_coordinate":
        result = skill.coordinate(ctx, body, body.get("workers", []))
        buses.global_bus.Send(msg["from"], {
            "type": "skill_result",
            "request_id": body.get("request_id"),
            **result,
        })


def poll_once(config: HarnessConfig, buses: Buses, skills: dict[str, Skill], timeout: float = 0) -> bool:
    """Check the global bus once for a dispatch message. Returns True if one was handled."""
    msg = buses.global_bus.Receive(timeout=timeout)
    if msg:
        handle_message(msg, config, buses, skills)
        return True
    return False
