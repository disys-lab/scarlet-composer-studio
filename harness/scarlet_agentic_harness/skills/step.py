"""One step of a compound skill's plan."""
from dataclasses import dataclass, field


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
