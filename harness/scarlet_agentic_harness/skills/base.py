"""
Skill — the generalization unit for scarlet-agentic-harness.

Any single well-defined distributed computation the head can offer to a
human and delegate across workers is a Skill, expressed entirely through
scarlets primitives (Mapper/Federator/Messenger, via HarnessContext) - never
a side channel. The median skill is the reference implementation; the actual
test of whether this interface generalizes is whether a new skill (sum,
mean, variance, ...) can be added as a new module implementing this
interface without changing head.py/worker.py's dispatch logic at all.

Two handlers, invoked on different agents by the harness's generic dispatch
logic (see head.py:run_skill / worker.py:handle_message) - a Skill
implementation never talks to Messenger's routing machinery directly:

  * contribute(ctx, request) runs on every worker asked to participate. Does
    local compute and publishes/signals via scarlets primitives. No return
    value - the real result surfaces through Mapper/Messenger, not a Python
    call stack, since contribute() and coordinate() run in different
    processes, often on different machines.

  * coordinate(ctx, request, workers) runs on exactly one agent - the
    coordinator, decided per-invocation by coordinator_for(). Gathers
    contributions and returns the final result as a JSON-serializable dict;
    that dict becomes (or is folded into) the skill_result message sent back
    to the head.
"""
import random
from abc import ABC, abstractmethod

from scarlet_agentic_harness.context import HarnessContext


class Skill(ABC):
    """
    The generalization unit for scarlet-agentic-harness.

    Any single well-defined distributed computation the head can offer
    to a human and delegate across workers is a `Skill`, expressed
    entirely through scarlets primitives (`Mapper`/`Federator`/
    `Messenger`, via `HarnessContext`) - never a side channel. A new
    skill is a new module implementing this interface, without changing
    `head`/`worker`'s dispatch logic at all.

    Two handlers, invoked on different agents by the harness's generic
    dispatch logic - a `Skill` implementation never talks to
    `Messenger`'s routing machinery directly.

    Attributes
    ----------
    name : str
        Tool/skill name, used for dispatch and the LLM tool schema.
    description : str
        Natural-language description, used in the LLM tool schema.
    parameters : dict
        JSON-schema "parameters" block for the LLM tool-call definition.
        Empty (the default) means the skill takes no arguments beyond
        being invoked by name.
    coordinate_timeout : float
        Seconds `coordinate` should wait for peer contributions before
        giving up. Per-skill because different skills have very
        different expected completion times. Default `15.0`.
    """

    name: str = ""
    description: str = ""
    parameters: dict = {"type": "object", "properties": {}, "required": []}
    coordinate_timeout: float = 15.0

    def coordinator_for(self, ctx: HarnessContext, workers: list[str]) -> str:
        """
        Decide which agent's coordinate() answers this invocation.

        Default: a randomly-chosen worker, not the head. Nothing about
        Mapper/Federator requires the head to be the one calling
        AllGather()/Aggregate() - that's just an application-level choice,
        and defaulting to the head means every skill's finishing/aggregation
        work lands on one process. Under concurrent skill invocations that
        makes the head a bottleneck for actual computation, not just
        dispatch - the head is supposed to retain control over task
        *routing* (see DESIGN_v3.md section 8.5), which is a different thing
        from being where computation happens. Worker-coordination keeps that
        distinction real: the head decides who finishes the job, a worker
        does it.

        Override to return ctx.agent_id for a skill where the aggregation is
        cheap enough (e.g. folding a handful of Federator scalars) that the
        extra two message hops (dispatch-to-coordinator, result-back-to-head)
        aren't worth it - an explicit opt-in for that case, not the default.

        Parameters
        ----------
        ctx : HarnessContext
        workers : list of str
            Agent ids currently reporting this skill's capability.

        Returns
        -------
        str
            The `agent_id` that will run `coordinate` for this invocation.
        """
        return random.choice(workers)

    def scarlet_names(self, mapper_name: str) -> list[str]:
        """
        Concrete scarlet_definition_* Redis keys this skill's contribute()/
        coordinate() will end up constructing via ctx.mapper()/ctx.federator(),
        given the per-request mapper_name run_skill() assigns. Empty list
        (the default) means this skill doesn't use a Mapper/Federator-backed
        scarlet at all (e.g. combine, which computes purely locally).

        run_skill() calls this before dispatch to pre-register each name
        with a real, request-specific description (LLM-composed when a
        ChatClient is available - see head.py's _compose_scarlet_description)
        so it's already visible on the Scarlets tracker the moment work
        starts, not only once some worker happens to construct one.
        register_scarlet_definition's own overwrite=False default (see
        scarlets' ScarletUtils.py) means a worker's later ctx.mapper()/
        ctx.federator() call - which always passes an empty description -
        is a no-op against a name already registered here, so head's richer
        description is never clobbered.

        A skill backed by Mapper directly returns [mapper_name] (see
        median.py). A skill backed by Federator must return the two derived
        names Federator's own __init__ actually constructs - scarletName +
        "_mapper_reducer"/"_mapper_global" (see sum.py) - duplicated here
        rather than imported, since scarlets' Federator doesn't expose that
        naming scheme as a constant; if Federator's internal suffixes ever
        change, this needs updating too.

        Parameters
        ----------
        mapper_name : str
            The per-request base name `run_skill` assigns.

        Returns
        -------
        list of str
            Scarlet names this invocation will construct. `[]` (the
            default) means this skill doesn't use a Mapper/Federator-
            backed scarlet at all.
        """
        return []

    @abstractmethod
    def contribute(self, ctx: HarnessContext, request: dict) -> None:
        """
        Run on every worker asked to participate in this invocation.

        Does local compute and publishes/signals via scarlets
        primitives. No return value - the real result surfaces through
        `Mapper`/`Messenger`, not a Python call stack, since `contribute`
        and `coordinate` run in different processes, often on different
        machines.

        Parameters
        ----------
        ctx : HarnessContext
        request : dict
            The dispatch request - includes ``request_id``, ``skill``,
            ``mapper_name``, ``coordinator``, ``workers``, ``params``.
        """
        ...

    @abstractmethod
    def coordinate(self, ctx: HarnessContext, request: dict, workers: list[str]) -> dict:
        """
        Run on exactly one agent - the coordinator, decided per-invocation by `coordinator_for`.

        Gathers contributions and returns the final result.

        Parameters
        ----------
        ctx : HarnessContext
        request : dict
            The dispatch request (same shape as `contribute`'s).
        workers : list of str
            Agent ids participating in this invocation.

        Returns
        -------
        dict
            JSON-serializable result. Becomes (or is folded into) the
            ``skill_result`` message sent back to the head. Should
            include ``"status": "ok"`` on success, or ``"status":
            "error"`` (optionally ``"retryable": True`` for transient
            failures) on failure.
        """
        ...

    def as_tool_schema(self) -> dict:
        """
        Build an OpenAI/vLLM-compatible tool definition for this skill.

        Returns
        -------
        dict
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
