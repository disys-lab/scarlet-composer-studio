"""
DistributionSkill - turn a computed statistic into a probability.

The companion to `combine`. `combine` does arithmetic and cannot call a
function; this does distribution lookups and nothing else. Between them a
compound skill can compute a statistic across the fleet and then report
its p-value without either step needing raw data in one place.

Local, like `combine`: there is nothing per-worker about evaluating a CDF,
so `contribute` is a no-op and the coordinator answers directly.

Limitations
-----------
- Low-level only. No high-level tests (`ttest_1samp`, `chisquare`, ...),
  because those take raw samples and would mean collecting every worker's
  data in one process.
- Four distributions: norm, t, chi2, f. Adding one means adding it to
  `skills/distributions.py`'s table, not passing a new name through.
- Says nothing about whether the statistic it was given is correct, or
  whether the distribution suits it. Choosing the right reference
  distribution is the caller's problem.
"""
from scarlet_agentic_harness.context import HarnessContext
from scarlet_agentic_harness.skills.base import Skill
from scarlet_agentic_harness.skills import distributions


class DistributionSkill(Skill):
    """
    Evaluate a scipy.stats distribution at a value - p-values, critical values, densities.

    Returns
    -------
    ``{"status": "ok", "result": <float or list of float>, "detail": str}``
    on success, or ``{"status": "error", "detail": str,
    "retryable": False}`` - every failure here is a bad request, which a
    retry would reproduce exactly.
    """

    name = "distribution"
    description = (
        "Evaluate a statistical distribution at a value: p-values, critical "
        "values, densities. Use this AFTER computing a test statistic (with "
        "z_test, t_test, f_test, chi2_test, or combine) to turn that "
        "number into a "
        "probability - e.g. the two-sided p-value for a z of 2.4 is "
        "2 * distribution(dist=norm, method=sf, x=2.4). Accepts a list for "
        "x, so a per-column statistic gives a per-column p-value. "
        + distributions.describe()
    )
    parameters = {
        "type": "object",
        "properties": {
            "dist": {
                "type": "string",
                "enum": sorted(distributions.DISTRIBUTIONS),
                "description": "Reference distribution.",
            },
            "method": {
                "type": "string",
                "enum": sorted(distributions.METHODS),
                "description": (
                    "sf = upper-tail P(X > x), the one-sided p-value; "
                    "cdf = P(X <= x); pdf = density; "
                    "ppf = the x for a given lower-tail probability, i.e. a "
                    "critical value."
                ),
            },
            "x": {
                "description": (
                    "Where to evaluate - a number, or a list for a per-column "
                    "statistic. For ppf this is a probability, not a statistic."
                ),
            },
            "params": {
                "type": "object",
                "description": (
                    "Shape parameters: df for t and chi2; dfn and dfd for f; "
                    "none for norm. loc and scale optional throughout."
                ),
            },
        },
        "required": ["dist", "method", "x"],
    }

    def contribute(self, ctx: HarnessContext, request: dict) -> None:
        """No-op - evaluating a distribution needs no per-worker data."""
        pass

    def coordinate(self, ctx: HarnessContext, request: dict, workers: list[str]) -> dict:
        """
        Evaluate the requested distribution method.

        Parameters
        ----------
        ctx : HarnessContext
        request : dict
            ``params`` carries dist, method, x and optionally params.
        workers : list of str
            Unused - nothing is gathered.

        Returns
        -------
        dict
        """
        p = request.get("params", {})
        dist, method, x = p.get("dist"), p.get("method"), p.get("x")

        if dist is None or method is None or x is None:
            return {"status": "error", "retryable": False,
                    "detail": "distribution requires dist, method and x"}
        try:
            result = distributions.evaluate(dist, method, x, p.get("params"))
        except ValueError as exc:
            return {"status": "error", "retryable": False, "detail": str(exc)}

        return {
            "status": "ok",
            "result": result,
            "detail": (f"{dist}.{method}({x}) = {result} "
                       f"(evaluated on {ctx.agent_id})"),
        }
