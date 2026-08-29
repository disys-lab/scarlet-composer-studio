"""
Unit tests for safe_eval - no Redis, no subprocesses. Covers both the
arithmetic it must support (variance's shape specifically, since that's the
motivating case) and everything it must reject: this evaluator runs
model-supplied expressions, so every rejection path matters as much as the
happy path.
"""
import pytest

from scarlet_agentic_harness.skills.safe_eval import SafeEvalError, safe_eval


def test_plain_arithmetic():
    assert safe_eval("1 + 2 * 3", {}) == 7
    assert safe_eval("(1 + 2) * 3", {}) == 9
    assert safe_eval("2 ** 10", {}) == 1024
    assert safe_eval("-5 + 3", {}) == -2
    assert safe_eval("+5", {}) == 5


def test_variables():
    assert safe_eval("s1 / n", {"s1": 45.0, "n": 9}) == 5.0


def test_variance_shape():
    # The motivating expression: variance from S1=sum(x), S2=sum(x^2), n.
    s1, s2, n = 45.0, 285.0, 9
    result = safe_eval("s2/n - (s1/n)**2", {"s1": s1, "s2": s2, "n": n})
    import statistics
    all_numbers = [5.0, 1.0, 9.0, 3.0, 8.0, 2.0, 7.0, 4.0, 6.0]
    assert abs(result - statistics.pvariance(all_numbers)) < 1e-9


def test_unknown_variable_rejected():
    with pytest.raises(SafeEvalError):
        safe_eval("s1 + mystery", {"s1": 1.0})


def test_non_numeric_variable_rejected():
    with pytest.raises(SafeEvalError):
        safe_eval("s1 + 1", {"s1": "not a number"})


def test_string_constant_rejected():
    with pytest.raises(SafeEvalError):
        safe_eval("'hello'", {})


def test_function_call_rejected():
    with pytest.raises(SafeEvalError):
        safe_eval("abs(-1)", {})


def test_attribute_access_rejected():
    with pytest.raises(SafeEvalError):
        safe_eval("s1.__class__", {"s1": 1.0})


def test_subscript_rejected():
    with pytest.raises(SafeEvalError):
        safe_eval("s1[0]", {"s1": [1, 2, 3]})


def test_comparison_rejected():
    with pytest.raises(SafeEvalError):
        safe_eval("s1 > 0", {"s1": 1.0})


def test_boolop_rejected():
    with pytest.raises(SafeEvalError):
        safe_eval("s1 and s2", {"s1": 1.0, "s2": 2.0})


def test_import_like_syntax_rejected():
    with pytest.raises(SafeEvalError):
        safe_eval("__import__('os')", {})


def test_invalid_syntax_rejected():
    with pytest.raises(SafeEvalError):
        safe_eval("1 + ", {})
