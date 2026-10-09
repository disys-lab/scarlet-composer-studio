"""
One-sample z-test of the fleet's measurements against a hypothesised mean.

This skill computes the z-statistic per column:

    z = (xbar - mu0) / (sigma / sqrt(n))

where:
- xbar is the sample mean of the column
- mu0 is the hypothesised population mean (provided by caller)
- sigma is the known population standard deviation (provided by caller)
- n is the number of observations

The computation is performed per column of the fleet's measurements.

Limitations
-----------
- Assumes the population standard deviation (sigma) is known.
- For large samples (n > 30) per worker; for smaller samples the result
  may be misleading because the normal approximation may not hold.
- Not suitable for non-i.i.d. data or data with heavy tails.
- Requires at least one non-missing value per column per worker.
"""
from scarlet_agentic_harness.skills.base import CompoundSkill, Step
from scarlet_agentic_harness.skills import predicate


class ZTestSkill(CompoundSkill):
    name = "z_test"
    description = (
        "One-sample z-test of the fleet's measurements against a "
        "hypothesised mean. Returns the z statistic, its two-sided p-value, "
        "and the one-sided tail, per column. Use when sigma is known."
    )
    parameters = {
        "type": "object",
        "properties": {
            "mu0": {"type": "number", "description": "Hypothesised mean."},
            "sigma": {"type": "number",
                      "description": "Known population standard deviation."},
            "objective": {"type": "string",
                          "description": "What to measure, in plain language."},
            "columns": {"type": "array", "items": {"type": "string"}},
            "workers": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Agent ids that should contribute. Omit for all of them.",
            },
            "conditions": predicate.CONDITIONS_SCHEMA,
        },
        "required": ["mu0", "sigma"],
    }
    plan = [
        Step("agree_representation", produces={"columns": "result"}),
        Step("sum_core", produces={"s1": "result", "n": "n"}),
        Step("combine",
             params={"expression": "(s1/n - mu0)/(sigma/(n**0.5))",
                     "variables": {"s1": "$s1", "n": "$n",
                                   "mu0": "$mu0", "sigma": "$sigma"}},
             produces={"z": "result"}),
        # |z|, because `sf` is the UPPER tail only: sf(-0.75) is 0.77, and
        # doubling that gives 1.55, which is not a probability. combine has
        # no abs() any more than it has sqrt() - (z**2)**0.5 is how it is
        # written.
        Step("combine",
             params={"expression": "(z**2)**0.5", "variables": {"z": "$z"}},
             produces={"abs_z": "result"}),
        Step("distribution",
             params={"dist": "norm", "method": "sf", "x": "$abs_z"},
             produces={"p_one_sided": "result"}),
        Step("combine",
             params={"expression": "2*p_one_sided",
                     "variables": {"p_one_sided": "$p_one_sided"}},
             produces={"p_value": "result"}),
    ]
    returns = {"result": "z", "p_value": "p_value",
               "p_one_sided": "p_one_sided", "columns": "columns", "n": "n"}
