"""
One-sample t-test of the fleet's measurements against a hypothesised mean.

This skill computes the t-statistic per column:

    t = (xbar - mu0) / (s / sqrt(n))

where:
- xbar is the sample mean of the column
- mu0 is the hypothesised population mean (provided by caller)
- s is the sample standard deviation estimated from the data
- n is the number of observations

The computation is performed per column of the fleet's measurements, using
the sample variance computed across the fleet.

Limitations
-----------
- Assumes measurements are independent and identically distributed.
- For large samples (n > 30) per worker; for smaller samples the result
  may be misleading because the normal approximation may not hold.
- Not suitable for non-i.i.d. data or data with heavy tails.
- Requires at least one non-missing value per column per worker.
"""
from scarlet_agentic_harness.skills.base import CompoundSkill, Step
from scarlet_agentic_harness.skills import predicate


class TTestSkill(CompoundSkill):
    name = "t_test"
    description = (
        "One-sample t-test of the fleet's measurements against a "
        "hypothesised mean. Returns t per column. Use when sigma is unknown "
        "and must be estimated from the data."
    )
    parameters = {
        "type": "object",
        "properties": {
            "mu0": {"type": "number", "description": "Hypothesised mean."},
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
        "required": ["mu0"],
    }
    plan = [
        Step("agree_representation", produces={"columns": "result"}),
        Step("sum_core", produces={"s1": "result", "n": "n"}),
        Step("sum_core", params={"transform": "square"},
             produces={"s2": "result"}),
        # xbar = s1/n; sample variance = (s2/n - xbar**2)*n/(n-1), so the
        # standard error squared is (s2/n - xbar**2)/(n-1). No sqrt exists
        # in combine - **0.5 is how a square root is written.
        Step("combine",
             params={"expression": "(s1/n - mu0)/((s2/n - (s1/n)**2)/(n-1))**0.5",
                     "variables": {"s1": "$s1", "s2": "$s2", "n": "$n",
                                   "mu0": "$mu0"}},
             produces={"t": "result"}),
        Step("combine",
             params={"expression": "n-1", "variables": {"n": "$n"}},
             produces={"df": "result"}),
        # |t|, because `sf` is the UPPER tail only: sf(-0.31) is 0.62, and
        # doubling that gives 1.75, which is not a probability. There is no
        # abs() in combine either - (t**2)**0.5 is how it is written.
        Step("combine",
             params={"expression": "(t**2)**0.5", "variables": {"t": "$t"}},
             produces={"abs_t": "result"}),
        Step("distribution",
             params={"dist": "t", "method": "sf", "x": "$abs_t",
                     "params": {"df": "$df"}},
             produces={"p_one_sided": "result"}),
        Step("combine",
             params={"expression": "2*p_one_sided",
                     "variables": {"p_one_sided": "$p_one_sided"}},
             produces={"p_value": "result"}),
    ]
    returns = {"result": "t", "p_value": "p_value", "df": "df",
               "columns": "columns", "n": "n"}
