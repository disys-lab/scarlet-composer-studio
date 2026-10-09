"""
Tests for the proportion_test compound skill.

The arithmetic tests at the bottom are the ones that matter. Every other
test stubs `combine`, so they pass against a plan whose expression was
wrong (e.g. using sqrt instead of **0.5). The tests that let `combine`
and `distribution` execute are the only ones that can catch those defects.
"""
import pytest

from scarlet_agentic_harness import dispatch
from scarlet_agentic_harness.skills.registry import discover_skills


# A sample whose answer is known: 30 successes out of 100 trials.
# p̂ = 0.30, p0 = 0.25
# z = (0.30 - 0.25) / sqrt(0.25 * 0.75 / 100) = 0.05 / 0.043301... = 1.154700538
# two-sided p-value = 2 * norm.sf(1.154700538) = 0.2482130790
# (from scipy, not by hand - the hand-worked 0.248126198 was wrong)
S1, N = 30, 100
P0 = 0.25
Z_TARGET = 1.154700538
P_VALUE_TARGET = 0.2482130790


@pytest.fixture
def skills():
    return discover_skills()


def _drive(skill, params, skills, monkeypatch, results):
    """Run a plan with every step stubbed; return (result, calls)."""
    calls = []

    def fake(sk, p, config, buses, on_result, **kw):
        calls.append((sk.name, p))
        on_result(results.get(sk.name, {"status": "ok", "result": None}))

    monkeypatch.setattr(dispatch, "run_skill", fake)
    box = {}
    dispatch.run_plan(skill, params, None, None, lambda r: box.update(r), skills)
    return box, calls


def _drive_live(skill, params, skills, monkeypatch, s1=S1, n=N):
    """
    Drive the plan with `combine` and `distribution` running for real.

    Only the step that touches worker data is canned. `sum_core` is
    dispatched once.
    """
    calls = []
    sums = [{"status": "ok", "result": s1, "n": n}]

    class _Ctx:
        agent_id = "test"

    def fake(sk, p, config, buses, on_result, **kw):
        calls.append((sk.name, p))
        if sk.name in ("combine", "distribution"):
            on_result(sk.coordinate(_Ctx(), {"params": p}, []))
        elif sk.name == "sum_core":
            on_result(sums.pop(0))
        else:
            on_result({"status": "ok", "result": ["binary"]})

    monkeypatch.setattr(dispatch, "run_skill", fake)
    box = {}
    dispatch.run_plan(skill, params, None, None, lambda r: box.update(r), skills)
    return box, calls


# --- wiring ---------------------------------------------------------------

def test_the_plan_runs_its_steps_in_order(skills, monkeypatch):
    res, calls = _drive_live(skills["proportion_test"], {"p0": P0}, skills, monkeypatch)
    assert [n for n, _ in calls] == [
        "agree_representation", "sum_core", "combine", "combine", "distribution", "combine"]
    assert res["status"] == "ok"


def test_supplying_columns_skips_the_agreement_step(skills, monkeypatch):
    """RULE 2: a step whose outputs are already bound does not run."""
    _, calls = _drive_live(skills["proportion_test"], {"p0": P0, "columns": ["binary"]},
                           skills, monkeypatch)
    assert "agree_representation" not in [n for n, _ in calls]


def test_a_failed_step_aborts_the_plan(skills, monkeypatch):
    res, calls = _drive(skills["proportion_test"], {"p0": P0}, skills, monkeypatch, {
        "agree_representation": {"status": "ok", "result": ["binary"]},
        "sum_core": {"status": "error", "detail": "no data", "retryable": False},
    })
    assert res["status"] == "error"
    assert res["retryable"] is False
    assert "combine" not in [n for n, _ in calls]


def test_returns_re_export_everything_a_caller_needs(skills, monkeypatch):
    """z alone is not usable - a caller needs the p-value and counts."""
    res, _ = _drive_live(skills["proportion_test"], {"p0": P0}, skills, monkeypatch)
    for field in ("result", "p_value", "columns", "n"):
        assert field in res, f"{field} is not re-exported"
    assert res["n"] == N
    assert res["columns"] == ["binary"]


def test_the_z_statistic_uses_the_correct_formula(skills, monkeypatch):
    _, calls = _drive_live(skills["proportion_test"], {"p0": P0}, skills, monkeypatch)
    # `produces` belongs to the Step, not to the params a step is called
    # with, so it cannot be used to find the step here.
    z_step = next(p for n, p in calls
                  if n == "combine" and "p0" in (p.get("variables") or {}))
    assert "n" in z_step["variables"], "z step must use n in its expression"
    assert "**0.5" in z_step["expression"], "the standard error needs a square root"


def test_the_p_value_step_uses_the_normal_distribution(skills, monkeypatch):
    _, calls = _drive_live(skills["proportion_test"], {"p0": P0}, skills, monkeypatch)
    dist = next(p for n, p in calls if n == "distribution")
    assert dist["dist"] == "norm"
    assert dist["method"] == "sf"


# --- the arithmetic, against scipy ---------------------------------------

def test_the_statistic_matches_expected_value(skills, monkeypatch):
    """
    The test the stubbed ones cannot be: `combine` really evaluates here.
    """
    res, _ = _drive_live(skills["proportion_test"], {"p0": P0}, skills, monkeypatch)
    assert res["status"] == "ok"
    assert res["result"] == pytest.approx(Z_TARGET, abs=1e-6)


def test_the_p_value_matches_expected(skills, monkeypatch):
    res, _ = _drive_live(skills["proportion_test"], {"p0": P0}, skills, monkeypatch)
    assert res["p_value"] == pytest.approx(P_VALUE_TARGET, abs=1e-6)


def test_a_proportion_far_from_p0_gives_a_small_p_value(skills, monkeypatch):
    """Direction check - a statistic can be right in magnitude and wrong in sign."""
    res, _ = _drive_live(skills["proportion_test"], {"p0": 0.05}, skills, monkeypatch)
    assert res["result"] > 0
    assert res["p_value"] < 1e-6


def test_a_proportion_below_p0_gives_a_negative_z(skills, monkeypatch):
    """A proportion below p0 must give a negative statistic."""
    res, _ = _drive_live(skills["proportion_test"], {"p0": 0.50}, skills, monkeypatch)
    assert res["result"] < 0


def test_the_two_sided_p_value_is_a_probability_on_both_sides_of_p0(skills, monkeypatch):
    """
    sf is the UPPER tail, so a plan that doubles it without taking the
    magnitude first reports a "p-value" above 1 whenever z is negative.

    NOTE: this is deliberately not the symmetry check used for t_test.
    There the standard error is estimated from the sample and does not
    depend on mu0, so |t| is symmetric about the mean. Here the standard
    error is sqrt(p0*(1-p0)/n) and moves with p0, so the two sides are
    genuinely not mirror images - asserting that they are fails against a
    correct skill.
    """
    for p0 in (0.10, 0.20, 0.30, 0.40, 0.60, 0.90):
        res, _ = _drive_live(skills["proportion_test"], {"p0": p0}, skills, monkeypatch)
        assert 0.0 <= res["p_value"] <= 1.0, (
            f"p0={p0} gave p={res['p_value']}, which is not a probability")
