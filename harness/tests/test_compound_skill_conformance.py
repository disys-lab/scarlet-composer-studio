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
from scarlet_agentic_harness.skills.safe_eval import _BIN_OPS, _UNARY_OPS, safe_eval


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

    # ...or as the subject of a RULE 0 condition. `mode` is consumed this
    # way in every hypothesis test: no step takes it as a parameter, it
    # selects which branch runs.
    for step in skill.plan:
        referenced |= set(step.when or {})

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


@pytest.mark.parametrize("name", _ids(_compounds()))
def test_each_tail_branch_computes_the_right_probability(name):
    """
    Evaluate each mode's expression and check it against the tail it claims.

    Replaces an earlier string-matching rule that looked for a doubled
    `sf` fed a non-absolute statistic. That bug is now impossible by
    construction - the two-sided branch uses 1 - |2u - 1|, which is
    correct for a statistic of either sign - but the branches could still
    be wired to the wrong formula, so this checks the arithmetic instead
    of the shape.

    With u = the upper-tail probability:
        upper      -> u
        lower      -> 1 - u
        two-sided  -> 2*min(u, 1-u)
    """
    if not name.endswith("_test"):
        return
    skill = _compounds()[name]
    expected = {
        "upper": lambda u: u,
        "lower": lambda u: 1.0 - u,
        "two-sided": lambda u: 2 * min(u, 1.0 - u),
    }
    for step in skill.plan:
        if "p_value" not in (step.produces or {}):
            continue
        mode = step.when["mode"]
        mode = mode[0] if isinstance(mode, (list, tuple)) else mode
        expr = step.params["expression"]
        for u in (0.001, 0.05, 0.25, 0.5, 0.75, 0.95, 0.999):
            got = safe_eval(expr, {"p_upper": u})
            want = expected[mode](u)
            assert abs(got - want) < 1e-12, (
                f"{name}, mode={mode}: {expr!r} gives {got} at "
                f"p_upper={u}, expected {want}.")
            assert 0.0 <= got <= 1.0, (
                f"{name}, mode={mode}: {expr!r} returned {got} at "
                f"p_upper={u}, which is not a probability.")


_MODES = ("two-sided", "upper", "lower")


@pytest.mark.parametrize("name", _ids(_compounds()))
def test_a_hypothesis_test_supports_all_three_tails(name):
    """
    `*_test` skills must offer two-sided, upper and lower alternatives.

    A test that hard-codes one tail answers a different question from the
    one asked, and does it silently: a two-sided p-value used for "is the
    variance greater than 1?" is twice what it should be, and an upper
    tail used for "do these differ?" is half. Both look like plausible
    probabilities.

    The implementation is a `mode` parameter and three mutually exclusive
    RULE 0 branches binding `p_value`. See any of the tests here - the
    block is deliberately identical in all of them.
    """
    if not name.endswith("_test"):
        return
    skill = _compounds()[name]

    spec = skill.parameters.get("properties", {}).get("mode")
    assert spec, (
        f"{name} declares no `mode` parameter, so the head cannot ask for "
        f"a one-sided alternative.")
    assert set(spec.get("enum", [])) == set(_MODES), (
        f"{name}'s mode enum is {spec.get('enum')}; it must offer exactly "
        f"{list(_MODES)}.")
    assert spec.get("default") == "two-sided", (
        f"{name} must default to two-sided - an omitted mode that silently "
        f"picks a single tail halves or doubles the p-value.")

    # One branch per mode, each binding p_value, each mutually exclusive.
    binders = [s for s in skill.plan if "p_value" in (s.produces or {})]
    assert len(binders) == len(_MODES), (
        f"{name} has {len(binders)} steps binding `p_value`; expected one "
        f"per mode ({len(_MODES)}).")
    claimed = set()
    for s in binders:
        assert s.when, (
            f"{name}: a step binding `p_value` has no `when`, so it runs in "
            f"every mode and the first one always wins.")
        assert "mode" in s.when, f"{name}: p_value branch not keyed on `mode`"
        v = s.when["mode"]
        claimed |= set(v) if isinstance(v, (list, tuple, set)) else {v}
    assert claimed == set(_MODES), (
        f"{name} covers modes {sorted(claimed)}; expected {list(_MODES)}.")
