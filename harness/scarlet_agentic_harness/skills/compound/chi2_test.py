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

A note on the name, because the history is confusing. An earlier skill
held this name and computed sum((x-mu)^2/mu) - a chi-squared statistic
only for Poisson counts, i.e. a dispersion test under a general name,
with no count data in the fleet to run it on. That one was removed and
this took the name, because "run a chi2 test" means the test for a
variance to nearly everyone who asks, and two skills both calling
themselves the chi-squared test is a choice the head cannot make
reliably.

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


class Chi2TestSkill(CompoundSkill):
    """Chi-squared test of the fleet's variance against a hypothesised value."""

    name = "chi2_test"
    description = (
        "PREFERRED for a chi-squared test of a VARIANCE - whether the "
        "fleet's variance of a column equals, exceeds, or falls below a "
        "hypothesised sigma0^2. Returns the chi2 statistic, its degrees of "
        "freedom and its p-value; pass mode=upper or mode=lower for a "
        "one-sided alternative. Call this rather than assembling it from "
        "variance, combine and distribution, which produced three "
        "different statistics for the same question across three "
        "attempts. This is the test meant by \"run a chi2 test on the "
        "variance\"; it is not a goodness-of-fit test."
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
        # --- the tail ----------------------------------------------
        # `sf` is the upper tail, always computed. The three branches
        # below are mutually exclusive on `mode`, so exactly one runs and
        # binds `p_value` (RULE 0). This block is identical in every
        # hypothesis test here - only `dist` and its shape parameters
        # differ.
        Step("distribution",
             params={"dist": "chi2", "method": "sf", "x": "$chi2", "params": {"df": "$df"}},
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
    returns = {"result": "chi2", "p_value": "p_value", "p_upper": "p_upper",
               "mode": "mode", "df": "df", "columns": "columns", "n": "n"}
