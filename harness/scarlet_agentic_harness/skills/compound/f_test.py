"""
F-test for comparing variances between two groups of workers.

This skill performs a two-sample F-test to compare the variance of a
measurement between two groups of workers. The F-statistic is computed as
the ratio of the two sample variances:

    F = var(group_a) / var(group_b)

The p-value is obtained from the F-distribution with (n_a-1, n_b-1) degrees
of freedom, where n_a and n_b are the sample sizes.

This is a compound skill: it runs variance twice (once per group), then
uses combine to compute the ratio and distribution to get the p-value.

Limitations
-----------
- Assumes measurements are independent and identically distributed within
  each group.
- The F-test is sensitive to departures from normality; heavy tails or
  skewness can make the result misleading.
- Requires at least 2 non-missing values per column per worker in each
  group; otherwise the variance is undefined.
- Two-sided by default. Pass mode="upper" or mode="lower" for a
  one-sided alternative; the p-value is computed for the mode asked for,
  not adjusted afterwards.
"""
from scarlet_agentic_harness.skills.base import CompoundSkill, Step
from scarlet_agentic_harness.skills import predicate


class FTestSkill(CompoundSkill):
    name = "f_test"
    description = (
        "Two-sample F-test comparing the variance of measurements between two "
        "groups of workers. Returns the F statistic and its p-value per column. "
        "Pass groups as lists of worker IDs or use conditions to define groups."
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
            "group_a": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Worker IDs in the first group.",
            },
            "group_b": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Worker IDs in the second group.",
            },
            "columns": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Exact columns to read; supplying this skips agreement.",
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
        "required": ["group_a", "group_b"],
    }

    plan = [
        Step("agree_representation", produces={"columns": "result"}),
        Step("variance", params={"workers": "$group_a"},
             produces={"var_a": "result", "n_a": "n"}),
        Step("variance", params={"workers": "$group_b"},
             produces={"var_b": "result", "n_b": "n"}),
        # `variance` returns the POPULATION variance - its expression is
        # "s2/n - mean**2", i.e. ddof=0. An F-test compares SAMPLE
        # variances, so each needs Bessel's correction, n/(n-1), first.
        # Measured: without it F came out 0.839756 where the ratio of the
        # sample variances is 0.841930, and the two-sided p moved from
        # 0.430523 to 0.423590. Small, and wrong.
        Step("combine",
             params={"expression": ("(var_a*n_a/(n_a-1))"
                                    "/(var_b*n_b/(n_b-1))"),
                     "variables": {"var_a": "$var_a", "var_b": "$var_b",
                                   "n_a": "$n_a", "n_b": "$n_b"}},
             produces={"f": "result"}),
        # An F-test has (n-1, n-1) degrees of freedom, not (n, n). Passing
        # the raw counts was measured live against scipy: it gave
        # sf = 0.789550 where the correct value is 0.788135.
        Step("combine", params={"expression": "n_a-1", "variables": {"n_a": "$n_a"}},
             produces={"df_a": "result"}),
        Step("combine", params={"expression": "n_b-1", "variables": {"n_b": "$n_b"}},
             produces={"df_b": "result"}),
        # --- the tail ----------------------------------------------
        # `sf` is the upper tail, always computed. The three branches
        # below are mutually exclusive on `mode`, so exactly one runs and
        # binds `p_value` (RULE 0). This block is identical in every
        # hypothesis test here - only `dist` and its shape parameters
        # differ.
        Step("distribution",
             params={"dist": "f", "method": "sf", "x": "$f", "params": {"dfn": "$df_a", "dfd": "$df_b"}},
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
    returns = {"result": "f", "p_value": "p_value", "p_upper": "p_upper",
               "mode": "mode", "df_a": "df_a", "df_b": "df_b",
               "columns": "columns", "n_a": "n_a", "n_b": "n_b"}
