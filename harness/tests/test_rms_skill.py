"""
Unit tests for the RMS (Root Mean Square) compound skill.

These run without Docker or Redis: run_plan's job is sequencing, namespace
bookkeeping and error propagation, none of which needs a fleet. Dispatch is
stubbed by monkeypatching dispatch.run_skill, so each test states only the
step results it cares about.

The RMS skill computes sqrt(sum(x^2)/n) per column using a three-step plan:
  1. agree_representation: determine the columns to process
  2. sum_core with transform="square": compute sum of squares per column
  3. combine: compute sqrt(s2/n) for each column
"""
import math
import pytest

from scarlet_agentic_harness import dispatch
from scarlet_agentic_harness.skills.base import CompoundSkill, Step
from scarlet_agentic_harness.skills.compound.rms import RmsSkill


def _registry(*names):
    """Each stub carries its own name - results and call records key on it."""
    reg = {}
    for n in names:
        skill = CompoundSkill()
        skill.name = n
        reg[n] = skill
    return reg


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


# ── TEST 1: the plan dispatches exactly agree_representation, sum_core, combine ─────────

def test_plan_dispatches_agree_representation_sum_core_combine_in_order(monkeypatch):
    """The RMS plan must run all three steps in the correct order."""
    skill = RmsSkill()
    names = [s.skill for s in skill.plan]
    results = {
        "agree_representation": {"status": "ok", "result": ["a", "b"]},
        "sum_core": {"status": "ok", "result": [10.0, 20.0], "n": 5, "columns": ["a", "b"]},
        "combine": {"status": "ok", "result": [math.sqrt(10.0 / 5), math.sqrt(20.0 / 5)]},
    }
    _, calls = _run(skill, {"objective": "power"}, _registry(*names), monkeypatch, results)
    assert [name for name, _ in calls] == ["agree_representation", "sum_core", "combine"]


# ── TEST 2: sum_core receives params including transform="square" ─────────

def test_sum_core_receives_transform_square(monkeypatch):
    """Without transform='square', sum_core returns Sigma(x) not Sigma(x^2)."""
    skill = RmsSkill()
    names = [s.skill for s in skill.plan]
    calls = []

    def capture_dispatch(skill, params, config, buses, on_result, **kw):
        calls.append((skill.name, params))
        if skill.name == "sum_core":
            # Verify transform="square" is present
            assert params.get("transform") == "square", "sum_core must receive transform='square'"
        on_result({"status": "ok", "result": [10.0, 20.0], "n": 5, "columns": ["a", "b"]})

    monkeypatch.setattr(dispatch, "run_skill", capture_dispatch)

    dispatch.run_plan(
        skill,
        {"objective": "power"},
        None,
        None,
        lambda r: None,
        _registry(*names),
    )

    # Confirm sum_core was called with the correct transform
    sum_core_calls = [c for c in calls if c[0] == "sum_core"]
    assert len(sum_core_calls) == 1
    assert sum_core_calls[0][1].get("transform") == "square"


# ── TEST 3: combine receives s2 and n, and returns re-exports result, columns AND n ─────────

def test_combine_receives_s2_and_n_and_returns_reexports(monkeypatch):
    """The combine step must receive s2 and n, and the final result must include result, columns, and n."""
    skill = RmsSkill()
    names = [s.skill for s in skill.plan]

    # Capture the params passed to combine
    combine_params = {}

    def capture_dispatch(skill, params, config, buses, on_result, **kw):
        if skill.name == "combine":
            combine_params.update(params)
        on_result({
            "status": "ok",
            "result": [math.sqrt(10.0 / 5), math.sqrt(20.0 / 5)],
            "columns": ["a", "b"],
            "n": 5,
        })

    monkeypatch.setattr(dispatch, "run_skill", capture_dispatch)

    box = {}
    dispatch.run_plan(
        skill,
        {"objective": "power"},
        None,
        None,
        lambda r: box.update(r),
        _registry(*names),
    )

    # Verify combine received s2 and n
    assert "s2" in combine_params.get("variables", {}), "combine must receive s2"
    assert "n" in combine_params.get("variables", {}), "combine must receive n"

    # Verify the final result includes result, columns, and n
    assert "result" in box, "final result must include 'result'"
    assert "columns" in box, "final result must include 'columns'"
    assert "n" in box, "final result must include 'n'"


# ── TEST 4: final result equals sqrt(s2/n) computed from canned numbers ─────────

def test_result_equals_sqrt_s2_over_n(monkeypatch):
    """Given canned step results, the final result must equal sqrt(s2/n) computed from those numbers."""
    skill = RmsSkill()
    names = [s.skill for s in skill.plan]

    # Canned step results: s2 = [10.0, 20.0], n = 5
    s2 = [10.0, 20.0]
    n = 5
    expected = [math.sqrt(x / n) for x in s2]

    results = {
        "agree_representation": {"status": "ok", "result": ["a", "b"]},
        "sum_core": {"status": "ok", "result": s2, "n": n, "columns": ["a", "b"]},
        "combine": {"status": "ok", "result": expected},
    }

    box, _ = _run(skill, {"objective": "power"}, _registry(*names), monkeypatch, results)

    # Verify the final result matches sqrt(s2/n) computed from the canned numbers
    assert box["result"] == pytest.approx(expected), f"Expected {expected}, got {box['result']}"
    assert box["columns"] == ["a", "b"]
    assert box["n"] == n


# ── Edge case: empty columns list (agreement step skipped) ─────────

def test_empty_columns_list_skips_agreement_step(monkeypatch):
    """If columns are supplied, agree_representation should be skipped."""
    skill = RmsSkill()
    names = [s.skill for s in skill.plan]

    results = {
        "sum_core": {"status": "ok", "result": [10.0, 20.0], "n": 5, "columns": ["a", "b"]},
        "combine": {"status": "ok", "result": [math.sqrt(10.0 / 5), math.sqrt(20.0 / 5)]},
    }

    _, calls = _run(
        skill,
        {"objective": "power", "columns": ["a", "b"]},
        _registry(*names),
        monkeypatch,
        results,
    )

    # agree_representation should be skipped when columns are provided
    assert [name for name, _ in calls] == ["sum_core", "combine"]

