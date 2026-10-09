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
- The test is two-sided by default; one-sided alternatives require
  adjusting the p-value manually.
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
        Step("distribution",
             params={"dist": "f", "method": "sf", "x": "$f",
                     "params": {"dfn": "$df_a", "dfd": "$df_b"}},
             produces={"p_upper": "result"}),
        # Two-sided, which is what "do these variances match?" asks and
        # what this skill's docstring has always claimed. `sf` alone is
        # the upper tail: for F < 1 it returns > 0.5, so the skill was
        # reporting 0.7896 where the two-sided answer is 0.4237.
        #
        # Two-sided p is 2*min(sf, cdf), and combine has no min(). For a
        # continuous distribution cdf = 1 - sf, and
        #     2*min(s, 1-s) == 1 - |2s - 1|
        # which is expressible: |x| is (x**2)**0.5.
        Step("combine",
             params={"expression": "1 - ((2*p_upper - 1)**2)**0.5",
                     "variables": {"p_upper": "$p_upper"}},
             produces={"p_value": "result"}),
    ]
    returns = {"result": "f", "p_value": "p_value", "p_upper": "p_upper",
               "df_a": "df_a", "df_b": "df_b", "columns": "columns",
               "n_a": "n_a", "n_b": "n_b"}
