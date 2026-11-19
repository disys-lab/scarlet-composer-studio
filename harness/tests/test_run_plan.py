"""
Unit tests for the plan runner.

These run without Docker or Redis: run_plan's job is sequencing, namespace
bookkeeping and error propagation, none of which needs a fleet. Dispatch is
stubbed by monkeypatching dispatch.run_skill, so each test states only the
step results it cares about.

The three rules are the whole semantics, so each gets a test that fails if
the rule is removed.
"""
import pytest

from scarlet_agentic_harness import dispatch
from scarlet_agentic_harness.skills.base import CompoundSkill, Skill, Step


class _Atomic(Skill):
    name = "atomic"

    def contribute(self, ctx, request):  # pragma: no cover - never dispatched here
        pass

    def coordinate(self, ctx, request, workers):  # pragma: no cover
        return {"status": "ok"}


def _registry(*names):
    """Each stub carries its own name - results and call records key on it."""
    reg = {}
    for n in names:
        skill = _Atomic()
        skill.name = n
        reg[n] = skill
    return reg


def _compound(plan, returns):
    c = CompoundSkill()
    c.name = "test_compound"
    c.plan = plan
    c.returns = returns
    return c


def _stub_dispatch(monkeypatch, results, calls):
    """Replace run_skill so a step returns a canned result and records its params."""
    def fake(skill, params, config, buses, on_result, **kw):
        calls.append((skill.name, params))
        on_result(results.get(skill.name, {"status": "ok", "result": None}))
    monkeypatch.setattr(dispatch, "run_skill", fake)


def _run(compound, params, skills, monkeypatch, results):
    calls, box = [], {}
    _stub_dispatch(monkeypatch, results, calls)
    dispatch.run_plan(compound, params, None, None, lambda r: box.update(r), skills)
    return box, calls


# ── RULE 2: skip ─────────────────────────────────────────────────────────

def test_a_step_whose_outputs_are_already_bound_is_skipped(monkeypatch):
    """The caller supplied `columns`, so consensus must not run at all."""
    c = _compound([Step("agree", produces={"columns": "result"}),
                   Step("atomic", produces={"total": "result"})], "total")
    res, calls = _run(c, {"columns": ["a", "b"]}, _registry("agree", "atomic"),
                      monkeypatch, {"atomic": {"status": "ok", "result": 7}})
    assert [n for n, _ in calls] == ["atomic"], "agree should have been skipped"
    assert res["result"] == 7


def test_an_unbound_step_does_run(monkeypatch):
    """Nothing supplied `columns`, so the producing step must run."""
    c = _compound([Step("agree", produces={"columns": "result"}),
                   Step("atomic", produces={"total": "result"})], "total")
    res, calls = _run(c, {}, _registry("agree", "atomic"), monkeypatch,
                      {"agree": {"status": "ok", "result": ["a"]},
                       "atomic": {"status": "ok", "result": 7}})
    assert [n for n, _ in calls] == ["agree", "atomic"]


def test_an_empty_list_counts_as_bound(monkeypatch):
    """
    `is not None`, not truthiness.

    An empty list means "computed, and the answer is nothing". Treating it as
    unbound would re-run the step forever.
    """
    c = _compound([Step("agree", produces={"columns": "result"}),
                   Step("atomic", produces={"total": "result"})], "total")
    _, calls = _run(c, {"columns": []}, _registry("agree", "atomic"),
                    monkeypatch, {"atomic": {"status": "ok", "result": 1}})
    assert "agree" not in [n for n, _ in calls]


# ── RULE 1: always-run ───────────────────────────────────────────────────

def test_a_step_with_no_outputs_always_runs(monkeypatch):
    """A check produces nothing, so it has nothing to already have."""
    c = _compound([Step("check"), Step("atomic", produces={"total": "result"})], "total")
    _, calls = _run(c, {"columns": ["a"], "total": None}, _registry("check", "atomic"),
                    monkeypatch, {"atomic": {"status": "ok", "result": 3}})
    assert "check" in [n for n, _ in calls]


def test_a_check_runs_even_when_everything_else_is_bound(monkeypatch):
    """This is the validation case: columns supplied, and the check still fires."""
    c = _compound([Step("check"), Step("atomic", produces={"total": "result"})], "total")
    _, calls = _run(c, {"total": 99}, _registry("check", "atomic"), monkeypatch, {})
    assert [n for n, _ in calls] == ["check"], "check runs, atomic skips"


# ── RULE 3: abort ────────────────────────────────────────────────────────

def test_a_failed_step_aborts_the_plan_and_names_itself(monkeypatch):
    c = _compound([Step("agree", produces={"columns": "result"}),
                   Step("atomic", produces={"total": "result"})], "total")
    res, calls = _run(c, {}, _registry("agree", "atomic"), monkeypatch,
                      {"agree": {"status": "error", "detail": "no common columns",
                                 "retryable": False}})
    assert res["status"] == "error"
    assert "agree" in res["detail"] and "no common columns" in res["detail"]
    assert [n for n, _ in calls] == ["agree"], "must not continue past a failure"


def test_retryable_is_carried_upward(monkeypatch):
    """An unretryable child failure must not be retried by the caller."""
    c = _compound([Step("agree", produces={"columns": "result"})], "columns")
    res, _ = _run(c, {}, _registry("agree"), monkeypatch,
                  {"agree": {"status": "error", "detail": "x", "retryable": False}})
    assert res["retryable"] is False


# ── namespace, params and returns ────────────────────────────────────────

def test_namespace_is_ambient_so_params_reach_every_step(monkeypatch):
    """`workers` was never declared by any step and must still arrive."""
    c = _compound([Step("atomic", produces={"total": "result"})], "total")
    _, calls = _run(c, {"workers": ["w1", "w2"]}, _registry("atomic"),
                    monkeypatch, {"atomic": {"status": "ok", "result": 1}})
    assert calls[0][1]["workers"] == ["w1", "w2"]


def test_dollar_refs_are_resolved_including_inside_nested_dicts(monkeypatch):
    c = _compound([Step("atomic", produces={"s1": "result"}),
                   Step("combine",
                        params={"expression": "s1/n",
                                "variables": {"s1": "$s1", "n": "$n"}},
                        produces={"mean": "result"})], "mean")
    _, calls = _run(c, {"n": 4}, _registry("atomic", "combine"), monkeypatch,
                    {"atomic": {"status": "ok", "result": 12},
                     "combine": {"status": "ok", "result": 3}})
    combine_params = [p for n, p in calls if n == "combine"][0]
    assert combine_params["variables"] == {"s1": 12, "n": 4}
    assert combine_params["expression"] == "s1/n", "a non-$ string is left alone"


def test_returns_mapping_exposes_more_than_one_field(monkeypatch):
    """
    sum must hand back n as well as the sums.

    A compound that returns only `result` silently gives back less than the
    skill it wraps, and anything composing a mean from it breaks.
    """
    c = _compound([Step("atomic", produces={"column_sums": "result", "n": "n"})],
                  {"result": "column_sums", "n": "n"})
    res, _ = _run(c, {}, _registry("atomic"), monkeypatch,
                  {"atomic": {"status": "ok", "result": [1, 2], "n": 380}})
    assert res["result"] == [1, 2]
    assert res["n"] == 380


def test_unknown_skill_in_a_plan_is_a_clear_error(monkeypatch):
    c = _compound([Step("nope", produces={"x": "result"})], "x")
    res, _ = _run(c, {}, _registry("atomic"), monkeypatch, {})
    assert res["status"] == "error" and "nope" in res["detail"]


def test_depth_cap_stops_runaway_nesting(monkeypatch):
    c = _compound([Step("atomic", produces={"x": "result"})], "x")
    box = {}
    dispatch.run_plan(c, {}, None, None, lambda r: box.update(r), _registry("atomic"),
                      depth=dispatch.MAX_PLAN_DEPTH)
    assert box["status"] == "error"
    assert str(dispatch.MAX_PLAN_DEPTH) in box["detail"]
    assert box["retryable"] is False


# --- the row filter must reach every step of a plan -------------------------
#
# Propagation is implicit: run_plan seeds its namespace with the compound's
# own params, and every step gets {**ns, **step.params}. Implicit is exactly the
# kind of thing that silently stops working, and a filter that reaches some
# steps but not others produces a plausible wrong number rather than an
# error - so it gets its own tests.

_WINDOW = [
    {"column": "ts", "op": "gte", "value": "2026-01-01T00:00:00"},
    {"column": "ts", "op": "lt", "value": "2026-02-01T00:00:00"},
]


def test_conditions_reach_every_step_of_a_plan(monkeypatch):
    """A filter given to the compound is seen by all of its steps."""
    compound = _compound(
        [Step("a", produces={"x": "result"}),
         Step("b", produces={"y": "result"})],
        {"result": "y"},
    )
    _, calls = _run(
        compound, {"objective": "power", "conditions": _WINDOW},
        _registry("a", "b"), monkeypatch,
        {"a": {"status": "ok", "result": 1}, "b": {"status": "ok", "result": 2}},
    )
    assert [name for name, _ in calls] == ["a", "b"]
    for name, params in calls:
        assert params.get("conditions") == _WINDOW, f"step {name} lost the filter"


def test_a_steps_own_params_do_not_drop_the_filter(monkeypatch):
    """A step that sets its own params still inherits conditions."""
    compound = _compound(
        [Step("a", params={"transform": "square"}, produces={"x": "result"})],
        {"result": "x"},
    )
    _, calls = _run(
        compound, {"conditions": _WINDOW}, _registry("a"), monkeypatch,
        {"a": {"status": "ok", "result": 1}},
    )
    _, params = calls[0]
    assert params["transform"] == "square"
    assert params["conditions"] == _WINDOW


def test_the_real_variance_plan_carries_the_filter_to_every_step(monkeypatch):
    """
    The shipped variance compound, not a synthetic one.

    variance nests mean, which nests sum_core - the filter has to survive
    two levels, and variance is what a time-windowed question actually
    calls.
    """
    from scarlet_agentic_harness.skills.compound.variance import VarianceSkill

    compound = VarianceSkill()
    names = [s.skill for s in compound.plan]
    results = {n: {"status": "ok", "result": 1, "n": 10} for n in names}
    _, calls = _run(
        compound, {"objective": "power", "conditions": _WINDOW},
        _registry(*names), monkeypatch, results,
    )
    assert calls, "variance plan dispatched nothing"
    for name, params in calls:
        assert params.get("conditions") == _WINDOW, f"step {name} lost the filter"


def test_conditions_are_declared_on_every_filterable_skill():
    """
    The schema has to advertise it or the head will never pass it.

    Propagation being automatic is worthless if the tool description does
    not mention the parameter - this is the gap that would make a filtered
    question silently return an unfiltered answer.
    """
    from scarlet_agentic_harness.skills.core.sum import SumCoreSkill
    from scarlet_agentic_harness.skills.core.median import MedianSkill
    from scarlet_agentic_harness.skills.compound.sum import SumSkill
    from scarlet_agentic_harness.skills.compound.mean import MeanSkill
    from scarlet_agentic_harness.skills.compound.variance import VarianceSkill

    for cls in (SumCoreSkill, MedianSkill, SumSkill, MeanSkill, VarianceSkill):
        props = cls.parameters.get("properties", {})
        assert "conditions" in props, f"{cls.__name__} does not advertise conditions"
