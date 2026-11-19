"""A skill expressed as a plan over other skills."""
from scarlet_agentic_harness.skills.skill import Skill


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
