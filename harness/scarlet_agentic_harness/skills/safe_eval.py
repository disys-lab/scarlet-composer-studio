"""
safe_eval — restricted arithmetic expression evaluator for CombineSkill.

CombineSkill lets the head's LLM request a numeric expression (e.g.
"s2/n - (s1/n)**2" for variance) evaluated against a set of named variables,
almost always outputs from earlier skill invocations (sum's `result`/`n`,
etc.). That expression comes from the model, not a trusted operator, and it
runs on a worker (see combine.py - "head never computes" is a hard
constraint here) - so this can't just be Python's eval() with a restricted
namespace. A restricted *namespace* still lets eval() reach __builtins__,
attribute access, comprehensions, and everything else Python's grammar
allows; the globals/locals dicts alone don't guard against that.

This instead walks the parsed AST and allow-lists exactly the node types a
plain arithmetic expression needs: numeric constants, variable lookups,
binary operators (+ - * / **), and unary +/-. Anything else - function
calls, attribute access, subscripting, comparisons, boolean ops, imports,
comprehensions, string constants - raises SafeEvalError before any code
runs, not caught after the fact.
"""
import ast

import numpy as np
import operator

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
}
_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


class SafeEvalError(ValueError):
    """Raised for any expression (or sub-expression) outside the allowed
    numeric-arithmetic grammar - an unrecognized node is always rejected,
    never silently passed through."""


def safe_eval(expression: str, variables: dict) -> float:
    """
    Evaluate a restricted arithmetic expression.

    Walks the parsed AST and allow-lists exactly the node types a plain
    arithmetic expression needs: numeric constants, variable lookups,
    binary operators (``+ - * / **``), and unary ``+``/``-``. Anything
    else - function calls, attribute access, subscripting, comparisons,
    boolean ops, imports, comprehensions, string constants - raises
    before any code runs, not caught after the fact. Not `eval` with a
    restricted namespace: a restricted namespace alone doesn't stop
    `eval` from reaching `__builtins__`, attribute access, or
    comprehensions.

    Parameters
    ----------
    expression : str
        e.g. ``"s2/n - (s1/n)**2"``.
    variables : dict
        Name -> numeric value bindings referenced by `expression`.

    Returns
    -------
    float

    Raises
    ------
    SafeEvalError
        If `expression` doesn't parse, or contains anything outside the
        allowed grammar, or references an unknown/non-numeric variable.
    """
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise SafeEvalError(f"not a valid expression: {exc}") from exc
    result = _eval_node(tree.body, variables)

    # A non-finite result never leaves this function.
    #
    # Row filtering made n=0 reachable: a window no worker has rows for
    # gives sum=0 and n=0, so `mean = s1/n` is NaN. That NaN is unsendable,
    # not just wrong - `json` writes it as a bare NaN literal, which is not
    # valid JSON. Observed: one stored message broke the composer's
    # /api/conversations with a 500, hiding every conversation on every bus.
    #
    # Failing here keeps the cause legible instead of surfacing several
    # hops away as a blank screen.
    finite = np.isfinite(np.asarray(result, dtype=float))
    if not np.all(finite):
        zeroed = [name for name, value in variables.items()
                  if isinstance(value, (int, float)) and value == 0]
        hint = (f" - {', '.join(zeroed)} is zero, so this is a division by "
                f"zero; if that is a row count, no worker matched the filter"
                if zeroed else "")
        raise SafeEvalError(
            f"expression {expression!r} produced a non-finite result{hint}")

    # Hand back a plain list, not an ndarray: the result crosses a bus as
    # JSON, and a scalar expression must still return a scalar so every
    # existing caller is unaffected.
    if isinstance(result, np.ndarray):
        return result.tolist()
    return result


def _eval_node(node: ast.AST, variables: dict) -> float:
    """
    Recursively evaluate one AST node under the same allow-list `safe_eval` documents.

    Parameters
    ----------
    node : ast.AST
    variables : dict

    Returns
    -------
    float

    Raises
    ------
    SafeEvalError
        If `node` (or any sub-node) is outside the allowed grammar.
    """
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        raise SafeEvalError(f"non-numeric constant: {node.value!r}")
    if isinstance(node, ast.Name):
        if node.id not in variables:
            raise SafeEvalError(f"unknown variable: {node.id!r}")
        return _coerce(node.id, variables[node.id])
    if isinstance(node, ast.BinOp):
        op = _BIN_OPS.get(type(node.op))
        if op is None:
            raise SafeEvalError(f"operator not allowed: {type(node.op).__name__}")
        left = _eval_node(node.left, variables)
        right = _eval_node(node.right, variables)
        _check_shapes(left, right, type(node.op).__name__)
        return op(left, right)
    if isinstance(node, ast.UnaryOp):
        op = _UNARY_OPS.get(type(node.op))
        if op is None:
            raise SafeEvalError(f"unary operator not allowed: {type(node.op).__name__}")
        return op(_eval_node(node.operand, variables))
    raise SafeEvalError(f"expression element not allowed: {type(node).__name__}")


def _coerce(name: str, value):
    """
    Accept a number or a flat sequence of numbers; reject everything else.

    A list becomes a numpy array so the existing operators broadcast
    elementwise with no change to `_BIN_OPS` - operator.add and friends
    already do the right thing on ndarrays. Booleans stay rejected: bool is
    a subclass of int, so `True + 1` would otherwise evaluate silently.
    """
    if isinstance(value, bool):
        raise SafeEvalError(f"variable {name!r} is not numeric: {value!r}")
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, np.ndarray):
        return value
    if isinstance(value, (list, tuple)):
        if not value:
            raise SafeEvalError(f"variable {name!r} is an empty sequence")
        for item in value:
            if isinstance(item, bool) or not isinstance(item, (int, float)):
                raise SafeEvalError(
                    f"variable {name!r} contains a non-numeric element: {item!r}")
        return np.asarray(value, dtype=float)
    raise SafeEvalError(f"variable {name!r} is not numeric: {value!r}")


def _check_shapes(left, right, op_name: str) -> None:
    """
    Reject mismatched vector lengths with a message that says what is wrong.

    numpy would raise "operands could not be broadcast together with shapes
    (3,) (5,)", which is accurate and tells a caller nothing about which
    quantities disagreed. A scalar against a vector is fine and deliberate -
    that is how `s1/n` works when s1 is per-column and n is one count.
    """
    l_vec = isinstance(left, np.ndarray)
    r_vec = isinstance(right, np.ndarray)
    if l_vec and r_vec and left.shape != right.shape:
        raise SafeEvalError(
            f"cannot apply {op_name} to vectors of different length: "
            f"{left.shape[0]} and {right.shape[0]} - the quantities being combined "
            f"do not describe the same set of columns")
