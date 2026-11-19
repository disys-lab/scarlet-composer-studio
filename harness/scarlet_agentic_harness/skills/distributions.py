"""
Whitelisted access to scipy.stats distributions.

`combine`/`safe_eval` is arithmetic only - no function calls at all - so a
p-value, a critical value or any other distribution quantity cannot be
expressed there. This is the other half: the fleet computes the statistic,
and this turns that statistic into a probability.

Deliberately low-level. scipy.stats' own high-level wrappers
(`ttest_1samp`, `chisquare`, ...) are not exposed, because they take raw
samples - which would mean shipping every worker's data to one place, the
thing this whole harness exists to avoid. A skill computes its statistic
across the fleet, then asks for the tail probability of that one number.

Both the distribution and the method are looked up in a table, never by
`getattr` on caller-supplied strings. The parameter set is checked per
distribution, so a missing `df` is a clear error rather than a TypeError
from inside scipy.
"""
from typing import Any, Dict

from scipy import stats

# Distribution name -> (scipy object, required shape parameters).
# Keep this short: each entry is a promise that the parameter names below
# match what scipy expects positionally for that distribution.
DISTRIBUTIONS: Dict[str, tuple] = {
    "norm": (stats.norm, ()),
    "t": (stats.t, ("df",)),
    "chi2": (stats.chi2, ("df",)),
    "f": (stats.f, ("dfn", "dfd")),
}

# Method name -> what it answers. `sf` is the one a hypothesis test wants:
# the upper-tail probability, computed more accurately than 1 - cdf.
METHODS: Dict[str, str] = {
    "sf": "upper-tail probability P(X > x) - the one-sided p-value",
    "cdf": "P(X <= x)",
    "pdf": "density at x",
    "ppf": "the x for a given lower-tail probability - a critical value",
}


def evaluate(dist: str, method: str, x, params: Dict[str, Any] | None = None):
    """
    Evaluate one distribution method at `x`.

    Parameters
    ----------
    dist : str
        A key of `DISTRIBUTIONS`.
    method : str
        A key of `METHODS`.
    x : float or list of float
        Where to evaluate. A list is evaluated elementwise, which is what
        a per-column statistic needs.
    params : dict, optional
        Shape parameters for `dist`, plus optional ``loc``/``scale``.

    Returns
    -------
    float or list of float
        Matching the shape of `x`.

    Raises
    ------
    ValueError
        Unknown distribution or method, a missing required parameter, or a
        non-numeric `x`. Never a bare scipy TypeError.
    """
    if dist not in DISTRIBUTIONS:
        raise ValueError(
            f"unknown distribution {dist!r} - available: {', '.join(sorted(DISTRIBUTIONS))}")
    if method not in METHODS:
        raise ValueError(
            f"unknown method {method!r} - available: {', '.join(sorted(METHODS))}")

    obj, required = DISTRIBUTIONS[dist]
    params = dict(params or {})

    missing = [p for p in required if p not in params]
    if missing:
        raise ValueError(
            f"distribution {dist!r} requires {', '.join(missing)}")

    shape_args = [float(params[p]) for p in required]
    kwargs = {k: float(params[k]) for k in ("loc", "scale") if k in params}

    values = x if isinstance(x, (list, tuple)) else [x]
    numbers = [_as_number(v) for v in values]

    fn = getattr(obj, method)          # method is whitelisted above
    out = [float(fn(v, *shape_args, **kwargs)) for v in numbers]
    return out if isinstance(x, (list, tuple)) else out[0]


def _as_number(v) -> float:
    """
    Coerce one value of `x` to a float, or refuse it by name.

    A numeric string is accepted. The LLM emits tool arguments as JSON and
    routinely types a number as a string - observed live, a chi-squared
    question sent ``x: "35.40459295505072"`` and this function's stricter
    ancestor refused it three times running. The head then gave up on the
    skill and reported a p-value it had estimated by a normal
    approximation in its own reasoning instead, which is exactly the
    behaviour the whole `distribution` skill exists to prevent.

    `combine` has always coerced its variables the same way (see
    safe_eval's `_coerce`), so this also makes the two agree.

    Parameters
    ----------
    v : object
        A number, or a string holding one.

    Returns
    -------
    float

    Raises
    ------
    ValueError
        If `v` is a bool, or a value no float() can read.
    """
    # bool is an int subclass, and True would silently evaluate at 1.0.
    if isinstance(v, bool):
        raise ValueError(f"x must be numeric, got {v!r}")
    try:
        return float(v)
    except (TypeError, ValueError):
        raise ValueError(f"x must be numeric, got {v!r}") from None


def describe() -> str:
    """One-line summaries of what is available, for a tool description."""
    dists = ", ".join(
        f"{n}({', '.join(req)})" if req else n
        for n, (_, req) in sorted(DISTRIBUTIONS.items()))
    methods = ", ".join(f"{m}" for m in sorted(METHODS))
    return f"distributions: {dists}; methods: {methods}"
