"""
Worker-side dispatch.

For any well-defined, already-invoked skill, the worker does not run its own
LLM call at all - the head's LLM already decided which skill applies and
sent a fully structured instruction, so re-interpreting it with another LLM
call would just reintroduce the ambiguity-compounding problem one hop later.
handle_message() is a thin, deterministic lookup from message type -> Skill
handler.

start_dispatch() is what actually drives handle_message() now: it wires
this worker's global-bus MessageRouter (buses.py) to spawn a new daemon
thread per incoming skill_contribute/skill_coordinate message, instead of
handling one message at a time in a blocking poll loop. That used to be a
real limitation (see the git history for this docstring's previous
wording): a worker acting as coordinator blocks inside skill.coordinate()
for up to its coordinate_timeout, and a single blocking Receive()-then-
handle loop couldn't service a second dispatch in that window at all.

This only works because the router (router.py), not this module, is the
sole caller of the global bus's Receive() - handle_message() itself never
touches buses.global_bus.Receive() or buses.local_bus.Receive() directly,
and neither does any Skill's contribute()/coordinate() (they go through
ctx.buses.local_router). Spawning a thread per message here is safe
specifically because message delivery to the right in-flight request is
already handled by the router underneath, not because threads+shared-FIFO
receive is safe in general (it is not - see router.py's docstring).
"""
import threading

from scarlet_agentic_harness.buses import Buses
from scarlet_agentic_harness.config import HarnessConfig
from scarlet_agentic_harness.context import HarnessContext
from scarlet_agentic_harness.dialogue import AgentDialogue
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


def start_dispatch(
    config: HarnessConfig,
    buses: Buses,
    skills: dict[str, Skill],
    dialogue: AgentDialogue | None = None,
) -> None:
    """
    Start servicing this worker's incoming dispatch messages concurrently.
    Call once at startup. After this, a new skill_contribute/skill_coordinate
    message arriving while an earlier one is still being handled (e.g. this
    worker is coordinating a slow skill.coordinate()) gets its own thread
    immediately, rather than waiting behind it.

    dialogue: if given (i.e. an LLM backend is configured - see __main__.py),
    agent_message traffic (dialogue.py) on the global bus is routed to it
    instead of being silently dropped. AgentDialogue.handle() manages its
    own threading internally, so it's safe to call directly here rather
    than wrapping it in another spawned thread.
    """
    def _dispatch(msg: dict) -> None:
        msg_type = msg.get("body", {}).get("type")
        if msg_type in ("skill_contribute", "skill_coordinate"):
            threading.Thread(
                target=handle_message, args=(msg, config, buses, skills), daemon=True
            ).start()
        elif msg_type == "agent_message" and dialogue is not None:
            dialogue.handle(msg)
        # else: unrecognized message, or agent_message with no dialogue
        # configured - dropped, matching prior behavior for anything
        # nobody's set up to handle.

    buses.global_router.default_handler = _dispatch
