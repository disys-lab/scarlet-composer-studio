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
    when : dict
        ``{namespace_var: value}`` - run this step only if every entry
        matches the namespace. A list or tuple matches if the namespace
        value is any member of it::

            Step("combine", when={"mode": "upper"}, ...)
            Step("combine", when={"mode": ["upper", "two-sided"]}, ...)

        A variable the namespace does not hold never matches, so a
        conditional step is skipped rather than guessed at. Use it to
        express a genuine branch - the alternative is a plan that computes
        every outcome and leaves the caller to pick, which reads worse and
        hides which path was taken.

        Several steps may share an output under mutually exclusive
        conditions; exactly one runs, and the plan stays linear.
    """

    skill: str
    params: dict = field(default_factory=dict)
    produces: dict = field(default_factory=dict)
    when: dict = field(default_factory=dict)
