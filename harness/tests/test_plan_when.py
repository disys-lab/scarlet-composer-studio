"""
Tests for RULE 0 - conditional steps (`Step.when`).

`when` is general-purpose: it expresses any branch a plan needs, not just
a hypothesis test's tail. The hypothesis tests are its first consumer, so
the cases below are deliberately written against a synthetic plan rather
than against those skills - the infrastructure has to be correct
independently of them.
"""
import pytest

from scarlet_agentic_harness import dispatch
from scarlet_agentic_harness.plan_runner import _matches, _schema_defaults
from scarlet_agentic_harness.skills.base import CompoundSkill, Step
from scarlet_agentic_harness.skills.base import Skill


class _Echo(Skill):
    """Returns whatever `tag` it was handed, so calls are identifiable."""

    name = "echo"

    def contribute(self, ctx, request):  # pragma: no cover - never dispatched
        pass

    def coordinate(self, ctx, request, workers):  # pragma: no cover
        return {"status": "ok"}


def _registry(*names):
    reg = {}
    for n in names:
        s = _Echo()
        s.name = n
        reg[n] = s
    return reg


def _run(skill, params, monkeypatch):
    """Run a plan with every step stubbed; return (result, step names)."""
    calls = []

    def fake(sk, p, config, buses, on_result, **kw):
        calls.append(sk.name)
        on_result({"status": "ok", "result": p.get("tag", 1)})

    monkeypatch.setattr(dispatch, "run_skill", fake)
    box = {}
    names = [st.skill for st in skill.plan]
    dispatch.run_plan(skill, params, None, None, lambda r: box.update(r),
                      _registry(*names))
    return box, calls


class _Branching(CompoundSkill):
    """One output, three mutually exclusive producers."""

    name = "branching"
    description = "test fixture"
    parameters = {
        "type": "object",
        "properties": {
            "mode": {"type": "string",
                     "enum": ["upper", "lower", "two-sided"],
                     "default": "two-sided"},
        },
        "required": [],
    }
    plan = [
        Step("upper_branch", when={"mode": "upper"},
             params={"tag": "U"}, produces={"answer": "result"}),
        Step("lower_branch", when={"mode": "lower"},
             params={"tag": "L"}, produces={"answer": "result"}),
        Step("two_sided_branch", when={"mode": "two-sided"},
             params={"tag": "T"}, produces={"answer": "result"}),
    ]
    returns = {"result": "answer", "mode": "mode"}


# --- the branch itself ----------------------------------------------------

@pytest.mark.parametrize("mode,expected", [
    ("upper", "upper_branch"),
    ("lower", "lower_branch"),
    ("two-sided", "two_sided_branch"),
])
def test_exactly_one_branch_runs(mode, expected, monkeypatch):
    res, calls = _run(_Branching(), {"mode": mode}, monkeypatch)
    assert calls == [expected], f"mode={mode} ran {calls}"
    assert res["status"] == "ok"


def test_the_declared_default_applies_when_the_caller_omits_the_parameter(monkeypatch):
    """
    Without schema defaults, a plan branching on an omitted parameter runs
    *no* branch and returns nothing - silently.
    """
    res, calls = _run(_Branching(), {}, monkeypatch)
    assert calls == ["two_sided_branch"]
    assert res["result"] == "T"


def test_an_explicit_value_beats_the_default(monkeypatch):
    _, calls = _run(_Branching(), {"mode": "lower"}, monkeypatch)
    assert calls == ["lower_branch"]


def test_an_unmatched_value_runs_nothing_rather_than_guessing(monkeypatch):
    """A mode no branch claims must not fall through to an arbitrary one."""
    _, calls = _run(_Branching(), {"mode": "sideways"}, monkeypatch)
    assert calls == []


# --- RULE 0 beats RULE 1 --------------------------------------------------

class _ConditionalCheck(CompoundSkill):
    """A check step - no `produces` - that is also conditional."""

    name = "conditional_check"
    description = "test fixture"
    parameters = {"type": "object", "properties": {}, "required": []}
    plan = [
        Step("always", produces={"a": "result"}),
        Step("only_when_strict", when={"strict": True}),   # no produces
    ]
    returns = {"result": "a"}


def test_a_check_step_is_still_governed_by_its_condition(monkeypatch):
    """
    RULE 1 says a step with no outputs always runs. RULE 0 is checked
    first, so a conditional check obeys its condition - otherwise `when`
    would be silently ignored on exactly the steps that assert things.
    """
    _, off = _run(_ConditionalCheck(), {}, monkeypatch)
    assert off == ["always"]
    _, on = _run(_ConditionalCheck(), {"strict": True}, monkeypatch)
    assert on == ["always", "only_when_strict"]


# --- the matcher ----------------------------------------------------------

def test_a_list_condition_matches_any_member():
    assert _matches({"mode": ["upper", "two-sided"]}, {"mode": "upper"})
    assert _matches({"mode": ["upper", "two-sided"]}, {"mode": "two-sided"})
    assert not _matches({"mode": ["upper", "two-sided"]}, {"mode": "lower"})


def test_every_entry_must_match():
    ns = {"mode": "upper", "strict": True}
    assert _matches({"mode": "upper", "strict": True}, ns)
    assert not _matches({"mode": "upper", "strict": False}, ns)


def test_a_missing_variable_never_matches():
    """A condition on an unknown name is a skip, not a guess."""
    assert not _matches({"mode": "upper"}, {})
    assert not _matches({"mode": None}, {})


def test_an_empty_condition_is_vacuously_true():
    """Steps without `when` must be unaffected."""
    assert _matches({}, {})


def test_false_and_zero_are_matched_by_value_not_truthiness():
    assert _matches({"strict": False}, {"strict": False})
    assert not _matches({"strict": False}, {"strict": True})
    assert _matches({"k": 0}, {"k": 0})


# --- schema defaults ------------------------------------------------------

def test_schema_defaults_are_collected():
    assert _schema_defaults(_Branching()) == {"mode": "two-sided"}


def test_a_schema_without_defaults_contributes_nothing():
    assert _schema_defaults(_ConditionalCheck()) == {}
