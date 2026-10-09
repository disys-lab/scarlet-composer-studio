"""
Tests for the t_test compound skill.

Written with the compound-test harness exactly as docs/AGENTS.md §5 gives
it, which doubles as a check that the harness in the guide actually works.

The arithmetic tests at the bottom are the ones that matter. Every other
test here stubs `combine`, and every one of them passed against a plan
whose expression was `(s1/n - mu0)/sqrt(...)` - which `combine` cannot
evaluate at all, because safe_eval has no function calls and therefore no
`sqrt`. The skill could not run once. Stubbing the arithmetic means the
tests agree with the plan about the shape of each call and never ask
whether the number coming out is right, so the only test that can catch
that class of defect is one that lets `combine` and `distribution`
actually execute.
"""
import pytest

from scarlet_agentic_harness import dispatch
from scarlet_agentic_harness.skills.registry import discover_skills


# A sample whose answer is known: scipy.stats.ttest_1samp(XS, 100.0) gives
# t = 0.3084435454 and p = 0.7647647163.
XS = [102.0, 98.0, 101.5, 99.0, 103.0, 97.5, 100.5, 104.0, 96.0, 101.0]
MU0 = 100.0
S1, S2, N = 1002.5, 100559.75, 10
SCIPY_T, SCIPY_P = 0.3084435454, 0.7647647163


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


def _drive_live(skill, params, skills, monkeypatch, s1=S1, s2=S2, n=N):
    """
    Drive the plan with `combine` and `distribution` running for real.

    Only the two steps that touch worker data are canned. `sum_core` is
    dispatched twice - plain, then with transform=square - so it answers
    from a queue rather than with one fixed value.
    """
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
            on_result({"status": "ok", "result": ["value"]})

    monkeypatch.setattr(dispatch, "run_skill", fake)
    box = {}
    dispatch.run_plan(skill, params, None, None, lambda r: box.update(r), skills)
    return box, calls


# --- wiring ---------------------------------------------------------------

def test_the_plan_runs_its_steps_in_order(skills, monkeypatch):
    res, calls = _drive_live(skills["t_test"], {"mu0": MU0}, skills, monkeypatch)
    assert [n for n, _ in calls] == [
        "agree_representation", "sum_core", "sum_core",
        "combine", "combine", "combine", "distribution", "combine"]
    assert res["status"] == "ok"


def test_the_two_sum_core_steps_use_different_transforms(skills, monkeypatch):
    """Identity then square - the two moments a variance needs."""
    _, calls = _drive_live(skills["t_test"], {"mu0": MU0}, skills, monkeypatch)
    sums = [p for n, p in calls if n == "sum_core"]
    assert len(sums) == 2
    assert sums[0].get("transform") in (None, "identity")
    assert sums[1].get("transform") == "square"


def test_supplying_columns_skips_the_agreement_step(skills, monkeypatch):
    """RULE 2: a step whose outputs are already bound does not run."""
    _, calls = _drive_live(skills["t_test"], {"mu0": MU0, "columns": ["value"]},
                           skills, monkeypatch)
    assert "agree_representation" not in [n for n, _ in calls]


def test_a_failed_step_aborts_the_plan(skills, monkeypatch):
    res, calls = _drive(skills["t_test"], {"mu0": MU0}, skills, monkeypatch, {
        "agree_representation": {"status": "ok", "result": ["value"]},
        "sum_core": {"status": "error", "detail": "no data", "retryable": False},
    })
    assert res["status"] == "error"
    assert res["retryable"] is False
    assert "combine" not in [n for n, _ in calls]


def test_returns_re_export_everything_a_caller_needs(skills, monkeypatch):
    """t alone is not usable - a caller needs the p-value, df and counts."""
    res, _ = _drive_live(skills["t_test"], {"mu0": MU0}, skills, monkeypatch)
    for field in ("result", "p_value", "df", "columns", "n"):
        assert field in res, f"{field} is not re-exported"
    assert res["n"] == N
    assert res["columns"] == ["value"]


def test_the_p_value_step_uses_the_t_distribution_with_n_minus_one_df(skills, monkeypatch):
    _, calls = _drive_live(skills["t_test"], {"mu0": MU0}, skills, monkeypatch)
    dist = next(p for n, p in calls if n == "distribution")
    assert dist["dist"] == "t"
    assert dist["method"] == "sf"
    assert dist["params"]["df"] == N - 1


# --- the arithmetic, against scipy ---------------------------------------

def test_the_statistic_matches_scipy(skills, monkeypatch):
    """
    The test the stubbed ones cannot be: `combine` really evaluates here.

    A plan that reaches this point has been proved to be inside safe_eval's
    grammar *and* to compute the textbook quantity. The previous version of
    this skill failed on the first count alone.
    """
    res, _ = _drive_live(skills["t_test"], {"mu0": MU0}, skills, monkeypatch)
    assert res["status"] == "ok"
    assert res["result"] == pytest.approx(SCIPY_T, abs=1e-9)


def test_the_p_value_matches_scipy(skills, monkeypatch):
    """Two-sided, so sf(t) doubled - and sf is the upper tail only."""
    res, _ = _drive_live(skills["t_test"], {"mu0": MU0}, skills, monkeypatch)
    assert res["p_value"] == pytest.approx(SCIPY_P, abs=1e-9)


def test_a_mean_far_above_mu0_gives_a_small_p_value(skills, monkeypatch):
    """Direction check - a statistic can be right in magnitude and wrong in sign."""
    res, _ = _drive_live(skills["t_test"], {"mu0": 50.0}, skills, monkeypatch)
    assert res["result"] > 0
    assert res["p_value"] < 1e-6


def test_the_two_sided_p_value_is_symmetric_about_the_mean(skills, monkeypatch):
    """
    sf is one-tailed, so a plan that forgets to double it, or that doubles
    the wrong tail, disagrees here: an mu0 above and one below the sample
    mean by the same amount must give the same two-sided p.
    """
    xbar = S1 / N
    above, _ = _drive_live(skills["t_test"], {"mu0": xbar + 1.0}, skills, monkeypatch)
    below, _ = _drive_live(skills["t_test"], {"mu0": xbar - 1.0}, skills, monkeypatch)
    assert above["result"] == pytest.approx(-below["result"], abs=1e-12)
    assert above["p_value"] == pytest.approx(below["p_value"], abs=1e-12)
