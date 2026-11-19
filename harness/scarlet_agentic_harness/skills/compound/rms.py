"""
Root-mean-square (RMS) skill.

Computes the root-mean-square of the fleet's measurements, per column:
  rms = sqrt( sum(x^2) / n )

Returns
-------
{"status": "ok", "result": <list of float, per column>,
 "columns": <list of str>, "n": <int>}

Parameters
----------
objective : str, optional
    What to measure, in plain language. Defaults to "all available numeric measurements".
columns : list of str, optional
    Column names to include. If omitted, all numeric columns are used.
conditions : list of dict, optional
    Row filter as a list of {column, op, value} dicts.

Limitations
-----------
- Assumes values are numeric and finite. Non-numeric or infinite values
  will cause the skill to fail.
- Not suitable for streaming data: reads a snapshot, so a window
  overlapping a write is not atomic.
- The result is returned even if n is small; check `n` before trusting
  the result for noisy data.
"""
from scarlet_agentic_harness.skills.base import CompoundSkill, Step
from scarlet_agentic_harness.skills import predicate


class RmsSkill(CompoundSkill):
    name = "rms"
    description = (
        "Compute the root-mean-square of the fleet's measurements, per column. "
        "rms = sqrt(sum(x^2) / n). Use to assess the magnitude of values, "
        "especially when negative values cancel out in a simple mean."
    )
    parameters = {
        "type": "object",
        "properties": {
            "objective": {
                "type": "string",
                "description": "What to measure, in plain language.",
            },
            "columns": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Column names to include. If omitted, all numeric columns are used.",
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
        Step("sum_core", params={"transform": "square"},
             produces={"s2": "result", "n": "n"}),
        Step("combine",
             params={"expression": "(s2/n)**0.5",
                     "variables": {"s2": "$s2", "n": "$n"}},
             produces={"rms": "result"}),
    ]
    returns = {"result": "rms", "columns": "columns", "n": "n"}
