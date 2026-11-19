"""
Tests for scarlet_agentic_harness/local_matrix.py.

These tests run without Docker or Redis. They use real CsvConnector
instances over CSV files in tmp_path, and a scripted LLM client that
raises AssertionError if called more times than expected.

The module-level CONFIG_PATH in local_config is patched per-test to point
to a temporary config file. Config entries MUST include type: csv, or
build_connector raises KeyError.
"""
import os
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import yaml

# Patch CONFIG_PATH before importing modules that depend on it
from scarlet_agentic_harness import local_config
from scarlet_agentic_harness import local_matrix
from scarlet_agentic_harness import data_profile
from tests.fakes import ScriptedLLMClient


def _make_csv_and_config(
    tmp_path: Path, name: str, header: list[str], rows: list[list], config_extra: dict | None = None
) -> tuple[Path, dict]:
    """Create a CSV file and a config entry, return (csv_path, config_entry)."""
    csv_path = tmp_path / f"{name}.csv"
    with open(csv_path, "w", newline="") as f:
        import csv

        writer = csv.writer(f)
        writer.writerow(header)
        for row in rows:
            writer.writerow(row)

    entry = {
        "type": "csv",
        # `mode` is not optional. profile_sources() skips any entry whose
        # mode is not exactly "local", so omitting it makes every source
        # vanish silently - the config loads, the entry is there, and the
        # profiles come back empty with no error anywhere.
        "mode": "local",
        "path": str(csv_path),
        "name": name,
    }
    if config_extra:
        entry.update(config_extra)

    return csv_path, entry


def _build_ctx(
    monkeypatch, tmp_path: Path, config_entries: list[dict], llm_client: Any | None = None
) -> Any:
    """
    Build a stub context whose `data_profiles` came from the real profiler.

    The CONFIG_PATH patch is applied through `monkeypatch`, not by hand,
    so it stays in force for the whole test and is undone at teardown.
    Restoring it immediately after profiling - which an earlier version of
    this helper did - leaves `find_source` and `refresh_if_stale` pointing
    at the real ~/.scarlet/config.yaml, and every test that reaches the
    connector fails with "this worker has no profiled local sources".
    """
    config_path = tmp_path / "config.yaml"
    with open(config_path, "w") as f:
        yaml.safe_dump({"sources": config_entries}, f)

    monkeypatch.setattr(local_config, "CONFIG_PATH", config_path)
    profiles = data_profile.profile_sources()

    ctx = type("Ctx", (), {})()
    ctx.data_profiles = profiles
    ctx.llm_client = llm_client
    return ctx


def _make_csv_ctx(
    monkeypatch, tmp_path: Path, name: str, header: list[str], rows: list[list],
    llm_client: Any | None = None
) -> tuple[Any, Path]:
    """Create a CSV + config and return (stub_ctx, csv_path)."""
    csv_path, entry = _make_csv_and_config(tmp_path, name, header, rows)
    ctx = _build_ctx(monkeypatch, tmp_path, [entry], llm_client)
    return ctx, csv_path


# ==============================================================================
# _validate_sql tests
# ==============================================================================


@pytest.mark.parametrize(
    "valid_sql",
    [
        # The commonest form of all. An earlier regex required whitespace
        # AFTER `data`, so anything ending "FROM data" was rejected - which
        # would have failed most generations the model produces.
        "SELECT a, b FROM data",
        "SELECT a FROM data;",
        "SELECT a FROM data WHERE a > 1",
        "select * from data",
        "SELECT a FROM data ORDER BY a",
        # `load` is a plausible sensor column. It must not trip the
        # forbidden-keyword guard.
        "SELECT load, torque FROM data",
    ],
)
def test_validate_sql_accepts_valid_queries(valid_sql: str) -> None:
    """Every shape a sane generator produces must survive validation."""
    out = local_matrix._validate_sql(valid_sql)
    # Returned verbatim apart from one optional trailing semicolon.
    assert out == valid_sql.rstrip(";").strip()


def test_validate_sql_strips_one_trailing_semicolon() -> None:
    """The connector takes a single statement; a trailing ';' is noise, not an error."""
    assert local_matrix._validate_sql("SELECT a FROM data;") == "SELECT a FROM data"


@pytest.mark.parametrize(
    "invalid_sql,expected_msg",
    [
        # These three fail the "must start with SELECT" rule, which is
        # checked BEFORE the keyword list - so that is the message they
        # produce. Asserting "forbidden keyword" here would be asserting a
        # branch that never runs for them.
        ("DROP TABLE data", "must start with SELECT"),
        ("INSERT INTO data VALUES (1)", "must start with SELECT"),
        ("UPDATE data SET a=1", "must start with SELECT"),
        # This one DOES reach the keyword guard: it starts with SELECT and
        # references `data`, so only the keyword list stops the second
        # statement.
        ("SELECT a FROM data; DROP TABLE data", "forbidden keyword"),
        # Must reference the table the connector actually loads.
        ("SELECT a FROM other_table", "must contain"),
    ],
)
def test_validate_sql_rejects_invalid_queries(invalid_sql: str, expected_msg: str) -> None:
    """Rejections must name the rule that was broken, so a bad generation is debuggable."""
    with pytest.raises(ValueError, match=expected_msg):
        local_matrix._validate_sql(invalid_sql)


def test_convert_to_matrix_basic() -> None:
    """_convert_to_matrix should convert numeric rows to float64."""
    rows = [[1, 2], [3, 4]]
    matrix, dropped = local_matrix._convert_to_matrix(rows, 2)
    assert matrix.dtype == np.float64
    assert matrix.shape == (2, 2)
    assert np.array_equal(matrix, np.array([[1.0, 2.0], [3.0, 4.0]]))
    assert dropped == 0


def test_convert_to_matrix_drops_non_numeric() -> None:
    """Rows with non-numeric strings are dropped and counted."""
    rows = [[1, 2], ["a", 3], [4, 5]]
    matrix, dropped = local_matrix._convert_to_matrix(rows, 2)
    assert matrix.shape == (2, 2)
    assert dropped == 1


def test_convert_to_matrix_drops_none() -> None:
    """Rows containing None are dropped and counted."""
    rows = [[1, 2], [None, 3], [4, 5]]
    matrix, dropped = local_matrix._convert_to_matrix(rows, 2)
    assert matrix.shape == (2, 2)
    assert dropped == 1


def test_convert_to_matrix_single_column_shape() -> None:
    """Single-column result must have shape (n, 1), NEVER (n,)."""
    rows = [[1], [2], [3]]
    matrix, dropped = local_matrix._convert_to_matrix(rows, 1)
    assert matrix.ndim == 2
    assert matrix.shape == (3, 1)


def test_convert_to_matrix_all_bad_returns_empty() -> None:
    """All-bad input returns empty array with correct column count."""
    rows = [["a", "b"], [None, 1], ["x", "y"]]
    matrix, dropped = local_matrix._convert_to_matrix(rows, 2)
    assert matrix.shape == (0, 2)
    assert matrix.dtype == np.float64
    assert dropped == 3


def test_convert_to_matrix_drops_nan_inf() -> None:
    """Rows with NaN or inf are dropped."""
    rows = [[1, 2], [float("nan"), 3], [4, float("inf")], [5, 6]]
    matrix, dropped = local_matrix._convert_to_matrix(rows, 2)
    assert matrix.shape == (2, 2)
    assert dropped == 2


def test_convert_to_matrix_all_rows_dropped_keeps_column_count() -> None:
    """
    An all-bad input must still return a 2-D array of the right width.

    Found by mutation testing: changing this path to `np.empty((0,))`
    passed the whole suite. It matters because load_local_matrix inspects
    `matrix.shape[0]` to decide whether anything survived, and a 1-D empty
    array makes `shape[1]` an IndexError instead of a clean "no rows
    survived" ValueError - turning a clear data problem into a crash.
    """
    # Two DIFFERENT paths reach an empty result, and they are easy to
    # confuse: no rows at all takes an early return, while rows that all
    # get dropped falls through the normal build. Both must be 2-D.
    no_rows, dropped_none = local_matrix._convert_to_matrix([], 2)
    assert no_rows.ndim == 2
    assert no_rows.shape == (0, 2)
    assert dropped_none == 0

    all_dropped, dropped = local_matrix._convert_to_matrix([["x", "y"], [None, None]], 2)
    assert all_dropped.ndim == 2
    assert all_dropped.shape == (0, 2)
    assert dropped == 2


# ==============================================================================
# choose_source tests
# ==============================================================================


def test_choose_source_no_profiles_returns_none() -> None:
    """No profiles -> returns None, no LLM call."""
    ctx = type("Ctx", (), {})()
    ctx.data_profiles = {}
    ctx.llm_client = ScriptedLLMClient([])  # Any call would raise

    result = local_matrix.choose_source(ctx, "test objective")
    assert result is None


def test_choose_source_single_profile_returns_its_name() -> None:
    """Exactly one profile -> returns its name, no LLM call."""
    ctx = type("Ctx", (), {})()
    ctx.data_profiles = {"source1": {"description": "test", "shape": (10, 2), "numeric_columns": ["a", "b"]}}
    ctx.llm_client = ScriptedLLMClient([])  # Any call would raise

    result = local_matrix.choose_source(ctx, "test objective")
    assert result == "source1"


def test_choose_source_multiple_profiles_uses_llm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Multiple profiles -> LLM chooses, returns its answer."""
    csv_path1, entry1 = _make_csv_and_config(tmp_path, "src1", ["a", "b"], [[1, 2], [3, 4]])
    csv_path2, entry2 = _make_csv_and_config(tmp_path, "src2", ["x", "y", "z"], [[1, 2, 3], [4, 5, 6]])
    ctx = _build_ctx(monkeypatch, tmp_path, [entry1, entry2], ScriptedLLMClient([{"content": "src2"}]))

    result = local_matrix.choose_source(ctx, "test objective")
    assert result == "src2"


def test_choose_source_llm_invalid_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM returns unknown name -> falls back to most numeric columns."""
    csv_path1, entry1 = _make_csv_and_config(tmp_path, "src1", ["a", "b"], [[1, 2], [3, 4]])
    csv_path2, entry2 = _make_csv_and_config(tmp_path, "src2", ["x"], [[1], [2]])
    ctx = _build_ctx(monkeypatch, tmp_path, [entry1, entry2], ScriptedLLMClient([{"content": "nonexistent"}]))

    result = local_matrix.choose_source(ctx, "test objective")
    # src1 has 2 numeric columns, src2 has 1 -> src1 wins
    assert result == "src1"


# ==============================================================================
# generate_sql tests
# ==============================================================================


def test_generate_sql_requires_llm() -> None:
    """generate_sql raises ValueError if ctx.llm_client is None."""
    ctx = type("Ctx", (), {})()
    ctx.data_profiles = {"src": {"numeric_columns": ["a"], "rows": 10}}
    ctx.llm_client = None

    with pytest.raises(ValueError, match="worker-local SQL generation requires an LLM backend"):
        local_matrix.generate_sql(ctx, "src", "test objective")


def test_generate_sql_validates_reply(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """generate_sql raises ValueError if LLM reply fails validation."""
    csv_path, entry = _make_csv_and_config(tmp_path, "src", ["a", "b"], [[1, 2], [3, 4]])
    ctx = _build_ctx(monkeypatch, tmp_path, [entry], ScriptedLLMClient([{"content": "DROP TABLE src"}]))

    # "DROP TABLE src" trips the FIRST rule (must start with SELECT), not
    # the keyword list - the rules are ordered, and asserting the later
    # message would be asserting a branch this input never reaches.
    with pytest.raises(ValueError, match="must start with SELECT"):
        local_matrix.generate_sql(ctx, "src", "test objective")


# ==============================================================================
# load_local_matrix tests
# ==============================================================================


def test_load_local_matrix_with_agreed_columns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """With columns=[...], LLM is NOT called, columns in that order."""
    csv_path, entry = _make_csv_and_config(
        tmp_path, "src", ["z", "a", "b"], [[1, 2, 3], [4, 5, 6]]
    )
    ctx = _build_ctx(monkeypatch, tmp_path, [entry], ScriptedLLMClient([]))  # Any call raises

    matrix, meta = local_matrix.load_local_matrix(ctx, "test objective", columns=["a", "b", "z"])

    # Check matrix shape and values
    assert matrix.shape == (2, 3)
    assert np.array_equal(matrix, np.array([[2.0, 3.0, 1.0], [5.0, 6.0, 4.0]]))

    # Check meta
    assert meta["source"] == "src"
    assert "SELECT" in meta["sql"]
    assert meta["columns"] == ["a", "b", "z"]
    assert meta["rows_returned"] == 2
    assert meta["rows_dropped"] == 0
    assert meta["shape"] == (2, 3)
    assert meta["sql_source"] == "agreed_columns"


def test_load_local_matrix_meta_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """meta carries all required fields."""
    csv_path, entry = _make_csv_and_config(tmp_path, "src", ["a", "b"], [[1, 2], [3, 4]])
    ctx = _build_ctx(monkeypatch, tmp_path, [entry], ScriptedLLMClient([{"content": "SELECT a, b FROM data"}]))

    matrix, meta = local_matrix.load_local_matrix(ctx, "test objective")

    assert "source" in meta
    assert "sql" in meta
    assert "columns" in meta
    assert "rows_returned" in meta
    assert "rows_dropped" in meta
    assert "shape" in meta
    assert "sql_source" in meta


def test_load_local_matrix_drops_rows_with_blanks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """rows_dropped is non-zero when CSV has blanks in selected column."""
    csv_path, entry = _make_csv_and_config(
        tmp_path, "src", ["a", "b"], [["1", "2"], ["", "3"], ["4", "5"]]
    )
    ctx = _build_ctx(monkeypatch, tmp_path, [entry], ScriptedLLMClient([{"content": "SELECT a, b FROM data"}]))

    matrix, meta = local_matrix.load_local_matrix(ctx, "test objective")

    assert meta["rows_returned"] == 2
    assert meta["rows_dropped"] == 1


def test_load_local_matrix_no_profiles_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No profiles -> ValueError."""
    ctx = _build_ctx(monkeypatch, tmp_path, [], ScriptedLLMClient([]))

    with pytest.raises(ValueError, match="this worker has no profiled local sources"):
        local_matrix.load_local_matrix(ctx, "test objective")
