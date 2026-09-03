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
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise SafeEvalError(f"not a valid expression: {exc}") from exc
    return _eval_node(tree.body, variables)


def _eval_node(node: ast.AST, variables: dict) -> float:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        raise SafeEvalError(f"non-numeric constant: {node.value!r}")
    if isinstance(node, ast.Name):
        if node.id not in variables:
            raise SafeEvalError(f"unknown variable: {node.id!r}")
        value = variables[node.id]
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise SafeEvalError(f"variable {node.id!r} is not numeric: {value!r}")
        return value
    if isinstance(node, ast.BinOp):
        op = _BIN_OPS.get(type(node.op))
        if op is None:
            raise SafeEvalError(f"operator not allowed: {type(node.op).__name__}")
        return op(_eval_node(node.left, variables), _eval_node(node.right, variables))
    if isinstance(node, ast.UnaryOp):
        op = _UNARY_OPS.get(type(node.op))
        if op is None:
            raise SafeEvalError(f"unary operator not allowed: {type(node.op).__name__}")
        return op(_eval_node(node.operand, variables))
    raise SafeEvalError(f"expression element not allowed: {type(node).__name__}")
