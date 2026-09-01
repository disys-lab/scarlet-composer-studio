"""
CreateScarletSkill — mints a scarlet via the same generic Skill dispatch
mechanism as median/sum, invocable by ANY agent: head (via run_skill()/
converse(), same as always), or any worker acting as coordinator or
contributor (via HarnessContext.invoke_skill() - see context.py), with no
head involvement required at all.

This is the deliberate generalization of two narrower things already in
this codebase:
  - head.py's _register_scarlets() mints scarlets a skill *author* already
    declared in code (Skill.scarlet_names()) - the name is fixed at code
    time, only the description is real LLM reasoning, and only head does it.
  - HarnessContext.mint_scarlet() lets one worker mint a scarlet
    unilaterally, mid-task, for its own use.

This skill is the case in between: any agent, at any point, can dispatch
"I need a shared bucket for X" as a real distributed request - contributors
signal they're in, the coordinator does the actual minting (real LLM
reasoning over name/type/description via ctx.mint_scarlet(), reusing that
exact primitive rather than duplicating it), and the *result* - the
concrete registered name - flows back to whoever dispatched it. That's the
concrete path an agent can build on to carry out aggregation/dissemination
of a vector, matrix, or tensor across peers without depending on head to
broker it: dispatch create_scarlet peer-to-peer for the shared bucket, then
dispatch whatever aggregation happens next using the name it returns.

Structurally identical to sum/median on purpose ("similar to other
mathematical skills"): contribute() signals readiness on the local bus
exactly like they do, coordinate() waits for it, then does its one real
piece of work. The "computation" here just happens to be "decide on and
register a scarlet" instead of "reduce N local values."
"""
import time

from scarlet_agentic_harness.context import HarnessContext
from scarlet_agentic_harness.skills.base import Skill

_READY_MSG_TYPE = "create_scarlet_contribution_ready"


class CreateScarletSkill(Skill):
    name = "create_scarlet"
    description = (
        "Mint a new scarlet - a shared, Redis-backed bucket other agents can discover "
        "and read the contract of - for aggregating or disseminating a mathematical "
        "artifact (a scalar, vector, matrix, or tensor) across the participating agents. "
        "The name, type, and description are decided by the coordinating agent's own "
        "reasoning, grounded in the stated purpose - not fixed in advance. Any agent can "
        "invoke this, not only the head: a worker can dispatch it to its peers directly "
        "to establish shared coordination infrastructure without routing through the head "
        "at all."
    )
    parameters = {
        "type": "object",
        "properties": {
            "purpose": {
                "type": "string",
                "description": (
                    "What this scarlet will be used for - e.g. 'aggregating a 128-dim "
                    "gradient tensor across 4 peers each round' or 'disseminating a shared "
                    "embedding matrix computed by one worker to the others'. This is the "
                    "entire grounding the coordinator's reasoning gets for choosing the "
                    "name/type/description - be concrete."
                ),
            },
            "artifact_kind": {
                "type": "string",
                "enum": ["scalar", "vector", "matrix", "tensor"],
                "description": "The shape of the mathematical artifact this scarlet will hold, if known.",
            },
        },
        "required": ["purpose"],
    }
    coordinate_timeout = 15.0

    def contribute(self, ctx: HarnessContext, request: dict) -> None:
        # No local computation to do - a contributor's only job is to
        # signal it's alive and aware of this shared resource being
        # established, same readiness-handshake shape as sum.py/median.py.
        # Always sent, even to self if this worker is also the coordinator
        # - see median.py's contribute() for why (a coordinator-side
        # failure has nowhere else to be reported otherwise).
        ctx.buses.local_bus.Send(request["coordinator"], {
            "type": _READY_MSG_TYPE,
            "request_id": request["request_id"],
            "from": ctx.agent_id,
        })

    def coordinate(self, ctx: HarnessContext, request: dict, workers: list[str]) -> dict:
        try:
            return self._coordinate(ctx, request, workers)
        finally:
            # Same leak-prevention as sum.py/median.py - see router.py.
            ctx.buses.local_router.forget(request["request_id"])

    def _coordinate(self, ctx: HarnessContext, request: dict, workers: list[str]) -> dict:
        ready_from: set[str] = set()
        ctx.report_progress(ready_count=0, expected_count=len(workers))
        deadline = time.time() + self.coordinate_timeout
        while len(ready_from) < len(workers) and time.time() < deadline:
            if ctx.cancelled.is_set():
                return {"status": "error", "detail": "cancelled", "retryable": False}
            msg = ctx.buses.local_router.receive_for(request["request_id"], timeout=1)
            if not msg:
                continue
            body = msg.get("body", {})
            if body.get("type") == _READY_MSG_TYPE:
                ready_from.add(body["from"])
                ctx.report_progress(ready_count=len(ready_from), expected_count=len(workers))

        if ctx.cancelled.is_set():
            return {"status": "error", "detail": "cancelled", "retryable": False}

        missing = set(workers) - ready_from
        if missing:
            return {
                "status": "error",
                "detail": f"workers did not report ready in time: {sorted(missing)}",
                "retryable": True,
            }

        params = request.get("params", {})
        purpose = params.get("purpose", "")
        artifact_kind = params.get("artifact_kind")
        motivation = (
            f"A distributed computation needs a new shared scarlet, to be used by "
            f"{len(workers)} participating agent(s) ({', '.join(sorted(workers))}). "
            f"Purpose: {purpose}"
            + (f" Artifact kind: {artifact_kind}." if artifact_kind else "")
        )

        try:
            registered_name = ctx.mint_scarlet(motivation)
        except Exception as exc:
            # Both ScarletMintingFailed (model didn't call the tool) and a
            # RuntimeError (this coordinator has no llm_client configured)
            # are plausibly transient from the *system's* perspective: a
            # retry picks a fresh (possibly different) coordinator, which
            # may have a working LLM backend or better luck this time - see
            # Skill.coordinator_for()'s random default.
            return {
                "status": "error",
                "detail": f"failed to mint scarlet: {exc}",
                "retryable": True,
            }

        return {
            "status": "ok",
            "result": {"name": registered_name, "purpose": purpose, "artifact_kind": artifact_kind},
            "detail": f"scarlet {registered_name!r} minted for {len(workers)} participating agent(s): {purpose}",
        }
