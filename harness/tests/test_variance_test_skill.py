"""
Tests for the variance_test compound skill.

This skill exists because the head could not compose the test reliably:
asked the same question three times with `variance` + `combine` +
`distribution`, it produced chi2 = 34.4160, 35.4046, and a hand-rolled
normal approximation, against a correct value of 35.7659. Each attempt
reached the right conclusion, which is why the wrong statistics survived.

So the tests that matter here let `combine` and `distribution` actually
run and check the number, rather than asserting the shape of each call.
"""
import pytest

from scarlet_agentic_harness import dispatch
from scarlet_agentic_harness.skills.registry import discover_skills


# worker2's vibration_rms. The `variance` step returns the POPULATION
# variance (ddof=0), so that is what the fixture feeds - supplying a
# sample variance would pre-correct the input and hide the conversion
# the plan is responsible for.
#
# From scipy, not worked out on paper:
#   sample variance (ddof=1)        = 0.364958, n = 99
#   population = sample*(n-1)/n     = 0.36127155555555557
#   chi2 = (n-1)*sample/sigma0_sq   = 35.765884
#   stats.chi2.cdf(chi2, 98)        = 1.0201749649275895e-09
#   two-sided = 2*min(cdf, 1-cdf)   = 2.040349929855179e-09
VAR_POP, N = 0.36127155555555557, 99
SIGMA0_SQ = 1.0
SCIPY_CHI2 = 35.765884
SCIPY_P_LOWER = 1.0201749649275895e-09
SCIPY_P_TWO_SIDED = 2.040349929855179e-09


@pytest.fixture
def skills():
    return discover_skills()


def _drive_live(skills, monkeypatch, params, var_pop=VAR_POP, n=N):
    """Stub only the data-touching steps; combine and distribution run for real."""
    calls = []

    class _Ctx:
        agent_id = "test"

    def fake(sk, p, config, buses, on_result, **kw):
        calls.append((sk.name, p))
        if sk.name in ("combine", "distribution"):
            on_result(sk.coordinate(_Ctx(), {"params": p}, []))
        elif sk.name == "variance":
            on_result({"status": "ok", "result": var_pop, "n": n})
        else:
            on_result({"status": "ok", "result": ["vibration_rms"]})

    monkeypatch.setattr(dispatch, "run_skill", fake)
    box = {}
    dispatch.run_plan(skills["variance_test"], params, None, None,
                      lambda r: box.update(r), skills)
    return box, calls


# --- the arithmetic ------------------------------------------------------

def test_the_statistic_matches_the_textbook_formula(skills, monkeypatch):
    """
    chi2 = (n-1)*s^2/sigma0^2, computed as n*var_pop/sigma0^2.

    The two are algebraically identical because s^2 = var_pop*n/(n-1).
    Forgetting that conversion is what produced 35.4046.
    """
    res, _ = _drive_live(skills, monkeypatch, {"sigma0_sq": SIGMA0_SQ})
    assert res["status"] == "ok"
    assert res["result"] == pytest.approx(SCIPY_CHI2, abs=1e-6)


def test_the_p_values_match_scipy(skills, monkeypatch):
    """`p_upper` is always computed; the lower tail is its complement."""
    res, _ = _drive_live(skills, monkeypatch, {"sigma0_sq": SIGMA0_SQ})
    assert 1.0 - res["p_upper"] == pytest.approx(SCIPY_P_LOWER, rel=1e-6)
    assert res["p_value"] == pytest.approx(SCIPY_P_TWO_SIDED, rel=1e-9)


def test_the_degrees_of_freedom_are_n_minus_one(skills, monkeypatch):
    res, _ = _drive_live(skills, monkeypatch, {"sigma0_sq": SIGMA0_SQ})
    assert res["df"] == N - 1


def test_a_variance_equal_to_sigma0_sq_is_not_significant(skills, monkeypatch):
    """
    The null being true must not look like evidence against it.

    var_pop = sigma0_sq*(n-1)/n makes the sample variance exactly
    sigma0_sq, so chi2 lands on its own degrees of freedom.
    """
    var_pop = SIGMA0_SQ * (N - 1) / N
    res, _ = _drive_live(skills, monkeypatch, {"sigma0_sq": SIGMA0_SQ},
                         var_pop=var_pop)
    assert res["result"] == pytest.approx(N - 1, abs=1e-9)
    assert res["p_value"] > 0.3


def test_the_p_value_is_a_probability_on_both_sides(skills, monkeypatch):
    """
    A variance can be too small as readily as too large, and this
    fixture's is. `cdf` alone would report 1e-9 as the p-value for a
    two-sided question; a plan that doubled the wrong tail would report
    something above 1.
    """
    for var_pop in (0.05, 0.36127155555555557, 1.0, 4.0, 25.0):
        res, _ = _drive_live(skills, monkeypatch, {"sigma0_sq": SIGMA0_SQ},
                             var_pop=var_pop)
        assert 0.0 <= res["p_value"] <= 1.0, (
            f"var_pop={var_pop} gave p={res['p_value']}, not a probability")


def test_a_variance_far_below_sigma0_sq_is_significant(skills, monkeypatch):
    """Direction: worker2's variance really is well under 1.0."""
    res, _ = _drive_live(skills, monkeypatch, {"sigma0_sq": SIGMA0_SQ})
    assert res["result"] < N - 1          # below its own df, so the low tail
    assert res["p_value"] < 1e-6


# --- wiring --------------------------------------------------------------

def test_the_plan_runs_its_steps_in_order(skills, monkeypatch):
    _, calls = _drive_live(skills, monkeypatch, {"sigma0_sq": SIGMA0_SQ})
    assert [n for n, _ in calls] == [
        "agree_representation", "variance", "combine", "combine", "distribution", "combine"]


def test_it_asks_the_chi_squared_distribution_not_the_normal(skills, monkeypatch):
    """The failure this replaces ended in a normal approximation."""
    _, calls = _drive_live(skills, monkeypatch, {"sigma0_sq": SIGMA0_SQ})
    dist = next(p for n, p in calls if n == "distribution")
    assert dist["dist"] == "chi2"
    assert dist["params"]["df"] == N - 1


def test_supplying_columns_skips_the_agreement_step(skills, monkeypatch):
    """RULE 2: a step whose outputs are already bound does not run."""
    _, calls = _drive_live(skills, monkeypatch,
                           {"sigma0_sq": SIGMA0_SQ, "columns": ["vibration_rms"]})
    assert "agree_representation" not in [n for n, _ in calls]


def test_it_can_be_scoped_to_one_worker(skills, monkeypatch):
    """Without `workers` declared, a per-worker question gets the fleet."""
    assert "workers" in skills["variance_test"].parameters["properties"]
    _, calls = _drive_live(skills, monkeypatch,
                           {"sigma0_sq": SIGMA0_SQ, "workers": ["w2"]})
    var = next(p for n, p in calls if n == "variance")
    assert var["workers"] == ["w2"]


def test_a_failed_step_aborts_the_plan(skills, monkeypatch):
    def fake(sk, p, config, buses, on_result, **kw):
        if sk.name == "variance":
            on_result({"status": "error", "detail": "no data", "retryable": False})
        else:
            on_result({"status": "ok", "result": ["vibration_rms"]})

    monkeypatch.setattr(dispatch, "run_skill", fake)
    box = {}
    dispatch.run_plan(skills["variance_test"], {"sigma0_sq": SIGMA0_SQ},
                      None, None, lambda r: box.update(r), skills)
    assert box["status"] == "error"
    assert box["retryable"] is False


def test_returns_re_export_everything_a_caller_needs(skills, monkeypatch):
    res, _ = _drive_live(skills, monkeypatch, {"sigma0_sq": SIGMA0_SQ})
    for field in ("result", "p_value", "p_upper", "df", "mode", "columns", "n"):
        assert field in res, f"{field} is not re-exported"


# --- every tail, against scipy -------------------------------------------

TAILS = {
    "upper": 0.999999998979825,
    "lower": 1.0201749445215569e-09,
    "two-sided": 2.0403498890431138e-09,
}


@pytest.mark.parametrize("mode", ["upper", "lower", "two-sided"])
def test_each_mode_gives_the_right_p_value(mode, skills, monkeypatch):
    """
    One assertion per tail, against scipy.

    The three are easy to confuse and all look like probabilities: for
    this fixture upper and lower differ by a factor of thousands, and a
    two-sided value used for a one-sided question is exactly double.
    """
    res, _ = _drive_live(skills, monkeypatch, {"sigma0_sq": SIGMA0_SQ, "mode": mode})
    assert res["status"] == "ok"
    assert res["mode"] == mode
    assert res["p_value"] == pytest.approx(TAILS[mode], rel=1e-9)
    assert 0.0 <= res["p_value"] <= 1.0


def test_omitting_mode_defaults_to_two_sided(skills, monkeypatch):
    """The schema default must reach the plan, or no branch runs at all."""
    mode = "two-sided"
    res, _ = _drive_live(skills, monkeypatch, {"sigma0_sq": SIGMA0_SQ})
    assert res["mode"] == "two-sided"
    assert res["p_value"] == pytest.approx(TAILS["two-sided"], rel=1e-9)


def test_the_upper_and_lower_tails_are_complementary(skills, monkeypatch):
    mode = "upper"
    up, _ = _drive_live(skills, monkeypatch, {"sigma0_sq": SIGMA0_SQ, "mode": mode})
    mode = "lower"
    lo, _ = _drive_live(skills, monkeypatch, {"sigma0_sq": SIGMA0_SQ, "mode": mode})
    assert up["p_value"] + lo["p_value"] == pytest.approx(1.0, abs=1e-12)
