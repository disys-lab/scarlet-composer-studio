"""
safe_eval with vectors.

combine is the only way a plan turns sums into a mean or a variance, and
since Sprint 2 those sums are per-column lists. Scalar behaviour must be
untouched: 06/07/08 compose variance through combine with plain numbers and
are the regression guard for that.
"""
import pytest

from scarlet_agentic_harness.skills.safe_eval import SafeEvalError, safe_eval


# ── scalars still behave exactly as before ───────────────────────────────

def test_scalar_arithmetic_is_unchanged():
    assert safe_eval("s2/n - (s1/n)**2", {"s1": 100.0, "s2": 2600.0, "n": 10}) == 160.0


def test_a_scalar_expression_returns_a_scalar_not_a_list():
    out = safe_eval("a+b", {"a": 1, "b": 2})
    assert out == 3 and not isinstance(out, list)


def test_booleans_are_still_rejected():
    """bool subclasses int, so True+1 would evaluate silently."""
    with pytest.raises(SafeEvalError, match="not numeric"):
        safe_eval("a+1", {"a": True})


# ── vectors ──────────────────────────────────────────────────────────────

def test_two_vectors_combine_elementwise():
    assert safe_eval("a+b", {"a": [1, 2, 3], "b": [10, 20, 30]}) == [11.0, 22.0, 33.0]


def test_a_scalar_broadcasts_against_a_vector():
    """This is how s1/n works: per-column sums over one shared count."""
    assert safe_eval("s1/n", {"s1": [10, 20, 30], "n": 10}) == [1.0, 2.0, 3.0]


def test_per_column_variance_the_way_a_plan_will_call_it():
    s1, s2, n = [10.0, 20.0], [60.0, 220.0], 2
    out = safe_eval("s2/n - (s1/n)**2", {"s1": s1, "s2": s2, "n": n})
    assert out == [5.0, 10.0]


def test_a_vector_result_comes_back_as_a_plain_list():
    """It crosses a bus as JSON; an ndarray would not serialise."""
    out = safe_eval("a*2", {"a": [1, 2]})
    assert isinstance(out, list) and out == [2.0, 4.0]


# ── the error that numpy would otherwise make unhelpful ──────────────────

def test_mismatched_vector_lengths_say_what_is_wrong():
    with pytest.raises(SafeEvalError) as e:
        safe_eval("a+b", {"a": [1, 2, 3], "b": [1, 2]})
    msg = str(e.value)
    assert "3" in msg and "2" in msg
    assert "same set of columns" in msg, "must explain, not just report shapes"


def test_a_non_numeric_element_is_caught_by_name():
    with pytest.raises(SafeEvalError, match="non-numeric element"):
        safe_eval("a+1", {"a": [1, "x"]})


def test_an_empty_vector_is_an_error_not_a_silent_nothing():
    with pytest.raises(SafeEvalError, match="empty sequence"):
        safe_eval("a+1", {"a": []})


def test_a_boolean_inside_a_vector_is_rejected():
    with pytest.raises(SafeEvalError, match="non-numeric element"):
        safe_eval("a+1", {"a": [1, True]})


# --- non-finite results must never cross the bus ----------------------------

def test_division_by_a_zero_row_count_is_an_error_not_a_nan():
    """
    The bug that hid every conversation in the composer UI.

    Row filtering made n=0 reachable: a window no worker has rows for
    gives sum=0 and n=0, and mean = s1/n is 0/0 = NaN. `json` writes that
    as a bare `NaN` literal, which is not valid JSON - the composer's
    /api/conversations endpoint 500'd on it and the UI showed nothing at
    all, for every bus, because one stored message could not be
    serialised.
    """
    from scarlet_agentic_harness.skills.safe_eval import safe_eval, SafeEvalError

    with pytest.raises(SafeEvalError, match="non-finite"):
        safe_eval("s1/n", {"s1": [0.0, 0.0, 0.0], "n": 0})


def test_the_error_names_the_zero_variable():
    """The message has to say which quantity was zero, or it is a puzzle."""
    from scarlet_agentic_harness.skills.safe_eval import safe_eval, SafeEvalError

    with pytest.raises(SafeEvalError, match="n is zero"):
        safe_eval("s2/n - mean**2", {"s2": [0.0], "n": 0, "mean": [0.0]})


def test_the_variance_expression_with_real_counts_still_works():
    """Regression guard: the ordinary path is untouched."""
    from scarlet_agentic_harness.skills.safe_eval import safe_eval

    out = safe_eval("s2/n - mean**2",
                    {"s2": [200.0, 800.0], "n": 2, "mean": [10.0, 20.0]})
    assert out == [0.0, 0.0]
