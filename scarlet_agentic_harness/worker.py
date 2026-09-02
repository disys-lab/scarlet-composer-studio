"""
Worker-side dispatch.

Which skill runs is never re-decided here: the head's LLM already decided
that and sent a fully structured instruction, so re-interpreting *that*
choice with another LLM call would just reintroduce the ambiguity-
compounding problem one hop later. handle_message() is a thin, deterministic
lookup from message type -> Skill handler for that part.

What a worker's own LLM *can* now do, once handle_message() has already
made that deterministic choice and is running the resulting
contribute()/coordinate(): mint an ad hoc scarlet mid-task, via
HarnessContext.mint_scarlet() (scarlet_minting.py), for shared state a
skill's own code decides it needs but couldn't have declared in advance
via Skill.scarlet_names() (contrast head.py's dispatch-time
_register_scarlets, which only ever generates a *description* for names
the skill author already fixed in code). This is a bounded decision inside
an already-selected skill, not a re-decision of which skill to run, so it
doesn't reopen the problem above - see scarlet_minting.py's docstring for
the full argument. llm_client is None unless this worker process has
LLM_BASE_URL configured (see __main__.py); a skill that calls
ctx.mint_scarlet() without one gets a clear, immediate error, not a silent
no-op.

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

Cancellation: _dispatch() creates a CancellationToken (cancellation.py)
*synchronously*, before spawning handle_message()'s thread - not inside
that thread. This matters because MessageRouter's default_handler calls
are never concurrent with each other on the same router (there is exactly
one polling thread calling Receive() then default_handler() in a loop -
see router.py), so as long as token creation happens before _dispatch()
returns, a skill_cancel for the same request_id arriving right after (and
necessarily processed *after*, on that same single-threaded loop) can
never race ahead of it. Creating the token inside the spawned thread
instead would reopen exactly that race.
"""
import threading

from scarlets.utils.RedisLogger import RedisLogger

from scarlet_agentic_harness.buses import Buses
from scarlet_agentic_harness.cancellation import CancellationRegistry, CancellationToken
from scarlet_agentic_harness.config import HarnessConfig
from scarlet_agentic_harness.context import HarnessContext
from scarlet_agentic_harness.dialogue import AgentDialogue
from scarlet_agentic_harness.scarlet_minting import ChatClient
from scarlet_agentic_harness.skills.base import Skill


def handle_message(
    msg: dict,
    config: HarnessConfig,
    buses: Buses,
    skills: dict[str, Skill],
    token: CancellationToken,
    llm_client: "ChatClient | None" = None,
) -> None:
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

    ctx = HarnessContext(config, buses, cancellation=token, llm_client=llm_client)
    skill.contribute(ctx, body)

    if msg_type == "skill_coordinate":
        result = skill.coordinate(ctx, body, body.get("workers", []))
        RedisLogger.info(
            f"[{config.agent_id}] finished coordinating {skill.name!r} "
            f"request={body.get('request_id')} status={result.get('status')}"
        )
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
    registry: CancellationRegistry | None = None,
    llm_client: "ChatClient | None" = None,
) -> CancellationRegistry:
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

    llm_client: same "is an LLM backend configured" condition as dialogue
    (in practice __main__.py constructs one LLMClient and passes it to
    both) - threaded through to every HarnessContext this worker builds, so
    a skill's contribute()/coordinate() can call ctx.mint_scarlet(). None
    (the default) means skills running on this worker that try to mint a
    scarlet get a clear, immediate error rather than a silent no-op - see
    HarnessContext.mint_scarlet().

    registry: this worker's CancellationRegistry - constructed here if not
    given (existing callers that don't need one, e.g. most tests, are
    unaffected), but a caller that wants live observability (see
    observability.py) or a context_fn grounded in real in-flight state
    (see dialogue.py) needs to construct its own CancellationRegistry
    (optionally wired to a shared Mapper - see __main__.py) and pass it in
    *before* calling start_dispatch(), so it can also be handed to
    AgentDialogue's context_fn. Returned either way, so a caller that let
    this function construct one can still get a handle to it.

    skill_cancel messages (sent by head.run_skill() when a retry
    supersedes an earlier attempt) look up the matching request_id in the
    registry and cancel its token, if this worker is still tracking it - a
    cancel for a request that already finished, or that this worker was
    never part of, is a normal race, not an error (see cancellation.py).
    """
    registry = registry if registry is not None else CancellationRegistry()

    def _dispatch(msg: dict) -> None:
        body = msg.get("body", {})
        msg_type = body.get("type")
        request_id = body.get("request_id")

        if msg_type in ("skill_contribute", "skill_coordinate"):
            token = registry.create(request_id, skill_name=body.get("skill", ""))
            RedisLogger.info(
                f"[{config.agent_id}] started {msg_type} for skill={body.get('skill')!r} request={request_id}"
            )

            def run():
                try:
                    handle_message(msg, config, buses, skills, token, llm_client=llm_client)
                finally:
                    registry.forget(request_id)

            threading.Thread(target=run, daemon=True).start()
        elif msg_type == "skill_cancel":
            RedisLogger.info(f"[{config.agent_id}] received skill_cancel for request={request_id}")
            registry.cancel(request_id)
        elif msg_type == "agent_message" and dialogue is not None:
            dialogue.handle(msg)
        # else: unrecognized message, or agent_message with no dialogue
        # configured - dropped, matching prior behavior for anything
        # nobody's set up to handle.

    buses.global_router.default_handler = _dispatch
    return registry
