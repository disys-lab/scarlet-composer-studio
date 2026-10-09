"""
Chi-squared goodness-of-fit test for fleet measurements.

Computes the chi-squared statistic per column:
    chi2 = sum( (x - mu)^2 / mu )
where mu is the expected value supplied by the caller.

This is a compound skill: it aggregates sums of x and x^2, then combines
them to produce the chi-squared statistic.

Limitations
-----------
- Requires mu > 0 for all columns; division by zero is not handled.
- Assumes measurements are independent counts or squared deviations.
- Not suitable for sparse data where expected counts are < 5.
- The statistic assumes the expected values (mu) are known, not estimated
  from the same data.
"""
from scarlet_agentic_harness.skills.base import CompoundSkill, Step
from scarlet_agentic_harness.skills import predicate


class Chi2TestSkill(CompoundSkill):
    name = "chi2_test"
    description = (
        "PREFERRED for a chi-squared goodness-of-fit test - call this "
        "rather than assembling one from sum_core and combine. Compares "
        "the fleet's measurements against an expected value per column, "
        "computing sum((observed - expected)^2 / expected) across every "
        "worker. Returns the chi2 statistic, its degrees of freedom, and "
        "its one-sided (upper-tail) p-value per column.\n"
        "This is GOODNESS-OF-FIT only. It is NOT the chi-squared test for "
        "a variance (chi2 = (n-1)s^2/sigma0^2) - for that one call "
        "`variance_test`, which does provide it."
    )
    parameters = {
        "type": "object",
        "properties": {
            "mu": {"type": "number", "description": "Expected value for the chi-squared test."},
            "objective": {"type": "string", "description": "What to measure, in plain language."},
            "columns": {"type": "array", "items": {"type": "string"}},
            "workers": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Agent ids that should contribute. Omit for all of them.",
            },
            "conditions": predicate.CONDITIONS_SCHEMA,
        },
        "required": ["mu"],
    }
    plan = [
        Step("agree_representation", produces={"columns": "result"}),
        Step("sum_core", produces={"s1": "result", "n": "n"}),
        Step("sum_core",
             params={"transform": "square"},
             produces={"s2": "result"}),
        Step("combine",
             params={"expression": "(s2 - 2*mu*s1 + n*mu*mu) / mu",
                     "variables": {"s2": "$s2", "s1": "$s1", "n": "$n", "mu": "$mu"}},
             produces={"chi2": "result"}),
        Step("combine",
             params={"expression": "n-1", "variables": {"n": "$n"}},
             produces={"df": "result"}),
        # ONE-SIDED, upper tail - and deliberately not doubled. A
        # goodness-of-fit test only has one interesting direction: a large
        # statistic means the data fit the expected value badly. A small
        # one means they fit well, which is not evidence against anything.
        # The other tests here are two-sided because "is the mean 2.5?"
        # can fail in either direction; "do these fit?" cannot.
        Step("distribution",
             params={"dist": "chi2", "method": "sf", "x": "$chi2",
                     "params": {"df": "$df"}},
             produces={"p_value": "result"}),
    ]
    returns = {"result": "chi2", "p_value": "p_value", "df": "df",
               "columns": "columns", "n": "n"}
