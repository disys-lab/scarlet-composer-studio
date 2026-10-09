"""
Tests for the chi2_test compound skill (goodness-of-fit).

Like z_test, this had no test file until the p-value step was added.

The thing to keep straight here: this test is ONE-SIDED, and that is not
an oversight. Goodness-of-fit only has one interesting direction - a large
statistic means the data fit the expected value badly. A small one means
they fit well, which is not evidence against anything. Every other
hypothesis test in this package is two-sided, so the asymmetry is asserted
explicitly below rather than left to be noticed.
"""
import pytest

from scarlet_agentic_harness import dispatch
from scarlet_agentic_harness.skills.registry import discover_skills


# From scipy, not worked out on paper:
#   chi2 = (s2 - 2*mu*s1 + n*mu*mu)/mu = 24.0
#   stats.chi2.sf(24.0, 79)            = 0.9999999997131148
S1, S2, N, MU = 1000.0, 12800.0, 80, 12.5
SCIPY_CHI2 = 24.0
SCIPY_P_UPPER = 0.9999999997131148


@pytest.fixture
def skills():
    return discover_skills()


def _drive_live(skills, monkeypatch, params, s1=S1, s2=S2, n=N):
    """Stub only the data-touching steps; combine and distribution run for real."""
    calls = []
    sums = [{"status": "ok", "result": s1, "n": n},
            {"status": "ok", "result": s2, "n": n}]

    class _Ctx:
        agent_id = "test"

    def fake(sk, p, config, buses, on_result, **kw):
        calls.append((sk.name, p))
        if sk.name in ("combine", "distribution"):
            on_result(sk.coordinate(_Ctx(), {"params": p}, []))
        elif sk.name == "sum_core":
            on_result(sums.pop(0))
        else:
            on_result({"status": "ok", "result": ["vibration_rms"]})

    monkeypatch.setattr(dispatch, "run_skill", fake)
    box = {}
    dispatch.run_plan(skills["chi2_test"], params, None, None,
                      lambda r: box.update(r), skills)
    return box, calls


# --- the arithmetic ------------------------------------------------------

def test_the_statistic_matches_the_formula(skills, monkeypatch):
    """sum((O-E)^2/E), expanded so the fleet only has to ship two sums."""
    res, _ = _drive_live(skills, monkeypatch, {"mu": MU})
    assert res["status"] == "ok"
    assert res["result"] == pytest.approx(SCIPY_CHI2, abs=1e-9)


def test_the_p_value_matches_scipy(skills, monkeypatch):
    res, _ = _drive_live(skills, monkeypatch, {"mu": MU})
    assert res["p_value"] == pytest.approx(SCIPY_P_UPPER, rel=1e-12)


def test_the_degrees_of_freedom_are_n_minus_one(skills, monkeypatch):
    res, _ = _drive_live(skills, monkeypatch, {"mu": MU})
    assert res["df"] == N - 1


def test_the_p_value_is_the_upper_tail_and_is_not_doubled(skills, monkeypatch):
    """
    The deliberate asymmetry. A good fit gives a small statistic and a
    p-value near 1 - not near 0, and not doubled past 1. Doubling this
    one would produce 1.9999999994, which is not a probability.
    """
    res, _ = _drive_live(skills, monkeypatch, {"mu": MU})
    assert res["result"] < res["df"]          # fits better than chance
    assert res["p_value"] > 0.99
    assert res["p_value"] <= 1.0


def test_a_bad_fit_gives_a_small_p_value(skills, monkeypatch):
    """The direction that matters: a large statistic is evidence of misfit."""
    res, _ = _drive_live(skills, monkeypatch, {"mu": 1.0})
    assert res["result"] > res["df"]
    assert res["p_value"] < 0.01


def test_the_p_value_is_a_probability_across_a_range_of_expectations(skills, monkeypatch):
    for mu in (0.5, 1.0, 5.0, 12.5, 50.0):
        res, _ = _drive_live(skills, monkeypatch, {"mu": mu})
        assert 0.0 <= res["p_value"] <= 1.0, (
            f"mu={mu} gave p={res['p_value']}, which is not a probability")


# --- wiring --------------------------------------------------------------

def test_the_plan_runs_its_steps_in_order(skills, monkeypatch):
    _, calls = _drive_live(skills, monkeypatch, {"mu": MU})
    assert [n for n, _ in calls] == [
        "agree_representation", "sum_core", "sum_core", "combine",
        "combine", "distribution"]


def test_the_two_sum_core_steps_use_different_transforms(skills, monkeypatch):
    _, calls = _drive_live(skills, monkeypatch, {"mu": MU})
    sums = [p for n, p in calls if n == "sum_core"]
    assert len(sums) == 2
    assert sums[0].get("transform") in (None, "identity")
    assert sums[1].get("transform") == "square"


def test_it_uses_the_chi_squared_distribution(skills, monkeypatch):
    _, calls = _drive_live(skills, monkeypatch, {"mu": MU})
    dist = next(p for n, p in calls if n == "distribution")
    assert dist["dist"] == "chi2"
    assert dist["method"] == "sf"
    assert dist["params"]["df"] == N - 1


def test_returns_re_export_the_statistic_and_the_p_value(skills, monkeypatch):
    res, _ = _drive_live(skills, monkeypatch, {"mu": MU})
    for field in ("result", "p_value", "df", "columns", "n"):
        assert field in res, f"{field} is not re-exported"


def test_supplying_columns_skips_the_agreement_step(skills, monkeypatch):
    _, calls = _drive_live(skills, monkeypatch,
                           {"mu": MU, "columns": ["vibration_rms"]})
    assert "agree_representation" not in [n for n, _ in calls]


def test_it_can_be_scoped_to_one_worker(skills, monkeypatch):
    _, calls = _drive_live(skills, monkeypatch, {"mu": MU, "workers": ["w2"]})
    agg = next(p for n, p in calls if n == "sum_core")
    assert agg["workers"] == ["w2"]


def test_a_failed_step_aborts_the_plan(skills, monkeypatch):
    def fake(sk, p, config, buses, on_result, **kw):
        if sk.name == "sum_core":
            on_result({"status": "error", "detail": "no data", "retryable": False})
        else:
            on_result({"status": "ok", "result": ["vibration_rms"]})

    monkeypatch.setattr(dispatch, "run_skill", fake)
    box = {}
    dispatch.run_plan(skills["chi2_test"], {"mu": MU}, None, None,
                      lambda r: box.update(r), skills)
    assert box["status"] == "error"
    assert box["retryable"] is False
