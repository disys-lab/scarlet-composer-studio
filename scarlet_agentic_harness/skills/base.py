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
    name: str = ""
    description: str = ""
    # JSON-schema "parameters" block for the LLM tool-call definition. Empty
    # means the skill takes no arguments beyond being invoked by name.
    parameters: dict = {"type": "object", "properties": {}, "required": []}
    # Seconds coordinate() should wait for peer contributions before giving
    # up. Per-skill because different skills have very different expected
    # completion times (a local sort vs. a long-running training round).
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
        """
        return random.choice(workers)

    @abstractmethod
    def contribute(self, ctx: HarnessContext, request: dict) -> None:
        ...

    @abstractmethod
    def coordinate(self, ctx: HarnessContext, request: dict, workers: list[str]) -> dict:
        ...

    def as_tool_schema(self) -> dict:
        """OpenAI/vLLM-compatible tool definition for this skill."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
