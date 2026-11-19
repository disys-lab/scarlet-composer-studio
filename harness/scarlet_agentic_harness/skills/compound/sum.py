"""
`sum` as a compound skill: agree a representation, then aggregate.

The atomic half is `sum_core`, which is unchanged. What this adds is the
step that used to live in the head's prompt - a fleet holding different
columns has to agree which ones every worker can contribute before any
aggregation is meaningful, and forgetting to do that produced a confident
wrong answer rather than an error.

`returns` uses the mapping form deliberately. `sum_core` hands back the
per-column sums AND the element count behind them, and notebooks compose a
mean or a variance from both. A compound exposing only the sums would
silently give back less than the skill it replaced.
"""
from scarlet_agentic_harness.skills.base import CompoundSkill, Step
from scarlet_agentic_harness.skills import predicate


class SumSkill(CompoundSkill):
    """`agree_representation` -> `sum_core`, returning the sums and their n."""

    name = "sum"
    description = (
        "Sum measurements held across worker agents, per column. Agrees which "
        "columns every worker can contribute before aggregating, so it works on a "
        "fleet whose workers hold different data. Returns the per-column sums and "
        "the number of rows behind them. Pass `columns` to skip the agreement step "
        "and use exactly those columns; pass `workers` to aggregate over a subset."
    )
    parameters = {
        "type": "object",
        "properties": {
            "objective": {
                "type": "string",
                "description": (
                    "Plain-language statement of what to sum. Do not name a source, a "
                    "file or a column - each worker resolves that locally."
                ),
            },
            "transform": {
                "type": "string",
                "enum": ["identity", "square"],
                "description": "identity for a plain sum, square for a sum of squares.",
            },
            "columns": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Exact columns to read. Supplying this skips the agreement step "
                    "entirely - it is already decided."
                ),
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
        Step("sum_core", produces={"column_sums": "result", "n": "n"}),
    ]
    returns = {"result": "column_sums", "n": "n"}
