"""
Tests for the z_test compound skill.

This skill had no test file at all until the p-value step was added to
it - the conformance suite was its only coverage. These follow the
AGENTS.md §5 harness, and the arithmetic ones let `combine` and
`distribution` actually execute rather than stubbing them.
"""
import pytest

from scarlet_agentic_harness import dispatch
from scarlet_agentic_harness.skills.registry import discover_skills


# worker1's vibration_rms against mu0 = 2.5 with sigma = 1.0.
# From scipy, not worked out on paper:
#   z = (s1/n - mu0)/(sigma/sqrt(n)) = 0.7467770942396454
#   stats.norm.sf(abs(z))           = 0.22759906218572928
#   two-sided = 2*sf                = 0.45519812437145857
S1, N, MU0, SIGMA = 204.1375, 79, 2.5, 1.0
SCIPY_Z = 0.7467770942396454
SCIPY_P_UPPER = 0.22759906218572928
SCIPY_P_TWO_SIDED = 0.45519812437145857


@pytest.fixture
def skills():
    return discover_skills()


def _drive_live(skills, monkeypatch, params, s1=S1, n=N):
    """Stub only the data-touching steps; combine and distribution run for real."""
    calls = []

    class _Ctx:
        agent_id = "test"

    def fake(sk, p, config, buses, on_result, **kw):
        calls.append((sk.name, p))
        if sk.name in ("combine", "distribution"):
            on_result(sk.coordinate(_Ctx(), {"params": p}, []))
        elif sk.name == "sum_core":
            on_result({"status": "ok", "result": s1, "n": n})
        else:
            on_result({"status": "ok", "result": ["vibration_rms"]})

    monkeypatch.setattr(dispatch, "run_skill", fake)
    box = {}
    dispatch.run_plan(skills["z_test"], params, None, None,
                      lambda r: box.update(r), skills)
    return box, calls


_P = {"mu0": MU0, "sigma": SIGMA}


# --- the arithmetic ------------------------------------------------------

def test_the_statistic_matches_scipy(skills, monkeypatch):
    res, _ = _drive_live(skills, monkeypatch, dict(_P))
    assert res["status"] == "ok"
    assert res["result"] == pytest.approx(SCIPY_Z, abs=1e-12)


def test_the_p_values_match_scipy(skills, monkeypatch):
    res, _ = _drive_live(skills, monkeypatch, dict(_P))
    assert res["p_upper"] == pytest.approx(SCIPY_P_UPPER, rel=1e-12)
    assert res["p_value"] == pytest.approx(SCIPY_P_TWO_SIDED, rel=1e-12)


def test_a_negative_statistic_still_gives_a_probability(skills, monkeypatch):
    """
    `sf` is the upper tail. Doubling it without taking |z| first reports a
    "p-value" above 1 for every z below zero - and the happy-path fixture
    above has a positive one, so only this test would catch it.
    """
    res, _ = _drive_live(skills, monkeypatch, {"mu0": 10.0, "sigma": SIGMA})
    assert res["result"] < 0
    assert 0.0 <= res["p_value"] <= 1.0


def test_the_two_sided_p_value_is_symmetric_about_the_mean(skills, monkeypatch):
    """
    Valid here, unlike for a proportion test: sigma is supplied by the
    caller and does not move with mu0, so the two sides really are mirror
    images.
    """
    xbar = S1 / N
    above, _ = _drive_live(skills, monkeypatch, {"mu0": xbar + 0.5, "sigma": SIGMA})
    below, _ = _drive_live(skills, monkeypatch, {"mu0": xbar - 0.5, "sigma": SIGMA})
    assert above["result"] == pytest.approx(-below["result"], abs=1e-12)
    assert above["p_value"] == pytest.approx(below["p_value"], abs=1e-12)


def test_a_mean_far_from_mu0_is_significant(skills, monkeypatch):
    res, _ = _drive_live(skills, monkeypatch, {"mu0": 0.0, "sigma": SIGMA})
    assert res["result"] > 0
    assert res["p_value"] < 1e-6


# --- wiring --------------------------------------------------------------

def test_the_plan_runs_its_steps_in_order(skills, monkeypatch):
    _, calls = _drive_live(skills, monkeypatch, dict(_P))
    assert [n for n, _ in calls] == [
        "agree_representation", "sum_core", "combine", "distribution", "combine"]


def test_it_uses_the_normal_distribution(skills, monkeypatch):
    _, calls = _drive_live(skills, monkeypatch, dict(_P))
    dist = next(p for n, p in calls if n == "distribution")
    assert dist["dist"] == "norm"
    assert dist["method"] == "sf"


def test_returns_re_export_the_statistic_and_the_p_value(skills, monkeypatch):
    res, _ = _drive_live(skills, monkeypatch, dict(_P))
    for field in ("result", "p_value", "p_upper", "columns", "n"):
        assert field in res, f"{field} is not re-exported"
    assert res["n"] == N


def test_supplying_columns_skips_the_agreement_step(skills, monkeypatch):
    """RULE 2: a step whose outputs are already bound does not run."""
    _, calls = _drive_live(skills, monkeypatch,
                           dict(_P, columns=["vibration_rms"]))
    assert "agree_representation" not in [n for n, _ in calls]


def test_it_can_be_scoped_to_one_worker(skills, monkeypatch):
    _, calls = _drive_live(skills, monkeypatch, dict(_P, workers=["w1"]))
    agg = next(p for n, p in calls if n == "sum_core")
    assert agg["workers"] == ["w1"]


def test_a_failed_step_aborts_the_plan(skills, monkeypatch):
    def fake(sk, p, config, buses, on_result, **kw):
        if sk.name == "sum_core":
            on_result({"status": "error", "detail": "no data", "retryable": False})
        else:
            on_result({"status": "ok", "result": ["vibration_rms"]})

    monkeypatch.setattr(dispatch, "run_skill", fake)
    box = {}
    dispatch.run_plan(skills["z_test"], dict(_P), None, None,
                      lambda r: box.update(r), skills)
    assert box["status"] == "error"
    assert box["retryable"] is False


# --- every tail, against scipy -------------------------------------------

TAILS = {
    "upper": 0.22759906218572928,
    "lower": 0.7724009378142707,
    "two-sided": 0.45519812437145857,
}


@pytest.mark.parametrize("mode", ["upper", "lower", "two-sided"])
def test_each_mode_gives_the_right_p_value(mode, skills, monkeypatch):
    """
    One assertion per tail, against scipy.

    The three are easy to confuse and all look like probabilities: for
    this fixture upper and lower differ by a factor of thousands, and a
    two-sided value used for a one-sided question is exactly double.
    """
    res, _ = _drive_live(skills, monkeypatch, dict(_P, mode=mode))
    assert res["status"] == "ok"
    assert res["mode"] == mode
    assert res["p_value"] == pytest.approx(TAILS[mode], rel=1e-9)
    assert 0.0 <= res["p_value"] <= 1.0


def test_omitting_mode_defaults_to_two_sided(skills, monkeypatch):
    """The schema default must reach the plan, or no branch runs at all."""
    mode = "two-sided"
    res, _ = _drive_live(skills, monkeypatch, dict(_P))
    assert res["mode"] == "two-sided"
    assert res["p_value"] == pytest.approx(TAILS["two-sided"], rel=1e-9)


def test_the_upper_and_lower_tails_are_complementary(skills, monkeypatch):
    mode = "upper"
    up, _ = _drive_live(skills, monkeypatch, dict(_P, mode=mode))
    mode = "lower"
    lo, _ = _drive_live(skills, monkeypatch, dict(_P, mode=mode))
    assert up["p_value"] + lo["p_value"] == pytest.approx(1.0, abs=1e-12)
