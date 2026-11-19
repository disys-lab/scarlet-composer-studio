"""
The sum / mean / variance compounds.

Dispatch is stubbed, so these assert the PLAN - step order, what is
skipped, what flows between steps - rather than arithmetic. The arithmetic
is already covered by test_safe_eval_vectors.py, and end to end by the
notebooks.

Two properties here are easy to get wrong and fail silently, so each has
its own test: variance must take `n` from its own sum_core rather than
from mean, and the nested `mean` must not re-run consensus.
"""
import pytest

from scarlet_agentic_harness import dispatch
from scarlet_agentic_harness.skills.registry import discover_skills


@pytest.fixture
def skills():
    return discover_skills()


def _drive(skill, params, skills, monkeypatch, results):
    """Run a plan with dispatch stubbed; return (result, ordered step calls)."""
    calls = []

    def fake(sk, p, config, buses, on_result, **kw):
        calls.append((sk.name, p))
        if isinstance(sk, type(skills["sum"])) or hasattr(sk, "plan"):
            # a nested compound: run its plan for real, through this same stub
            dispatch.run_plan(sk, p, config, buses, on_result, skills,
                              depth=kw.get("depth", 0))
            return
        on_result(results.get(sk.name, {"status": "ok", "result": None}))

    monkeypatch.setattr(dispatch, "run_skill", fake)
    box = {}
    dispatch.run_plan(skill, params, None, None, lambda r: box.update(r), skills)
    return box, [n for n, _ in calls]


def test_sum_agrees_then_aggregates(skills, monkeypatch):
    res, order = _drive(skills["sum"], {}, skills, monkeypatch, {
        "agree_representation": {"status": "ok", "result": ["a", "b"]},
        "sum_core": {"status": "ok", "result": [10.0, 20.0], "n": 7},
    })
    assert order == ["agree_representation", "sum_core"]
    assert res["result"] == [10.0, 20.0]
    assert res["n"] == 7, "sum must hand back n, not only the sums"


def test_sum_skips_agreement_when_columns_are_supplied(skills, monkeypatch):
    _, order = _drive(skills["sum"], {"columns": ["a"]}, skills, monkeypatch,
                      {"sum_core": {"status": "ok", "result": [1.0], "n": 2}})
    assert order == ["sum_core"]


def test_mean_and_variance_label_their_values(skills, monkeypatch):
    """
    A bare list of numbers cannot be labelled by the caller.

    Observed before this was fixed: the head reported "Column 1 / Column 2 /
    Column 3" and guessed n was a worker count, because the compound hid the
    agreement step and therefore hid which columns were agreed.
    """
    for name in ("mean", "variance"):
        res, _ = _drive(skills[name], {}, skills, monkeypatch, {
            "agree_representation": {"status": "ok", "result": ["a", "b"]},
            "sum_core": {"status": "ok", "result": [10.0, 20.0], "n": 5},
            "combine": {"status": "ok", "result": [2.0, 4.0]},
        })
        assert res["columns"] == ["a", "b"], f"{name} must say which columns"
        assert res["n"] == 5, f"{name} must say how many rows"


def test_mean_divides_the_sums_by_n(skills, monkeypatch):
    res, order = _drive(skills["mean"], {}, skills, monkeypatch, {
        "agree_representation": {"status": "ok", "result": ["a", "b"]},
        "sum_core": {"status": "ok", "result": [10.0, 20.0], "n": 5},
        "combine": {"status": "ok", "result": [2.0, 4.0]},
    })
    assert order == ["agree_representation", "sum_core", "combine"]
    assert res["result"] == [2.0, 4.0]


def test_mean_passes_the_sums_and_n_into_combine(skills, monkeypatch):
    """The $-refs must resolve from the namespace, not arrive as literals."""
    calls = []

    def fake(sk, p, config, buses, on_result, **kw):
        calls.append((sk.name, p))
        on_result({"agree_representation": {"status": "ok", "result": ["a"]},
                   "sum_core": {"status": "ok", "result": [10.0], "n": 5},
                   "combine": {"status": "ok", "result": [2.0]}}[sk.name])

    monkeypatch.setattr(dispatch, "run_skill", fake)
    dispatch.run_plan(skills["mean"], {}, None, None, lambda r: None, skills)
    combine_params = [p for n, p in calls if n == "combine"][0]
    assert combine_params["variables"] == {"s1": [10.0], "n": 5}
    assert combine_params["expression"] == "s1/n"


def test_variance_calls_mean_and_does_not_rerun_consensus(skills, monkeypatch):
    """
    One consensus round for the whole nested plan.

    `columns` is bound by variance's own first step; the ambient namespace
    carries it into mean, whose agree_representation step is then skipped.
    Two rounds means the namespace is not reaching the sub-compound.
    """
    res, order = _drive(skills["variance"], {}, skills, monkeypatch, {
        "agree_representation": {"status": "ok", "result": ["a", "b"]},
        "sum_core": {"status": "ok", "result": [10.0, 20.0], "n": 5},
        "combine": {"status": "ok", "result": [1.5, 2.5]},
    })
    assert order.count("agree_representation") == 1, f"consensus ran twice: {order}"
    assert "mean" in order
    assert res["result"] == [1.5, 2.5]


def test_variance_takes_n_from_its_own_sum_core(skills, monkeypatch):
    """
    A sub-compound returns only its `returns` value.

    mean's internal n never reaches variance, so variance must source its
    own - and the n reaching combine must be the one from its own sum_core.
    """
    calls = []

    def fake(sk, p, config, buses, on_result, **kw):
        calls.append((sk.name, p))
        if hasattr(sk, "plan"):
            dispatch.run_plan(sk, p, config, buses, on_result, skills, depth=1)
            return
        on_result({"agree_representation": {"status": "ok", "result": ["a"]},
                   "sum_core": {"status": "ok", "result": [10.0], "n": 42},
                   "combine": {"status": "ok", "result": [1.0]}}[sk.name])

    monkeypatch.setattr(dispatch, "run_skill", fake)
    dispatch.run_plan(skills["variance"], {}, None, None, lambda r: None, skills)
    outer_combine = [p for n, p in calls if n == "combine"][-1]
    assert outer_combine["variables"]["n"] == 42
    assert "mean" in outer_combine["variables"]


def test_a_compound_is_never_dispatched_to_a_worker(skills):
    """
    contribute/coordinate must raise, loudly, naming the routing bug.

    Reaching them means run_skill resolved workers for a compound - which no
    worker advertises - so the branch was taken too late.
    """
    with pytest.raises(RuntimeError, match="compound skill"):
        skills["sum"].contribute(None, {})
    with pytest.raises(RuntimeError, match="compound skill"):
        skills["variance"].coordinate(None, {}, [])


def test_converse_reaches_a_compound_skill(monkeypatch):
    """
    The regression guard for a bug that left the whole feature inert.

    `converse` once called `run_skill` without `skills`, so every compound
    hit the "no skill registry" guard and returned an error. The model, on
    seeing a failed tool call, silently composed the result by hand instead
    - correctly on one run and wrongly on the next. Every plan test passed
    throughout, because they call `run_plan` directly and never traverse
    `converse`.

    This asserts the argument survives the whole call path, which is the
    only thing that distinguishes a working compound from an inert one.
    """
    from scarlet_agentic_harness import head as head_mod

    seen = {}

    def fake_run_skill(skill, params, config, buses, on_result, **kw):
        seen["skill"] = skill.name
        seen["skills_passed"] = kw.get("skills") is not None
        on_result({"status": "ok", "result": [1.0], "n": 1})

    monkeypatch.setattr(head_mod, "run_skill", fake_run_skill)

    from tests.fakes import ScriptedLLMClient, assistant_tool_call, assistant_final
    from scarlet_agentic_harness.config import HarnessConfig
    from scarlet_agentic_harness.skills.registry import discover_skills

    # from_env requires these; converse never touches a bus here because
    # run_skill is stubbed out above.
    monkeypatch.setenv("ROLE", "head")
    monkeypatch.setenv("APP_ID", "test-head")

    skills = discover_skills()
    llm = ScriptedLLMClient([
        assistant_tool_call("c1", "variance", {"objective": "anything"}),
        assistant_final("done"),
    ])

    done, box = __import__("threading").Event(), {}
    head_mod.converse(
        "what is the variance", HarnessConfig.from_env(), None, skills, llm,
        lambda result, exc: (box.update({"r": result, "e": exc}), done.set()),
    )
    done.wait(timeout=10)

    assert seen.get("skill") == "variance", "converse must dispatch the compound"
    assert seen["skills_passed"], (
        "converse must pass `skills` to run_skill, or every compound errors "
        "and the model silently composes the answer by hand"
    )
