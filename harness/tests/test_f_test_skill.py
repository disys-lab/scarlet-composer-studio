"""
Tests for the f_test compound skill.

Written with the compound-test harness exactly as docs/AGENTS.md §5 gives
it, which doubles as a check that the harness in the guide actually works.

What matters most here is the *calls* list, not the final number. An
earlier version of this skill declared a `group_column` parameter, then
wrote two identical `mean` steps that referenced it nowhere - so both
groups computed the same value over the whole fleet and F was always
exactly 1.0. It dispatched, returned, and looked entirely plausible. Only
an assertion on what each step received would have caught it.
"""
import pytest

from scarlet_agentic_harness import dispatch
from scarlet_agentic_harness.skills.base import Skill
from scarlet_agentic_harness.skills.compound.f_test import FTestSkill


class _Atomic(Skill):
    """Stands in for any step the plan dispatches."""

    name = "atomic"

    def contribute(self, ctx, request):  # pragma: no cover - never dispatched
        pass

    def coordinate(self, ctx, request, workers):  # pragma: no cover
        return {"status": "ok"}


def _registry(*names):
    reg = {}
    for n in names:
        s = _Atomic()
        s.name = n
        reg[n] = s
    return reg


def _run(skill, params, results, monkeypatch):
    """Run the plan with canned step results; return (final, calls)."""
    calls, box = [], {}

    def fake(step_skill, step_params, config, buses, on_result, **kw):
        calls.append((step_skill.name, step_params))
        on_result(results.get(step_skill.name, {"status": "ok", "result": None}))

    monkeypatch.setattr(dispatch, "run_skill", fake)
    names = [st.skill for st in skill.plan]
    dispatch.run_plan(skill, params, None, None, lambda r: box.update(r),
                      _registry(*names))
    return box, calls


_GROUPS = {"group_a": ["w1", "w2"], "group_b": ["w3", "w4"]}


def _results(var_a=4.0, var_b=1.0, n=10):
    """Canned step results; `variance` is dispatched twice and answers both."""
    return {
        "agree_representation": {"status": "ok", "result": ["vibration_rms"]},
        "variance": {"status": "ok", "result": [var_a], "n": n},
        "combine": {"status": "ok", "result": [var_a / var_b]},
        "distribution": {"status": "ok", "result": [0.05]},
    }


def test_the_plan_runs_its_steps_in_order(monkeypatch):
    final, calls = _run(FTestSkill(), dict(_GROUPS), _results(), monkeypatch)
    assert final["status"] == "ok"
    assert [name for name, _ in calls] == [
        "agree_representation", "variance", "variance", "combine",
        "combine", "combine", "distribution", "combine"]


def test_the_two_variance_steps_get_different_workers(monkeypatch):
    """
    The whole point of the skill. Identical `workers` on both steps gives
    F = 1.0 for any input, which is the bug this replaces.
    """
    _, calls = _run(FTestSkill(), dict(_GROUPS), _results(), monkeypatch)
    variance_calls = [p for name, p in calls if name == "variance"]
    assert len(variance_calls) == 2
    assert variance_calls[0]["workers"] == ["w1", "w2"]
    assert variance_calls[1]["workers"] == ["w3", "w4"]


def test_combine_receives_both_variances(monkeypatch):
    _, calls = _run(FTestSkill(), dict(_GROUPS), _results(), monkeypatch)
    combine = next(p for name, p in calls if name == "combine")
    assert "var_a" in combine["variables"] and "var_b" in combine["variables"]
    assert "/" in combine["expression"]


def test_the_p_value_step_uses_the_f_distribution_with_both_dfs(monkeypatch):
    _, calls = _run(FTestSkill(), dict(_GROUPS), _results(), monkeypatch)
    dist = next(p for name, p in calls if name == "distribution")
    assert dist["dist"] == "f"
    assert dist["method"] == "sf"
    assert "dfn" in dist["params"] and "dfd" in dist["params"]


def test_returns_re_export_everything_a_caller_needs(monkeypatch):
    """F alone is not usable - a caller needs the p-value and the counts."""
    final, _ = _run(FTestSkill(), dict(_GROUPS), _results(), monkeypatch)
    for field in ("result", "p_value", "columns"):
        assert field in final, f"{field} is not re-exported"


def test_supplying_columns_skips_the_agreement_step(monkeypatch):
    """RULE 2: a step whose outputs are already bound does not run."""
    params = dict(_GROUPS, columns=["vibration_rms"])
    _, calls = _run(FTestSkill(), params, _results(), monkeypatch)
    assert "agree_representation" not in [name for name, _ in calls]


def test_a_failed_step_aborts_the_plan(monkeypatch):
    results = _results()
    results["variance"] = {"status": "error", "detail": "no data",
                           "retryable": False}
    final, calls = _run(FTestSkill(), dict(_GROUPS), results, monkeypatch)
    assert final["status"] == "error"
    assert final["retryable"] is False
    assert "combine" not in [name for name, _ in calls]


# --- the arithmetic, against scipy ----------------------------------------
#
# Everything above stubs `combine`, so none of it ever evaluated an
# expression or noticed that the plan passed `n` where scipy wants `n-1`,
# or that it reported a one-sided tail as the p-value of a two-sided test.
# Measured live before the fix: F=0.8398 gave p=0.7896, which is
# sf(F, 79, 99) - wrong degrees of freedom AND the wrong tail. The correct
# two-sided answer on df=(78,98) is 0.423729.

import pytest
from scarlet_agentic_harness.skills.registry import discover_skills

# What the `variance` step actually hands back: the POPULATION variance
# (its expression is "s2/n - mean**2", ddof=0). Feeding it sample
# variances here would have hidden the Bessel-correction bug, because the
# fixture would have been pre-corrected and the plan's own correction
# would then be invisible.
#   sample variances from the real worker CSVs: 0.307269, 0.364958
#   population = sample * (n-1)/n
VAR_A, VAR_B, N_A, N_B = 0.3033795189873418, 0.36127155555555557, 79, 99
# Taken from scipy's own output, not worked out on paper:
#   F = var_a/var_b = 0.8419297563007251
#   stats.f.sf(F, 78, 98)              = 0.7847384682506593
#   2*min(sf, stats.f.cdf(F, 78, 98))  = 0.43052306349868136
SCIPY_F = 0.8419297563007251
SCIPY_P_UPPER = 0.7847384682506593
SCIPY_P_TWO_SIDED = 0.43052306349868136


def _drive_live(params, monkeypatch, var_a=VAR_A, var_b=VAR_B, n_a=N_A, n_b=N_B):
    """Stub only the data-touching steps; run combine and distribution for real."""
    skills = discover_skills()
    variances = [{"status": "ok", "result": var_a, "n": n_a},
                 {"status": "ok", "result": var_b, "n": n_b}]

    class _Ctx:
        agent_id = "test"

    def fake(sk, p, config, buses, on_result, **kw):
        if sk.name in ("combine", "distribution"):
            on_result(sk.coordinate(_Ctx(), {"params": p}, []))
        elif sk.name == "variance":
            on_result(variances.pop(0))
        else:
            on_result({"status": "ok", "result": ["vibration_rms"]})

    monkeypatch.setattr(dispatch, "run_skill", fake)
    box = {}
    dispatch.run_plan(skills["f_test"], params, None, None,
                      lambda r: box.update(r), skills)
    return box


def test_the_f_statistic_matches_scipy(monkeypatch):
    res = _drive_live(dict(_GROUPS), monkeypatch)
    assert res["status"] == "ok"
    assert res["result"] == pytest.approx(SCIPY_F, abs=1e-6)


def test_the_degrees_of_freedom_are_n_minus_one(monkeypatch):
    """(n-1, n-1), not (n, n) - the bug this replaces."""
    res = _drive_live(dict(_GROUPS), monkeypatch)
    assert res["df_a"] == N_A - 1
    assert res["df_b"] == N_B - 1


def test_the_p_value_is_two_sided(monkeypatch):
    """
    The docstring has always said two-sided; the plan emitted a bare `sf`.
    For F < 1 the upper tail is above 0.5, so the two disagree loudly.
    """
    res = _drive_live(dict(_GROUPS), monkeypatch)
    assert res["p_upper"] == pytest.approx(SCIPY_P_UPPER, abs=1e-6)
    assert res["p_value"] == pytest.approx(SCIPY_P_TWO_SIDED, abs=1e-6)


def test_the_p_value_is_a_probability_whichever_group_is_larger(monkeypatch):
    """
    Swapping the groups inverts F, so one order exercises the upper tail
    and the other the lower. A one-sided `sf` returns >1 nonsense for one
    of them; a correct two-sided p is symmetric under the swap.
    """
    normal = _drive_live(dict(_GROUPS), monkeypatch)
    swapped = _drive_live(dict(_GROUPS), monkeypatch,
                          var_a=VAR_B, var_b=VAR_A, n_a=N_B, n_b=N_A)
    for res in (normal, swapped):
        assert 0.0 <= res["p_value"] <= 1.0
    assert normal["p_value"] == pytest.approx(swapped["p_value"], abs=1e-6)
