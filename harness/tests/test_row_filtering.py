"""
End-to-end row filtering through the real CsvConnector.

Covers the sprint's filtering path at the level that actually matters: a
structured condition goes in, real SQL comes out, duckdb runs it against a
real CSV, and the rows that come back are the ones the window admits.

Like test_data_profile, this runs without Docker or Redis - CsvConnector is
pure duckdb+pandas over a local file.

CRITICAL: local_config.CONFIG_PATH is a module-level Path resolved at IMPORT
time, so it must be monkeypatched on the module, never via the env var.
"""
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from scarlet_agentic_harness import data_profile, local_config, local_matrix

# One minute apart from midnight, so row i is at 00:{i:02d}.
_ROWS = 10


def _ctx(monkeypatch, tmp_path: Path, columns=None, rows=None):
    """Write a CSV + config, profile it, and return a ctx holding the profile."""
    columns = columns or ["timestamp", "power_kw", "status"]
    if rows is None:
        rows = [
            [f"2026-01-01T00:{i:02d}:00", float(i), "on"]
            for i in range(_ROWS)
        ]

    csv_path = tmp_path / "readings.csv"
    with csv_path.open("w", newline="") as f:
        f.write(",".join(columns) + "\n")
        for row in rows:
            f.write(",".join("" if v is None else str(v) for v in row) + "\n")

    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump({"sources": [{
        "name": "readings", "path": str(csv_path),
        "mode": "local", "type": "csv",
        "description": "test readings",
    }]}))
    monkeypatch.setattr(local_config, "CONFIG_PATH", cfg)

    profiles = data_profile.profile_sources()
    assert "readings" in profiles, "fixture failed to profile the CSV"
    return SimpleNamespace(data_profiles=profiles, llm_client=None,
                           agent_id="w1")


def test_profile_types_the_timestamp_column(monkeypatch, tmp_path):
    """The filter column must be recognised as temporal, not as text."""
    ctx = _ctx(monkeypatch, tmp_path)
    prof = ctx.data_profiles["readings"]
    assert "timestamp" in prof["temporal_columns"]
    assert "timestamp" not in prof["numeric_columns"]
    # and it is still filterable even though it can never be aggregated
    assert "power_kw" in prof["numeric_columns"]


def test_time_window_admits_only_rows_inside_it(monkeypatch, tmp_path):
    """A half-open window returns exactly the rows it covers."""
    ctx = _ctx(monkeypatch, tmp_path)
    matrix, meta = local_matrix.load_local_matrix(
        ctx, "power readings", columns=["power_kw"],
        conditions=[
            {"column": "timestamp", "op": "gte", "value": "2026-01-01T00:02:00"},
            {"column": "timestamp", "op": "lt", "value": "2026-01-01T00:05:00"},
        ],
    )
    # rows at 00:02, 00:03, 00:04 - power_kw equals the minute index
    assert matrix.shape == (3, 1)
    assert [v[0] for v in matrix.tolist()] == [2.0, 3.0, 4.0]
    assert meta["filtered"] is True
    assert meta["rows_matched"] == 3
    assert "WHERE" in meta["sql"]


def test_no_conditions_reads_every_row(monkeypatch, tmp_path):
    """The unfiltered path is unchanged - this is the regression guard."""
    ctx = _ctx(monkeypatch, tmp_path)
    matrix, meta = local_matrix.load_local_matrix(
        ctx, "power readings", columns=["power_kw"])
    assert matrix.shape == (_ROWS, 1)
    assert meta["filtered"] is False
    assert "WHERE" not in meta["sql"]


def test_a_window_matching_nothing_is_not_an_error(monkeypatch, tmp_path):
    """
    An empty window is an ordinary outcome, not a broken worker.

    It must not raise, and it must be distinguishable from a worker that
    contributed a real zero - otherwise an empty slice gets averaged in.
    """
    ctx = _ctx(monkeypatch, tmp_path)
    matrix, meta = local_matrix.load_local_matrix(
        ctx, "power readings", columns=["power_kw"],
        conditions=[
            {"column": "timestamp", "op": "gte", "value": "2027-01-01T00:00:00"},
        ],
    )
    assert matrix.shape[0] == 0
    assert meta["rows_matched"] == 0
    assert meta["filtered"] is True


def test_filtering_on_a_column_this_worker_lacks_is_its_own_error(
        monkeypatch, tmp_path):
    """
    Missing filter column is a distinct, reportable case.

    It is not "zero rows matched" - the worker cannot answer the question
    at all, and the message has to say so.
    """
    ctx = _ctx(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="does not have column"):
        local_matrix.load_local_matrix(
            ctx, "power readings", columns=["power_kw"],
            conditions=[{"column": "nonexistent", "op": "gt", "value": 1}],
        )


def test_a_non_iso_timestamp_column_refuses_to_filter(monkeypatch, tmp_path):
    """
    US-format dates are left untyped, so filtering on them raises.

    Compared as strings '03/01/2025' >= '01/15/2026' is True - wrong by a
    year, and silent. Refusing beats answering wrongly.
    """
    rows = [[f"0{i+1}/01/2026", float(i), "on"] for i in range(5)]
    ctx = _ctx(monkeypatch, tmp_path, rows=rows)
    prof = ctx.data_profiles["readings"]
    assert "timestamp" not in prof["temporal_columns"]

    # It is typed as text, so an ISO value becomes a string comparison
    # rather than a timestamp one. That is exactly what must not silently
    # happen, so assert the clause is NOT a TIMESTAMP comparison.
    _, meta = local_matrix.load_local_matrix(
        ctx, "power readings", columns=["power_kw"],
        conditions=[{"column": "timestamp", "op": "gte", "value": "01/01/2026"}],
    )
    assert "TIMESTAMP" not in meta["where"]


# --- empty workers must be named upward, not just excluded ------------------

def test_sum_coordinate_names_every_worker_that_matched_nothing():
    """
    The arithmetic already handles an empty worker: a zero sum over a zero
    count moves neither the numerator nor the denominator. But that makes
    it invisible, and the head will otherwise infer from a successful round
    that every worker had data - observed exactly that, reporting "no
    workers were missing readings" when three of four had none.
    """
    import numpy as np
    from scarlet_agentic_harness.skills.core.sum import SumCoreSkill, _READY_MSG_TYPE

    workers = ["w1", "w2", "w3", "w4"]
    ready = [{"type": _READY_MSG_TYPE, "from": w, "ncols": 3,
              "rows": 20 if w == "w3" else 0, "map_status": True}
             for w in workers]

    class _Router:
        def __init__(self): self._q = [{"body": b} for b in ready]
        def receive_for(self, rid, timeout=1): return self._q.pop(0) if self._q else None
        def forget(self, rid): pass

    class _Fed:
        def Aggregate(self, identity):
            # (totals, status, exc) - row 0 column sums, row 1 the count.
            # 20 rows, all of them from w3.
            return np.array([[100.0, 200.0, 300.0], [20.0, 20.0, 20.0]]), True, None

    class _Ctx:
        agent_id = "w1"
        data_profiles = {}
        cancelled = type("C", (), {"is_set": staticmethod(lambda: False)})()
        def __init__(self):
            class _B:
                local_bus = type("X", (), {"Send": staticmethod(lambda *a, **k: None)})()
                local_router = _Router()
            self.buses = _B()
        def federator(self, name, op=None): return _Fed()
        def report_progress(self, **kw): pass

    out = SumCoreSkill().coordinate(
        _Ctx(), {"request_id": "r1", "mapper_name": "m", "params": {}}, workers)

    assert out["status"] == "ok", out
    assert out["empty_workers"] == ["w1", "w2", "w4"], out.get("empty_workers")
    assert out["rows_per_worker"] == {"w1": 0, "w2": 0, "w3": 20, "w4": 0}
    assert "matched no rows" in out["detail"]
    for w in ("w1", "w2", "w4"):
        assert w in out["detail"], f"{w} missing from the narratable detail"


# --- heterogeneous date formats --------------------------------------------
#
# The fleet agrees ONE logical window. Each worker casts its own column to
# it. This is the only objective that genuinely needs per-worker SQL: no
# amount of agreement makes "%d/%m/%Y" readable by a plain CAST.

def test_a_worker_storing_eu_dates_casts_with_its_own_pattern(
        monkeypatch, tmp_path):
    """Unambiguous day-first dates are typed, and filtered correctly."""
    # Days 13-22 - all > 12, so %m/%d/%Y cannot parse them and the format
    # is unambiguous.
    rows = [[f"{13 + i}/06/2026", float(i), "on"] for i in range(10)]
    ctx = _ctx(monkeypatch, tmp_path, rows=rows)
    prof = ctx.data_profiles["readings"]

    assert "timestamp" in prof["temporal_columns"]
    fmt = next(c["format"] for c in prof["columns"] if c["name"] == "timestamp")
    assert fmt == "%d/%m/%Y"

    matrix, meta = local_matrix.load_local_matrix(
        ctx, "power readings", columns=["power_kw"],
        conditions=[
            {"column": "timestamp", "op": "gte", "value": "2026-06-15T00:00:00"},
            {"column": "timestamp", "op": "lt", "value": "2026-06-18T00:00:00"},
        ],
    )
    # 15, 16, 17 June -> rows 2, 3, 4 -> power_kw 2.0, 3.0, 4.0
    assert "strptime" in meta["where"]
    assert [v[0] for v in matrix.tolist()] == [2.0, 3.0, 4.0]


def test_an_ambiguous_date_column_is_refused_rather_than_guessed(
        monkeypatch, tmp_path):
    """
    Every day <= 12, so both %m/%d/%Y and %d/%m/%Y parse every value.

    Nothing in the data says which was meant. Guessing shifts the series by
    months and never errors, so the column stays untyped and filtering on
    it raises instead.
    """
    rows = [[f"0{i+1}/0{i+1}/2026", float(i), "on"] for i in range(9)]
    ctx = _ctx(monkeypatch, tmp_path, rows=rows)
    prof = ctx.data_profiles["readings"]
    assert "timestamp" not in prof["temporal_columns"], \
        "an ambiguous date column must not be typed"


def test_iso_workers_are_unaffected_by_the_new_formats(monkeypatch, tmp_path):
    """Regression guard: ISO still takes the plain CAST path."""
    ctx = _ctx(monkeypatch, tmp_path)
    _, meta = local_matrix.load_local_matrix(
        ctx, "power readings", columns=["power_kw"],
        conditions=[{"column": "timestamp", "op": "gte",
                     "value": "2026-01-01T00:05:00"}],
    )
    assert "CAST(" in meta["where"] and "strptime" not in meta["where"]


# --- a failed data read must not permanently kill the round ----------------

@pytest.mark.parametrize("read_retryable,expected", [(True, True), (False, False)])
def test_a_read_failure_carries_its_retryability(read_retryable, expected):
    """
    `contribute` reads its data before it Maps. That read was unguarded, so
    a raise was reported non-retryable - right for a bad column, wrong for a
    dropped database connection, where the head gave up on a round a second
    attempt would have completed.
    """
    import numpy as np
    from scarlet_agentic_harness.skills.core.sum import SumCoreSkill, _READY_MSG_TYPE

    body = {"type": _READY_MSG_TYPE, "from": "w1", "ncols": 0, "rows": 0,
            "read_status": False, "read_error": "OperationalError: connection lost",
            "read_retryable": read_retryable, "map_status": False, "map_error": None}

    class _Router:
        def __init__(self): self._q = [{"body": body}]
        def receive_for(self, rid, timeout=1): return self._q.pop(0) if self._q else None
        def forget(self, rid): pass

    class _Ctx:
        agent_id = "w1"
        data_profiles = {}
        cancelled = type("C", (), {"is_set": staticmethod(lambda: False)})()
        def __init__(self):
            class _B:
                local_bus = type("X", (), {"Send": staticmethod(lambda *a, **k: None)})()
                local_router = _Router()
            self.buses = _B()
        def federator(self, name, op=None): raise AssertionError("must not aggregate")
        def report_progress(self, **kw): pass

    out = SumCoreSkill().coordinate(
        _Ctx(), {"request_id": "r1", "mapper_name": "m", "params": {}}, ["w1"])

    assert out["status"] == "error"
    assert out["retryable"] is expected
    assert "could not read its data" in out["detail"]
    assert "connection lost" in out["detail"]
