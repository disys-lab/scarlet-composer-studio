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
        # --- the tail ----------------------------------------------
        # `sf` is the upper tail, always computed. The three branches
        # below are mutually exclusive on `mode`, so exactly one runs and
        # binds `p_value` (RULE 0). This block is identical in every
        # hypothesis test here - only `dist` and its shape parameters
        # differ.
        Step("distribution",
             params={"dist": "norm", "method": "sf", "x": "$z"},
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
    returns = {"result": "z", "p_value": "p_value", "p_upper": "p_upper",
               "mode": "mode", "columns": "columns", "n": "n"}
