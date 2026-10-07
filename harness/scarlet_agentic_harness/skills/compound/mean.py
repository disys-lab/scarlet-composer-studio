"""
`mean` as a compound: agree, sum, divide.

The division happens on a worker via `combine`, not here - "head never
computes" applies to a plan runner too. `combine` carries vectors as of
this sprint, so one call handles every column at once rather than one call
per column.
"""
from scarlet_agentic_harness.skills.base import CompoundSkill, Step
from scarlet_agentic_harness.skills import predicate


class MeanSkill(CompoundSkill):
    """`agree_representation` -> `sum_core` -> `combine`, per column."""

    name = "mean"
    description = (
        "Per-column mean of measurements held across worker agents. Agrees which "
        "columns every worker can contribute, sums them, and divides by the row "
        "count. Pass `columns` to skip the agreement step; pass `workers` to "
        "average over a subset."
    )
    parameters = {
        "type": "object",
        "properties": {
            "objective": {
                "type": "string",
                "description": (
                    "Plain-language statement of what to average. Do not name a "
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
        Step("sum_core", produces={"s1": "result", "n": "n"}),
        Step("combine",
             params={"expression": "s1/n",
                     "variables": {"s1": "$s1", "n": "$n"}},
             produces={"mean": "result"}),
    ]
    # Mapping form, for the same reason sum uses it: a bare list of numbers
    # cannot be labelled by the caller. columns says which column each value
    # belongs to, and n is the row count behind them. Returning only the
    # values makes the head invent labels - observed: it reported
    # "Column 1 / Column 2 / Column 3" and guessed n was a worker count.
    returns = {"result": "mean", "columns": "columns", "n": "n"}
