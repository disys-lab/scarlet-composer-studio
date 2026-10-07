"""
`variance` as a compound, and the first compound that calls a compound.

variance = s2/n - mean**2, where mean is itself a compound. Two things
about that are worth stating, because both are easy to get wrong and
neither fails loudly:

`n` comes from this plan's own `sum_core` step, NOT from `mean`. A
sub-compound returns only its `returns` value; its internal namespace does
not leak upward, so the n that `mean` computed is not visible here.

The `mean` step does NOT re-run consensus. `columns` is already bound in
this namespace by step 1, the namespace is ambient so it reaches `mean`'s
params, and `mean`'s own agree_representation step is skipped by the plan
runner's skip rule. One consensus round for the whole nested plan - if it
runs twice, the ambient namespace is not reaching the sub-compound and
that is a bug, not an inefficiency.
"""
from scarlet_agentic_harness.skills.base import CompoundSkill, Step
from scarlet_agentic_harness.skills import predicate


class VarianceSkill(CompoundSkill):
    """`agree_representation` -> `mean` -> `sum_core(square)` -> `combine`."""

    name = "variance"
    description = (
        "Per-column population variance of measurements held across worker agents. "
        "Agrees which columns every worker can contribute, then composes the "
        "variance from a mean and a sum of squares. Pass `columns` to skip the "
        "agreement step; pass `workers` to compute over a subset."
    )
    parameters = {
        "type": "object",
        "properties": {
            "objective": {
                "type": "string",
                "description": (
                    "Plain-language statement of what to measure. Do not name a "
                    "source, a file or a column."
                ),
            },
            "columns": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Exact columns to read; supplying this skips agreement.",
            },
            "workers": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Agent ids that should contribute. Omit for all of them.",
            },
            "conditions": predicate.CONDITIONS_SCHEMA,
        },
        "required": [],
    }

    plan = [
        Step("agree_representation", produces={"columns": "result"}),
        Step("mean", produces={"mean": "result"}),
        Step("sum_core", params={"transform": "square"},
             produces={"s2": "result", "n": "n"}),
        Step("combine",
             params={"expression": "s2/n - mean**2",
                     "variables": {"s2": "$s2", "n": "$n", "mean": "$mean"}},
             produces={"variance": "result"}),
    ]
    # Mapping form, for the same reason sum uses it: a bare list of numbers
    # cannot be labelled by the caller. columns says which column each value
    # belongs to, and n is the row count behind them. Returning only the
    # values makes the head invent labels - observed: it reported
    # "Column 1 / Column 2 / Column 3" and guessed n was a worker count.
    returns = {"result": "variance", "columns": "columns", "n": "n"}
