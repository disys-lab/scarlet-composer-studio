"""
One-sample z-test for a proportion.

This skill tests the fleet's observed rate of a binary (0/1) column against
a hypothesised proportion p0. It computes the z-statistic per column:

    z = (p̂ - p0) / sqrt(p0 * (1 - p0) / n)

where:
- p̂ is the sample proportion (sum of 1s / n)
- p0 is the hypothesised population proportion (provided by caller)
- n is the number of observations

The two-sided p-value is reported using the standard normal distribution.

Limitations
-----------
- Assumes binary (0/1) data. Non-binary values are treated as-is, so
  proportions outside [0,1] will produce misleading results.
- Requires n * p0 > 5 and n * (1 - p0) > 5 for the normal approximation
  to be reasonable. Below that the result may be inaccurate.
- Not suitable for dependent observations or clustering.
- Requires at least one non-missing value per column per worker.
"""
from scarlet_agentic_harness.skills.base import CompoundSkill, Step
from scarlet_agentic_harness.skills import predicate


class ProportionTestSkill(CompoundSkill):
    name = "proportion_test"
    description = (
        "One-sample z-test of the fleet's binary proportion against a "
        "hypothesised value. Returns z and its two-sided p-value per column."
    )
    parameters = {
        "type": "object",
        "properties": {
            "p0": {"type": "number", "description": "Hypothesised proportion."},
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
        "required": ["p0"],
    }
    plan = [
        Step("agree_representation", produces={"columns": "result"}),
        Step("sum_core", produces={"s1": "result", "n": "n"}),
        Step("combine",
             params={"expression": "(s1/n - p0)/(p0*(1-p0)/n)**0.5",
                     "variables": {"s1": "$s1", "n": "$n", "p0": "$p0"}},
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
