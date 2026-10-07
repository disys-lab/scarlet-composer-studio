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
from dataclasses import dataclass, field
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
    stagger_extension: float = 10.0
    stagger_ceiling: float = 45.0

    def staggered_deadline(self, expected: int):
        """
        A deadline that extends while the fleet is still answering.

        A flat `coordinate_timeout` has to be either generous enough for
        the slowest plausible worker or short enough to notice a hang, and
        it cannot be both. Row filtering widened that gap: a filtered query
        adds a profile lookup and a clause build to every worker's path,
        and a worker scanning a large table for a narrow window can take
        noticeably longer than one reading everything.

        So the wait is staggered rather than flat. It starts at
        `coordinate_timeout`, and every time another worker reports in, the
        deadline moves out by `stagger_extension` - but never past
        `stagger_ceiling` seconds from the start. A fleet that is still
        making progress is given more time; one that has gone quiet is not,
        and a genuinely wedged worker still fails at the ceiling instead of
        hanging forever.

        Parameters
        ----------
        expected : int
            How many contributions completion requires. Only used to stop
            extending once everyone has answered.

        Returns
        -------
        callable
            ``progress(count) -> bool``. Call it with the number of
            contributions received so far; it returns True while there is
            still time left, having first extended the deadline if `count`
            grew since the last call.
        """
        import time as _time

        started = _time.time()
        state = {"deadline": started + self.coordinate_timeout, "seen": 0}
        ceiling = started + self.stagger_ceiling

        def progress(count: int) -> bool:
            if count > state["seen"]:
                state["seen"] = count
                if count < expected:
                    # Someone answered and we are not done - buy more time.
                    #
                    # max() against the current deadline is load-bearing: a
                    # worker replying early must never move the deadline
                    # *earlier* than it already was. Written as a bare
                    # min(ceiling, now + extension) it did exactly that - a
                    # reply at t=1s pulled a 15s deadline back to 11s - which
                    # produced spurious timeouts, retries, and a notebook that
                    # ran until the cell limit killed it. The deadline only
                    # ever moves outward, and never past the ceiling.
                    state["deadline"] = min(
                        ceiling,
                        max(state["deadline"], _time.time() + self.stagger_extension))
            return _time.time() < state["deadline"]

        return progress

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

@dataclass
class Step:
    """
    One step in a `CompoundSkill`'s plan.

    Parameters
    ----------
    skill : str
        Name of the skill to run, as registered.
    params : dict
        Overlaid on the ambient namespace for this step only. Any string of
        the form ``"$name"`` is replaced with ``ns["name"]`` before dispatch,
        recursively, including inside nested dicts - which is what lets a
        step pass a literal and a computed value in the same call.
    produces : dict
        ``{namespace_var: result_field}``. After the step succeeds, each
        named field of its result is bound to that namespace variable. A
        step with an empty `produces` is a check rather than a producer, and
        is never skipped.
    """

    skill: str
    params: dict = field(default_factory=dict)
    produces: dict = field(default_factory=dict)


class CompoundSkill(Skill):
    """
    A skill whose body is a plan over other skills, not a contribute/coordinate pair.

    A compound is never dispatched to workers - no worker advertises it as a
    capability. It is executed by the plan runner, which drives `run_skill`
    once per step over a shared namespace seeded from the caller's params.

    Subclasses declare `plan` and `returns` instead of implementing
    `contribute`/`coordinate`; both inherited methods raise, because reaching
    them means a compound was dispatched, which is a routing bug rather than
    a skill error.

    Attributes
    ----------
    plan : list of Step
        Executed in order.
    returns : str or dict
        A namespace variable name, or ``{output_field: namespace_var}`` when
        more than one value must come back. The mapping form matters: a
        compound wrapping a skill whose callers read several fields must
        expose all of them, or it silently hands back less than the skill it
        replaced.
    """

    plan: list = []
    returns = "result"

    def contribute(self, ctx, request):
        """Never called - a compound is executed by the plan runner, not dispatched."""
        raise RuntimeError(
            f"{self.name!r} is a compound skill and was dispatched to a worker. "
            f"run_skill must branch to the plan runner before resolving workers."
        )

    def coordinate(self, ctx, request, workers):
        """Never called - see `contribute`."""
        raise RuntimeError(
            f"{self.name!r} is a compound skill and was dispatched to a worker. "
            f"run_skill must branch to the plan runner before resolving workers."
        )
