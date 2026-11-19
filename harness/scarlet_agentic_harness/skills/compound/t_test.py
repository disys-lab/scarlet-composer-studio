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
            "mode": {
                "type": "string",
                "enum": ["two-sided", "upper", "lower"],
                "default": "two-sided",
                "description": (
                    "Which tail the alternative hypothesis lives in. "
                    "two-sided = the value differs from the hypothesised "
                    "one; upper = it is greater; lower = it is less."
                ),
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
        # --- the tail ----------------------------------------------
        # `sf` is the upper tail, always computed. The three branches
        # below are mutually exclusive on `mode`, so exactly one runs and
        # binds `p_value` (RULE 0). This block is identical in every
        # hypothesis test here - only `dist` and its shape parameters
        # differ.
        Step("distribution",
             params={"dist": "t", "method": "sf", "x": "$t", "params": {"df": "$df"}},
             produces={"p_upper": "result"}),
        Step("combine", when={"mode": "upper"},
             params={"expression": "p_upper",
                     "variables": {"p_upper": "$p_upper"}},
             produces={"p_value": "result"}),
        Step("combine", when={"mode": "lower"},
             params={"expression": "1 - p_upper",
                     "variables": {"p_upper": "$p_upper"}},
             produces={"p_value": "result"}),
        # 2*min(u, 1-u) == 1 - |2u - 1|, which holds for every
        # distribution here, symmetric or not - verified to 5.6e-17
        # against norm, t, chi2 and f. |x| is (x**2)**0.5; combine has no
        # abs(). This is why no separate |statistic| step is needed.
        Step("combine", when={"mode": "two-sided"},
             params={"expression": "1 - ((2*p_upper - 1)**2)**0.5",
                     "variables": {"p_upper": "$p_upper"}},
             produces={"p_value": "result"}),
    ]
    returns = {"result": "t", "p_value": "p_value", "p_upper": "p_upper",
               "mode": "mode", "df": "df", "columns": "columns", "n": "n"}
