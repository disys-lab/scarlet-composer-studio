"""Tests for predicate and temporal detection in the scarlet_agentic_harness.

The two pieces tested here are:
- build_where: constructs SQL WHERE clauses from predicate conditions
- _temporal_format: detects whether a column contains ISO or native datetime values

The US-format case ("03/01/2025") matters because string comparison of such
dates yields incorrect ordering (e.g., "03/01/2025" >= "01/15/2026" is True),
so returning None prevents incorrect sorting or filtering.
"""

from datetime import datetime, date

import pytest

from scarlet_agentic_harness.skills.predicate import build_where, OPS
from scarlet_agentic_harness.data_profile import _temporal_format


# Fixture matching the context file's PROFILE structure
PROFILE = {
    "columns": [
        {"name": "power_kw", "numeric": True, "temporal": False},
        {"name": "ts", "numeric": False, "temporal": True},
        {"name": "status", "numeric": False, "temporal": False},
        {"name": 'we"ird', "numeric": True, "temporal": False},
    ],
    "numeric_columns": ["power_kw", 'we"ird'],
    "temporal_columns": ["ts"],
}


def test_empty_list_returns_empty_string():
    """Empty list of conditions returns empty string."""
    assert build_where([], PROFILE) == ""


def test_none_returns_empty_string():
    """None conditions returns empty string."""
    assert build_where(None, PROFILE) == ""


def test_numeric_gt_condition():
    """A numeric condition renders as '"power_kw" > 30.0'."""
    result = build_where([{"column": "power_kw", "op": "gt", "value": 30}], PROFILE)
    assert result == ' WHERE "power_kw" > 30.0'


def test_two_conditions_joined_with_and():
    """Two conditions join with AND, in the order given."""
    result = build_where([
        {"column": "ts", "op": "gte", "value": "2026-01-01T00:00:00"},
        {"column": "ts", "op": "lt", "value": "2026-02-01T00:00:00"}
    ], PROFILE)
    assert result == (
        ' WHERE CAST("ts" AS TIMESTAMP) >= TIMESTAMP \'2026-01-01 00:00:00\''
        ' AND CAST("ts" AS TIMESTAMP) < TIMESTAMP \'2026-02-01 00:00:00\''
    )


def test_trailing_Z_on_timestamp():
    """A trailing "Z" on a timestamp is accepted."""
    result = build_where(
        [{"column": "ts", "op": "gte", "value": "2026-01-01T00:00:00Z"}], PROFILE
    )
    assert result == ' WHERE CAST("ts" AS TIMESTAMP) >= TIMESTAMP \'2026-01-01 00:00:00+00:00\''
    # Note: The context file expects this exact format


def test_single_quotes_in_text_value():
    """Single quotes in a text value are doubled."""
    result = build_where(
        [{"column": "status", "op": "eq", "value": "it's on"}], PROFILE
    )
    assert result == " WHERE \"status\" = 'it''s on'"


def test_column_name_with_double_quote():
    """A column name containing a double quote has it doubled in the identifier."""
    result = build_where(
        [{"column": 'we"ird', "op": "ne", "value": 1}], PROFILE
    )
    assert result == ' WHERE "we""ird" != 1.0'


def test_ops_contains_exactly_six_operators():
    """OPS holds exactly gt, gte, lt, lte, eq, ne."""
    assert sorted(OPS) == sorted(["gt", "gte", "lt", "lte", "eq", "ne"])


def test_unknown_operator_raises_valueerror():
    """An unknown operator raises ValueError naming the operator."""
    with pytest.raises(ValueError, match="like"):
        build_where(
            [{"column": "power_kw", "op": "like", "value": 1}], PROFILE
        )


def test_missing_column_raises_valueerror():
    """A column absent from the profile raises ValueError with 'does not have column'."""
    with pytest.raises(ValueError, match="does not have column"):
        build_where(
            [{"column": "nope", "op": "gt", "value": 1}], PROFILE
        )


def test_non_iso_timestamp_raises_valueerror():
    """A non-ISO timestamp such as "03/01/2025" raises ValueError."""
    with pytest.raises(ValueError):
        build_where(
            [{"column": "ts", "op": "gte", "value": "03/01/2025"}], PROFILE
        )


def test_non_numeric_value_for_numeric_column_raises_valueerror():
    """A non-numeric value for a numeric column raises ValueError."""
    with pytest.raises(ValueError):
        build_where(
            [{"column": "power_kw", "op": "gt", "value": "abc"}], PROFILE
        )


def test_bool_for_numeric_column_raises_valueerror():
    """A bool for a numeric column raises ValueError."""
    with pytest.raises(ValueError):
        build_where(
            [{"column": "power_kw", "op": "eq", "value": True}], PROFILE
        )


# Temporal format tests
def test_iso_strings_return_iso():
    """ISO strings -> "iso"."""
    rows = [["2025-01-01T00:00:00"], ["2025-01-02T00:00:00"]]
    assert _temporal_format(rows, 0) == "iso"


def test_iso_with_trailing_z_return_iso():
    """ISO with a trailing Z -> "iso"."""
    rows = [["2025-01-01T00:00:00Z"]]
    assert _temporal_format(rows, 0) == "iso"


def test_iso_with_space_separator_return_iso():
    """ISO with a space separator instead of T -> "iso"."""
    rows = [["2025-01-01 00:00:00"]]
    assert _temporal_format(rows, 0) == "iso"


def test_datetime_objects_return_native():
    """datetime.datetime objects -> "native"."""
    rows = [[datetime(2025, 1, 1)], [datetime(2025, 1, 2)]]
    assert _temporal_format(rows, 0) == "native"


def test_date_objects_return_native():
    """datetime.date objects -> "native"."""
    rows = [[date(2025, 1, 1)], [date(2025, 1, 2)]]
    assert _temporal_format(rows, 0) == "native"


def test_us_style_date_returns_none():
    """US-style "03/01/2025" -> None."""
    rows = [["03/01/2025"]]
    assert _temporal_format(rows, 0) is None


def test_ordinary_text_returns_none():
    """Ordinary text such as "running" -> None."""
    rows = [["running"]]
    assert _temporal_format(rows, 0) is None


def test_all_none_or_empty_returns_none():
    """All values None or "" -> None."""
    rows = [[None], [""], [None]]
    assert _temporal_format(rows, 0) is None


def test_mixed_string_and_datetime_returns_none():
    """A mix of string and datetime values -> None."""
    rows = [["2025-01-01T00:00:00"], [datetime(2025, 1, 2)]]
    assert _temporal_format(rows, 0) is None


def test_numeric_values_return_none():
    """Numeric values -> None."""
    rows = [[1], [2.5], [3]]
    assert _temporal_format(rows, 0) is None


def test_none_interleaved_with_valid_iso_returns_iso():
    """None values interleaved with valid ISO strings -> "iso" (nulls are skipped)."""
    rows = [["2025-01-01T00:00:00"], [None], ["2025-01-02T00:00:00"], [None]]
    assert _temporal_format(rows, 0) == "iso"


def test_us_format_rejected_and_string_ordering_wrong():
    """US format is rejected because string ordering would be incorrect."""
    # Compared as plain strings, a March 2025 date sorts at or after a
    # January 2026 one - lexicographic order only agrees with chronological
    # order for ISO input. Parenthesised deliberately: written as
    # `a >= b is True` Python chains it into `(a >= b) and (b is True)`,
    # which is always False and asserts nothing about the ordering.
    assert ("03/01/2025" >= "01/15/2026") is True

    # So the column must not be typed temporal at all; the predicate builder
    # then refuses to filter on it rather than emitting that comparison.
    rows = [["03/01/2025"]]
    assert _temporal_format(rows, 0) is None


# --- staggered waits --------------------------------------------------------

def test_staggered_deadline_extends_while_workers_report_in():
    """
    The wait grows when progress happens and not otherwise.

    A flat timeout cannot be both generous enough for the slowest worker
    and short enough to notice a hang; this is what makes it adaptive.
    """
    import time
    from scarlet_agentic_harness.skills.base import Skill

    class _S(Skill):
        name = "s"
        coordinate_timeout = 0.25
        stagger_extension = 0.5
        stagger_ceiling = 10.0

        def contribute(self, ctx, request): pass
        def coordinate(self, ctx, request, workers): return {"status": "ok"}

    still_waiting = _S().staggered_deadline(expected=3)

    # No progress: the base deadline is all we get.
    assert still_waiting(0) is True
    time.sleep(0.3)
    assert still_waiting(0) is False, "a silent fleet must not extend the wait"

    # Progress past the original deadline buys more time.
    still_waiting = _S().staggered_deadline(expected=3)
    time.sleep(0.3)
    assert still_waiting(1) is True, "a worker reporting in should extend the wait"


def test_staggered_deadline_stops_extending_once_everyone_answered():
    """The last arrival must not buy time nobody needs."""
    from scarlet_agentic_harness.skills.base import Skill

    class _S(Skill):
        name = "s"
        coordinate_timeout = 0.05
        stagger_extension = 5.0
        stagger_ceiling = 60.0

        def contribute(self, ctx, request): pass
        def coordinate(self, ctx, request, workers): return {"status": "ok"}

    still_waiting = _S().staggered_deadline(expected=2)
    still_waiting(2)          # everyone is in
    import time; time.sleep(0.1)
    assert still_waiting(2) is False


# --- other connector dialects ----------------------------------------------
#
# Untested against live Influx/PI this sprint by design - these cover the
# rendering only. The point they prove is that a structured condition CAN
# be retargeted; raw SQL from an LLM could not have been.

_DIALECT_PROFILE = {
    "columns": [
        {"name": "ts", "numeric": False, "temporal": True},
        {"name": "power_kw", "numeric": True, "temporal": False},
        {"name": "status", "numeric": False, "temporal": False},
    ],
}

_W = [{"column": "ts", "op": "gte", "value": "2026-01-01T00:00:00"},
      {"column": "ts", "op": "lt", "value": "2026-02-01T00:00:00"}]


def test_flux_puts_the_time_window_in_range_not_filter():
    from scarlet_agentic_harness.skills.predicate import render_flux
    out = render_flux(_W, _DIALECT_PROFILE)
    assert "|> range(start: 2026-01-01T00:00:00, stop: 2026-02-01T00:00:00)" in out
    assert "filter" not in out


def test_flux_puts_a_value_condition_in_filter():
    from scarlet_agentic_harness.skills.predicate import render_flux
    out = render_flux([{"column": "power_kw", "op": "gt", "value": 30}],
                      _DIALECT_PROFILE)
    assert '|> filter(fn: (r) => r["power_kw"] > 30.0)' in out


def test_pi_renders_a_window_as_start_and_end_time():
    from scarlet_agentic_harness.skills.predicate import render_pi
    assert render_pi(_W, _DIALECT_PROFILE) == {
        "start_time": "2026-01-01T00:00:00",
        "end_time": "2026-02-01T00:00:00",
    }


def test_pi_refuses_a_non_time_condition():
    """PI cannot express it, so it must not be silently dropped."""
    from scarlet_agentic_harness.skills.predicate import render_pi
    with pytest.raises(ValueError, match="only be filtered by time"):
        render_pi([{"column": "power_kw", "op": "gt", "value": 30}],
                  _DIALECT_PROFILE)


def test_every_dialect_rejects_an_unknown_column():
    from scarlet_agentic_harness.skills.predicate import render_flux, render_pi
    bad = [{"column": "nope", "op": "gte", "value": "2026-01-01T00:00:00"}]
    for fn in (render_flux, render_pi):
        with pytest.raises(ValueError, match="does not have column"):
            fn(bad, _DIALECT_PROFILE)


def test_empty_conditions_are_a_no_op_in_every_dialect():
    from scarlet_agentic_harness.skills.predicate import render_flux, render_pi
    assert render_flux(None, _DIALECT_PROFILE) == ""
    assert render_pi(None, _DIALECT_PROFILE) == {}


def test_an_early_reply_never_shortens_the_deadline():
    """
    The regression that killed notebooks 13 and 14.

    Written as `min(ceiling, now + extension)`, a worker replying one
    second in pulled a 15-second deadline back to 11 - so the wait expired
    early, the round was retried, and the notebook ran until its cell limit
    killed it. The deadline must only ever move outward.
    """
    import time
    from scarlet_agentic_harness.skills.base import Skill

    class _S(Skill):
        name = "s"
        coordinate_timeout = 2.0
        stagger_extension = 0.1     # far shorter than the base timeout
        stagger_ceiling = 30.0

        def contribute(self, ctx, request): pass
        def coordinate(self, ctx, request, workers): return {"status": "ok"}

    still_waiting = _S().staggered_deadline(expected=4)
    still_waiting(1)            # an early reply, extension << remaining time
    time.sleep(0.3)             # past now+extension, well inside the base window
    assert still_waiting(1) is True, \
        "an early reply must not pull the deadline in"
