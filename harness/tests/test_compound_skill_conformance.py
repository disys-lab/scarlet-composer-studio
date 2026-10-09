"""
Conformance checks that run against EVERY registered compound skill.

These exist because prose does not bind. Each rule below is written in
docs/AGENTS.md, and each has still been violated by a contribution that
looked correct and passed its own tests - because a plan's own tests mock
dispatch, so nothing in them ever evaluates an expression or compares two
steps.

Any new compound skill is checked by these automatically. There is nothing
to wire up; the registry finds it.
"""
import ast

import pytest

from scarlet_agentic_harness.skills.registry import discover_skills
from scarlet_agentic_harness.skills.compound_skill import CompoundSkill
from scarlet_agentic_harness.skills.safe_eval import _BIN_OPS, _UNARY_OPS


def _compounds():
    return {n: s for n, s in discover_skills().items()
            if isinstance(s, CompoundSkill)}


def _ids(d):
    return sorted(d)


# The grammar safe_eval accepts, derived from its own tables so this stays
# in sync when an operator is added there. Checked statically: whether an
# expression is inside the grammar has nothing to do with the values its
# names happen to take.
_ALLOWED_NODES = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Name,
                  ast.Constant, ast.Load)
_ALLOWED_OPS = tuple(_BIN_OPS) + tuple(_UNARY_OPS)


@pytest.mark.parametrize("name", _ids(_compounds()))
def test_every_combine_expression_is_within_the_grammar(name):
    """
    `combine` is arithmetic only - no function calls at all.

    A generated t_test used `sqrt(...)`, which the guide forbids in two
    places. Its own tests passed, because they stub run_skill and the
    expression is never evaluated. The skill could not run at all:
    "expression element not allowed: Call".
    """
    skill = _compounds()[name]
    for i, step in enumerate(skill.plan):
        if step.skill != "combine":
            continue
        expr = (step.params or {}).get("expression")
        assert expr, f"{name} step {i}: combine with no expression"

        try:
            tree = ast.parse(expr, mode="eval")
        except SyntaxError as exc:
            pytest.fail(f"{name} step {i}: expression does not parse - {exc}")

        for node in ast.walk(tree):
            if isinstance(node, _ALLOWED_OPS):
                continue
            if isinstance(node, ast.Constant) and \
                    not isinstance(node.value, (int, float)):
                pytest.fail(
                    f"{name} step {i}: non-numeric constant "
                    f"{node.value!r} in {expr!r}")
            if not isinstance(node, _ALLOWED_NODES):
                pytest.fail(
                    f"{name} step {i}: {type(node).__name__} is not allowed "
                    f"in a combine expression ({expr!r}). combine supports "
                    f"+ - * / ** only; there is no sqrt (write x**0.5) and "
                    f"no function calls of any kind.")


@pytest.mark.parametrize("name", _ids(_compounds()))
def test_every_combine_expression_only_uses_names_the_step_binds(name):
    """
    A name the step does not bind is "unknown variable" at run time.

    Static, like the grammar check above - and the other half of it. An
    expression can be perfectly legal arithmetic and still fail on the
    first dispatch because `variables` is missing a key.
    """
    skill = _compounds()[name]
    for i, step in enumerate(skill.plan):
        if step.skill != "combine":
            continue
        params = step.params or {}
        expr = params.get("expression", "")
        bound = set(params.get("variables") or {})
        used = {n.id for n in ast.walk(ast.parse(expr, mode="eval"))
                if isinstance(n, ast.Name)}
        missing = used - bound
        assert not missing, (
            f"{name} step {i}: {expr!r} uses {sorted(missing)}, which the "
            f"step's `variables` does not bind. At run time that is "
            f"\"unknown variable\" and the plan aborts.")


@pytest.mark.parametrize("name", _ids(_compounds()))
def test_no_two_steps_are_identical(name):
    """
    Two identical steps compute the same thing twice.

    A generated f_test declared a `group_column` parameter and then wrote
    two byte-identical `mean` steps. Both aggregated the whole fleet, so
    the ratio was exactly 1.0 for any input - it dispatched, returned, and
    looked entirely plausible.
    """
    skill = _compounds()[name]
    seen = {}
    for i, step in enumerate(skill.plan):
        key = (step.skill, repr(sorted((step.params or {}).items())))
        if key in seen:
            pytest.fail(
                f"{name}: steps {seen[key]} and {i} are identical "
                f"({step.skill} with the same params), so they compute the "
                f"same value. If they are meant to differ, each must say how "
                f"- narrow with `workers` or `conditions` in the step's own "
                f"params.")
        seen[key] = i


@pytest.mark.parametrize("name", _ids(_compounds()))
def test_every_declared_parameter_is_consumed(name):
    """
    A parameter no step references does nothing.

    `group_column` was declared, documented, required - and read by
    nothing. The plan ignored it silently.

    `objective`, `columns`, `conditions` and `workers` are exempt: the plan
    runner spreads them into every step automatically.
    """
    registry = discover_skills()
    skill = _compounds()[name]
    declared = set(skill.parameters.get("properties", {}))
    if not declared:
        return

    # Consumed either explicitly, as "$name" somewhere in a step's params...
    referenced = set()
    for step in skill.plan:
        for value in _walk(step.params or {}):
            if isinstance(value, str) and value.startswith("$"):
                referenced.add(value[1:])

    # ...or implicitly: the plan runner spreads the compound's params into
    # every step, so a name a step already accepts is consumed without any
    # "$" reference. `transform` reaches sum_core exactly this way.
    for step in skill.plan:
        target = registry.get(step.skill)
        if target is not None:
            referenced |= set(target.parameters.get("properties", {}))

    unused = declared - referenced
    assert not unused, (
        f"{name} declares {sorted(unused)} but no step references "
        f"{'it' if len(unused) == 1 else 'them'} as $name, and no step in "
        f"the plan accepts {'that name' if len(unused) == 1 else 'those names'} "
        f"either. A declared parameter that nothing consumes is silently "
        f"ignored - that is how an f_test ended up with a `group_column` "
        f"it never used.")


def _walk(value):
    """Yield every leaf in a nested dict/list."""
    if isinstance(value, dict):
        for v in value.values():
            yield from _walk(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _walk(v)
    else:
        yield value


@pytest.mark.parametrize("name", _ids(_compounds()))
def test_returns_re_exports_something(name):
    """A compound that returns nothing cannot be composed with."""
    skill = _compounds()[name]
    assert skill.returns, f"{name} declares no `returns`"


@pytest.mark.parametrize("name", _ids(_compounds()))
def test_a_skill_promising_a_p_value_computes_one(name):
    """
    If the description advertises a p-value, the plan must produce one.

    A generated t_test promised "the t statistic and its two-sided
    p-value" and had no `distribution` step at all - so the p-value it
    advertised to the head did not exist.
    """
    skill = _compounds()[name]
    if "p-value" not in skill.description.lower() and \
       "p_value" not in skill.description.lower():
        return
    assert any(step.skill == "distribution" for step in skill.plan), (
        f"{name}'s description promises a p-value but its plan has no "
        f"`distribution` step, so no p-value is ever computed.")
    assert any("p" in field.lower() for field in skill.returns), (
        f"{name} computes a p-value but does not re-export it in `returns`.")


# Distributions that are symmetric about zero, so a statistic drawn from
# one can be negative. chi2 and f cannot be, which is why doubling their
# upper tail is a different conversation.
_SYMMETRIC = {"norm", "t"}


@pytest.mark.parametrize("name", _ids(_compounds()))
def test_a_doubled_upper_tail_is_fed_an_absolute_value(name):
    """
    `sf` is the UPPER tail only, so 2*sf(x) needs |x|, not x.

    Observed in a generated t_test: for t = -0.31, sf(-0.31) is 0.62 and
    the plan reported a "p-value" of 1.75. Nothing raised - it is ordinary
    arithmetic on a real number, and the skill's own tests stubbed
    `combine` so no value was ever computed. Only a statistic that came
    out negative showed it, and the happy-path fixture had a positive one.

    There is no abs() in combine, so the absolute value is written
    (x**2)**0.5 - a Pow by 0.5 at the top of the expression.
    """
    skill = _compounds()[name]
    produced_by = {}
    for step in skill.plan:
        for local in (step.produces or {}):
            produced_by[local] = step

    for i, step in enumerate(skill.plan):
        if step.skill != "distribution":
            continue
        params = step.params or {}
        if params.get("method") != "sf" or params.get("dist") not in _SYMMETRIC:
            continue

        # Is this sf's result doubled anywhere later in the plan?
        tail = {local for local, src in (step.produces or {}).items()}
        doubled = False
        for later in skill.plan:
            if later.skill != "combine":
                continue
            expr = (later.params or {}).get("expression", "")
            names = {n.id for n in ast.walk(ast.parse(expr, mode="eval"))
                     if isinstance(n, ast.Name)}
            bound = later.params.get("variables") or {}
            source = {str(v).lstrip("$") for v in bound.values()}
            if "2" in expr.replace(" ", "") and (names & bound.keys()) and \
                    (source & tail):
                doubled = True
        if not doubled:
            continue

        x = params.get("x")
        if not (isinstance(x, str) and x.startswith("$")):
            continue
        src = produced_by.get(x[1:])
        expr = (src.params or {}).get("expression", "") if src else ""
        ok = False
        if expr:
            top = ast.parse(expr, mode="eval").body
            ok = (isinstance(top, ast.BinOp) and isinstance(top.op, ast.Pow)
                  and isinstance(top.right, ast.Constant)
                  and float(top.right.value) == 0.5)
        assert ok, (
            f"{name} step {i}: the plan doubles sf({x}) to get a two-sided "
            f"p-value, but {x} is not an absolute value - it comes from "
            f"{expr!r}. {params['dist']} is symmetric, so the statistic can "
            f"be negative, and sf of a negative number is above 0.5: "
            f"doubling it gives a 'p-value' greater than 1. Take the "
            f"magnitude first with a combine step ({x[1:]}**2)**0.5 - there "
            f"is no abs() in combine.")


# Steps that reduce over the fleet. A plan containing one of these is
# answering "over which workers?" whether or not it says so.
_AGGREGATING = {"sum_core", "sum", "mean", "median", "variance"}


@pytest.mark.parametrize("name", _ids(_compounds()))
def test_an_aggregating_skill_can_be_scoped_to_workers(name):
    """
    A skill that reduces over the fleet must declare `workers`.

    Propagation into steps is automatic, but the head never sends a
    parameter the schema does not mention - so without it, "run a z-test
    on worker1's data" silently returns the answer for every worker and
    nothing anywhere reports a problem.

    Measured live, before this check existed: asked for a z-test on
    worker1, `z_test` returned n=387 - the whole fleet - and z=0.888471
    instead of worker1's 0.746779. The conclusion happened to be the same,
    which is exactly why it survived.

    A plan that sets `workers` itself on every aggregating step (f_test,
    which compares two named groups) is scoped by construction and does
    not need the top-level parameter.
    """
    skill = _compounds()[name]
    aggregating = [s for s in skill.plan if s.skill in _AGGREGATING]
    if not aggregating:
        return
    if all("workers" in (s.params or {}) for s in aggregating):
        return  # scoped per step, like f_test's two groups

    assert "workers" in skill.parameters.get("properties", {}), (
        f"{name} aggregates over the fleet ("
        f"{', '.join(sorted({s.skill for s in aggregating}))}) but does not "
        f"declare a `workers` parameter, so the head cannot scope it. A "
        f"question about one worker will silently get the fleet-wide "
        f"answer. Add workers to `parameters`; propagation into the steps "
        f"is automatic.")


@pytest.mark.parametrize("name", _ids(_compounds()))
def test_an_aggregating_skill_can_be_filtered(name):
    """Same argument for `conditions` - AGENTS.md calls this one out too."""
    skill = _compounds()[name]
    if not any(s.skill in _AGGREGATING for s in skill.plan):
        return
    assert "conditions" in skill.parameters.get("properties", {}), (
        f"{name} aggregates but does not declare `conditions`, so a "
        f"filtered question silently returns the unfiltered answer.")


@pytest.mark.parametrize("name", _ids(_compounds()))
def test_a_hypothesis_test_returns_both_a_statistic_and_a_p_value(name):
    """
    Anything named `*_test` must return the statistic AND its p-value.

    A statistic on its own is not an answer to "is this significant?" -
    somebody still has to turn it into a probability, and the only
    sanctioned way to do that is the `distribution` skill. When the skill
    does not, the head has to notice and make a second call, and it does
    so inconsistently: measured live, "run a z test on vibration_rms"
    returned a bare z and stopped, and only an explicit "give me the
    p-value" produced one. Worse, when the head tries to fill the gap
    itself it has been seen estimating a tail from memory ("the
    standardized z-score is approximately -4.444, so P(Z > -4.444) is
    approximately 1").

    `p_value` is the required name. One-sided tests may also re-export
    `p_one_sided`/`p_upper`/`p_lower`, but the headline field a caller
    composes against has to be predictable.
    """
    if not name.endswith("_test"):
        return
    skill = _compounds()[name]

    assert any(step.skill == "distribution" for step in skill.plan), (
        f"{name} is a hypothesis test but its plan has no `distribution` "
        f"step, so it returns a statistic nobody can interpret. Add one; "
        f"see t_test for a two-sided p-value and chi2_test for a "
        f"one-sided one.")
    assert "p_value" in skill.returns, (
        f"{name} computes a p-value but does not re-export it as "
        f"`p_value` (returns: {sorted(skill.returns)}). Callers and the "
        f"head both look for that exact name.")
    assert "result" in skill.returns, (
        f"{name} must also re-export the statistic itself as `result`.")
