"""
Chi-squared test for a variance, against a hypothesised value.

Tests whether the fleet's variance of a column equals sigma0^2:

    chi2 = (n - 1) * s^2 / sigma0^2      with n - 1 degrees of freedom

where s^2 is the SAMPLE variance. The `variance` step returns the
population variance (ddof=0), and the two are related by
s^2 = var_pop * n/(n-1), so the (n-1) cancels and the statistic is just
``n * var_pop / sigma0^2``. That is why the plan below looks simpler than
the textbook formula - it is the same quantity.

This exists because the head could not compose it reliably. Asked the
question three separate times with `variance`, `combine` and
`distribution`, it produced chi2 = 34.4160, 35.4046 and a hand-rolled
normal approximation, where the correct value is 35.7659. Every attempt
reached the right *conclusion*, which is exactly why the wrong statistics
went unnoticed.

`chi2_test` is a different test - goodness-of-fit against an expected
value per column, sum((O-E)^2/E). It does not answer this question and
this does not answer that one.

Limitations
-----------
- Assumes the measurements are normally distributed. The chi-squared test
  for a variance is markedly more sensitive to departures from normality
  than a t-test is to the same departures.
- Assumes independent observations; clustered or autocorrelated readings
  make the degrees of freedom wrong.
- Two-sided. A one-sided alternative is `p_lower` (or 1 - `p_lower`)
  re-exported below, used directly rather than halved.
- sigma0_sq must be positive; a zero or negative hypothesised variance is
  not a hypothesis this test can evaluate.
"""
from scarlet_agentic_harness.skills.base import CompoundSkill, Step
from scarlet_agentic_harness.skills import predicate


class VarianceTestSkill(CompoundSkill):
    """Chi-squared test of the fleet's variance against a hypothesised value."""

    name = "variance_test"
    description = (
        "PREFERRED for a chi-squared test of a VARIANCE - whether the "
        "fleet's variance of a column equals, exceeds, or falls below a "
        "hypothesised sigma0^2. Returns the chi2 statistic, its degrees of "
        "freedom, and a two-sided p-value, plus `p_lower` for a one-sided "
        "alternative. Call this rather than assembling it from variance, "
        "combine and distribution, which has produced three different "
        "statistics for the same question. "
        "Note this is NOT chi2_test, which is goodness-of-fit against an "
        "expected value per column - a different test entirely."
    )
    parameters = {
        "type": "object",
        "properties": {
            "sigma0_sq": {
                "type": "number",
                "description": (
                    "Hypothesised population VARIANCE (sigma squared), not "
                    "the standard deviation."
                ),
            },
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
        "required": ["sigma0_sq"],
    }
    plan = [
        Step("agree_representation", produces={"columns": "result"}),
        Step("variance", produces={"var_pop": "result", "n": "n"}),
        # chi2 = (n-1)*s^2/sigma0^2, and s^2 = var_pop*n/(n-1), so the
        # (n-1) cancels: chi2 = n*var_pop/sigma0^2. Composing it the long
        # way round and forgetting the ddof conversion is what produced
        # 35.4046 instead of 35.7659.
        Step("combine",
             params={"expression": "n*var_pop/sigma0_sq",
                     "variables": {"n": "$n", "var_pop": "$var_pop",
                                   "sigma0_sq": "$sigma0_sq"}},
             produces={"chi2": "result"}),
        Step("combine",
             params={"expression": "n-1", "variables": {"n": "$n"}},
             produces={"df": "result"}),
        Step("distribution",
             params={"dist": "chi2", "method": "cdf", "x": "$chi2",
                     "params": {"df": "$df"}},
             produces={"p_lower": "result"}),
        # Two-sided: 2*min(cdf, 1-cdf), and combine has no min(). For a
        # continuous distribution that is 1 - |2*cdf - 1|, and |x| is
        # written (x**2)**0.5. A chi2 statistic cannot be negative, but
        # the TAIL still has two sides - a variance can be too small as
        # easily as too large, and this fixture's is.
        Step("combine",
             params={"expression": "1 - ((2*p_lower - 1)**2)**0.5",
                     "variables": {"p_lower": "$p_lower"}},
             produces={"p_value": "result"}),
    ]
    returns = {"result": "chi2", "p_value": "p_value", "p_lower": "p_lower",
               "df": "df", "columns": "columns", "n": "n"}
