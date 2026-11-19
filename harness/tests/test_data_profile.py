"""
Tests for scarlet_agentic_harness.data_profile.

These tests run without Docker or Redis. The suite's heavyweight fixtures
require a real Redis/Postgres container; these cover pure logic and the
real CsvConnector instead. CsvConnector is pure duckdb+pandas over a local
file, so we write real CSVs into tmp_path and exercise the real connector.

CRITICAL: local_config.CONFIG_PATH is a module-level Path resolved at
IMPORT time from SCARLET_LOCAL_CONFIG. Setting that env var inside a test
does nothing. Every test must instead do:

    monkeypatch.setattr(local_config, "CONFIG_PATH", tmp_path / "config.yaml")
"""
import os
from pathlib import Path

import pytest
import yaml

from scarlet_agentic_harness import data_profile, local_config


def _write_csv_and_config(monkeypatch, tmp_path: Path, sources: list[dict]) -> None:
    """
    Write a CSV for each source and a config pointing at them.

    Each source dict must contain:
      - name: str
      - columns: list[str] (column names)
      - rows: list[list] (data rows)
      - optional: description: str, mode: str (defaults to "local"), type: str (defaults to "csv")
      - optional: path: str (if provided, use this path verbatim and skip writing CSV)

    Writes CSVs to tmp_path/<name>.csv and a config.yaml pointing at them.
    """
    config_entries = []
    for src in sources:
        name = src["name"]
        if "path" in src:
            csv_path = src["path"]
        else:
            csv_path = tmp_path / f"{name}.csv"
            columns = src["columns"]
            rows = src["rows"]

            # Write CSV
            with csv_path.open("w", newline="") as f:
                f.write(",".join(columns) + "\n")
                for row in rows:
                    f.write(",".join(str(v) if v is not None else "" for v in row) + "\n")

        entry = {
            "name": name,
            "path": str(csv_path),
            "mode": src.get("mode", "local"),
            "type": src.get("type", "csv"),
        }
        if "description" in src:
            entry["description"] = src["description"]
        config_entries.append(entry)

    # Write config using yaml.safe_dump
    config_path = tmp_path / "config.yaml"
    config_dict = {"sources": config_entries}
    config_path.write_text(yaml.safe_dump(config_dict, default_flow_style=False, allow_unicode=True))

    # Patch CONFIG_PATH for this test
    monkeypatch.setattr(local_config, "CONFIG_PATH", config_path)


# ---------------------------------------------------------------------
# profile_sources tests
# ---------------------------------------------------------------------

def test_profile_sources_shape_is_exact(monkeypatch, tmp_path):
    """A 40-row CSV with 3 numeric columns and one text column gives shape == [40, 3]."""
    rows = [[i, float(i * 2), float(i * 3), f"2024-01-{(i % 28) + 1:02d}T00:00:00"]
            for i in range(40)]
    _write_csv_and_config(monkeypatch, tmp_path, [{
        "name": "test_data",
        "columns": ["a", "b", "c", "ts"],
        "rows": rows,
    }])
    monkeypatch.setattr(local_config, "CONFIG_PATH", tmp_path / "config.yaml")

    profiles = data_profile.profile_sources()
    assert "test_data" in profiles
    assert profiles["test_data"]["shape"] == [40, 3]
    assert profiles["test_data"]["rows"] == 40


def test_profile_sources_text_column_not_numeric(monkeypatch, tmp_path):
    """ISO timestamps are not counted as numeric."""
    rows = [[f"2024-01-{(i % 28) + 1:02d}T00:00:00"] for i in range(10)]
    _write_csv_and_config(monkeypatch, tmp_path, [{
        "name": "timestamps",
        "columns": ["ts"],
        "rows": rows,
    }])
    monkeypatch.setattr(local_config, "CONFIG_PATH", tmp_path / "config.yaml")

    profiles = data_profile.profile_sources()
    assert "timestamps" in profiles
    cols = profiles["timestamps"]["columns"]
    assert len(cols) == 1
    assert cols[0]["name"] == "ts"
    assert cols[0]["numeric"] is False


def test_profile_sources_boolean_column_not_numeric(monkeypatch, tmp_path):
    """Booleans are not numeric even though float(True) succeeds."""
    rows = [[True], [False], [True], [False]]
    _write_csv_and_config(monkeypatch, tmp_path, [{
        "name": "bools",
        "columns": ["flag"],
        "rows": rows,
    }])
    monkeypatch.setattr(local_config, "CONFIG_PATH", tmp_path / "config.yaml")

    profiles = data_profile.profile_sources()
    assert "bools" in profiles
    cols = profiles["bools"]["columns"]
    assert len(cols) == 1
    assert cols[0]["name"] == "flag"
    assert cols[0]["numeric"] is False


def test_profile_sources_null_counts_per_column(monkeypatch, tmp_path):
    """Null counts are per column and exact."""
    rows = [
        [1, 10, 100],
        [2, None, 200],
        [None, 30, None],
        [None, 40, None],
    ]
    _write_csv_and_config(monkeypatch, tmp_path, [{
        "name": "nulls_test",
        "columns": ["a", "b", "c"],
        "rows": rows,
    }])
    monkeypatch.setattr(local_config, "CONFIG_PATH", tmp_path / "config.yaml")

    profiles = data_profile.profile_sources()
    assert "nulls_test" in profiles
    cols = {c["name"]: c for c in profiles["nulls_test"]["columns"]}
    assert cols["a"]["nulls"] == 2
    assert cols["b"]["nulls"] == 1
    assert cols["c"]["nulls"] == 2


def test_profile_sources_entirely_empty_column_not_numeric(monkeypatch, tmp_path):
    """A column that is entirely empty is NOT numeric."""
    rows = [[None], [None], [None]]
    _write_csv_and_config(monkeypatch, tmp_path, [{
        "name": "empty_col",
        "columns": ["empty"],
        "rows": rows,
    }])
    monkeypatch.setattr(local_config, "CONFIG_PATH", tmp_path / "config.yaml")

    profiles = data_profile.profile_sources()
    assert "empty_col" in profiles
    cols = profiles["empty_col"]["columns"]
    assert len(cols) == 1
    assert cols[0]["name"] == "empty"
    assert cols[0]["numeric"] is False


def test_profile_sources_mode_broker_skipped(monkeypatch, tmp_path):
    """mode: broker entries are skipped entirely."""
    rows = [[1, 2]]
    _write_csv_and_config(monkeypatch, tmp_path, [{
        "name": "local_source",
        "columns": ["a", "b"],
        "rows": rows,
    }, {
        "name": "broker_source",
        "columns": ["x", "y"],
        "rows": rows,
        "mode": "broker",
    }])
    monkeypatch.setattr(local_config, "CONFIG_PATH", tmp_path / "config.yaml")

    profiles = data_profile.profile_sources()
    assert "local_source" in profiles
    assert "broker_source" not in profiles


def test_profile_sources_one_unreadable_source_does_not_stop_others(monkeypatch, tmp_path):
    """One unreadable source does not prevent other valid sources from being profiled."""
    rows = [[1, 2]]
    _write_csv_and_config(monkeypatch, tmp_path, [{
        "name": "good_source",
        "columns": ["a", "b"],
        "rows": rows,
    }, {
        "name": "bad_source",
        "path": str(tmp_path / "does_not_exist.csv"),
        "columns": ["x", "y"],
        "rows": rows,
    }])
    monkeypatch.setattr(local_config, "CONFIG_PATH", tmp_path / "config.yaml")

    profiles = data_profile.profile_sources()
    assert "good_source" in profiles
    assert "bad_source" not in profiles


def test_profile_sources_description_carried_through(monkeypatch, tmp_path):
    """description is carried through from the config entry; missing gets ""."""
    rows = [[1]]
    _write_csv_and_config(monkeypatch, tmp_path, [{
        "name": "with_desc",
        "columns": ["a"],
        "rows": rows,
        "description": "A test dataset",
    }, {
        "name": "no_desc",
        "columns": ["b"],
        "rows": rows,
    }])
    monkeypatch.setattr(local_config, "CONFIG_PATH", tmp_path / "config.yaml")

    profiles = data_profile.profile_sources()
    assert profiles["with_desc"]["description"] == "A test dataset"
    assert profiles["no_desc"]["description"] == ""


# ---------------------------------------------------------------------
# render_profile_markdown tests
# ---------------------------------------------------------------------

def test_render_profile_markdown_starts_with_header_and_sections(monkeypatch, tmp_path):
    """Output starts with '# Local data profile' and contains '## <name>' per source."""
    rows = [[1, 2]]
    _write_csv_and_config(monkeypatch, tmp_path, [{
        "name": "test_source",
        "columns": ["a", "b"],
        "rows": rows,
    }])
    monkeypatch.setattr(local_config, "CONFIG_PATH", tmp_path / "config.yaml")

    profiles = data_profile.profile_sources()
    md = data_profile.render_profile_markdown(profiles)
    assert md.startswith("# Local data profile")
    assert "## test_source" in md


def test_render_profile_markdown_shape_line(monkeypatch, tmp_path):
    """The shape line reports rows x numeric-column-count."""
    rows = [[1, 2, "text"]]
    _write_csv_and_config(monkeypatch, tmp_path, [{
        "name": "shape_test",
        "columns": ["a", "b", "c"],
        "rows": rows,
    }])
    monkeypatch.setattr(local_config, "CONFIG_PATH", tmp_path / "config.yaml")

    profiles = data_profile.profile_sources()
    md = data_profile.render_profile_markdown(profiles)
    assert "- shape: 1 x 2  (rows x numeric columns)" in md


def test_render_profile_markdown_gaps_rendered(monkeypatch, tmp_path):
    """Gaps are rendered as name=count for columns with nulls."""
    rows = [[1, None], [2, 20], [None, 30]]
    _write_csv_and_config(monkeypatch, tmp_path, [{
        "name": "gaps_test",
        "columns": ["a", "b"],
        "rows": rows,
    }])
    monkeypatch.setattr(local_config, "CONFIG_PATH", tmp_path / "config.yaml")

    profiles = data_profile.profile_sources()
    md = data_profile.render_profile_markdown(profiles)
    assert "gaps: a=1, b=1" in md


# ---------------------------------------------------------------------
# profiles_are_stale tests
# ---------------------------------------------------------------------

def test_profiles_are_stale_false_when_names_match(monkeypatch, tmp_path):
    """False when the profile keys match the config's local source names."""
    rows = [[1]]
    _write_csv_and_config(monkeypatch, tmp_path, [{
        "name": "source_a",
        "columns": ["a"],
        "rows": rows,
    }])
    monkeypatch.setattr(local_config, "CONFIG_PATH", tmp_path / "config.yaml")

    profiles = data_profile.profile_sources()
    assert data_profile.profiles_are_stale(profiles) is False


def test_profiles_are_stale_true_when_config_gains_source(monkeypatch, tmp_path):
    """True when the config gains a source the profiles do not have."""
    rows = [[1]]
    _write_csv_and_config(monkeypatch, tmp_path, [{
        "name": "source_a",
        "columns": ["a"],
        "rows": rows,
    }, {
        "name": "source_b",
        "columns": ["b"],
        "rows": rows,
    }])
    monkeypatch.setattr(local_config, "CONFIG_PATH", tmp_path / "config.yaml")

    # Profile only source_a
    # Built through yaml, with `type`, for the same reason the helper
    # does: build_connector selects the connector class from `type`,
    # and omitting it makes every source fail to profile - which looks
    # exactly like the staleness this test is trying to assert.
    config_a = tmp_path / "config_a.yaml"
    config_a.write_text(yaml.safe_dump({"sources": [{
        "name": "source_a", "type": "csv", "mode": "local",
        "path": str(tmp_path / "source_a.csv"),
    }]}))
    monkeypatch.setattr(local_config, "CONFIG_PATH", config_a)
    profiles = data_profile.profile_sources()
    assert "source_a" in profiles
    assert "source_b" not in profiles

    # Now config has both
    monkeypatch.setattr(local_config, "CONFIG_PATH", tmp_path / "config.yaml")
    assert data_profile.profiles_are_stale(profiles) is True


def test_profiles_are_stale_true_when_config_loses_source(monkeypatch, tmp_path):
    """True when the config loses one the profiles still have."""
    rows = [[1]]
    _write_csv_and_config(monkeypatch, tmp_path, [{
        "name": "source_a",
        "columns": ["a"],
        "rows": rows,
    }, {
        "name": "source_b",
        "columns": ["b"],
        "rows": rows,
    }])
    monkeypatch.setattr(local_config, "CONFIG_PATH", tmp_path / "config.yaml")

    profiles = data_profile.profile_sources()
    assert "source_a" in profiles
    assert "source_b" in profiles

    # Now config has only source_a
    # Built through yaml, with `type`, for the same reason the helper
    # does: build_connector selects the connector class from `type`,
    # and omitting it makes every source fail to profile - which looks
    # exactly like the staleness this test is trying to assert.
    config_a = tmp_path / "config_a.yaml"
    config_a.write_text(yaml.safe_dump({"sources": [{
        "name": "source_a", "type": "csv", "mode": "local",
        "path": str(tmp_path / "source_a.csv"),
    }]}))
    monkeypatch.setattr(local_config, "CONFIG_PATH", config_a)
    assert data_profile.profiles_are_stale(profiles) is True


def test_profiles_are_stale_false_when_only_description_changed(monkeypatch, tmp_path):
    """False when only a description changed and the name set is identical."""
    rows = [[1]]
    _write_csv_and_config(monkeypatch, tmp_path, [{
        "name": "same_name",
        "columns": ["a"],
        "rows": rows,
        "description": "Original",
    }])
    monkeypatch.setattr(local_config, "CONFIG_PATH", tmp_path / "config.yaml")

    profiles = data_profile.profile_sources()
    assert "same_name" in profiles

    # Update description in config
    config = tmp_path / "config.yaml"
    config.write_text("sources:\n  - name: same_name\n    path: " + str(tmp_path / "same_name.csv") + "\n    mode: local\n    description: Updated")
    monkeypatch.setattr(local_config, "CONFIG_PATH", config)
    assert data_profile.profiles_are_stale(profiles) is False


def test_profiles_are_stale_false_when_config_unreadable(monkeypatch, tmp_path):
    """False when the config file cannot be read at all."""
    rows = [[1]]
    _write_csv_and_config(monkeypatch, tmp_path, [{
        "name": "source_a",
        "columns": ["a"],
        "rows": rows,
    }])
    monkeypatch.setattr(local_config, "CONFIG_PATH", tmp_path / "config.yaml")

    profiles = data_profile.profile_sources()
    assert "source_a" in profiles

    # Make config unreadable (point to a directory)
    monkeypatch.setattr(local_config, "CONFIG_PATH", tmp_path)
    assert data_profile.profiles_are_stale(profiles) is False


# ---------------------------------------------------------------------
# refresh_if_stale tests
# ---------------------------------------------------------------------

def test_refresh_if_stale_false_when_nothing_changed(monkeypatch, tmp_path):
    """Returns False and leaves the dict untouched when nothing changed."""
    rows = [[1]]
    _write_csv_and_config(monkeypatch, tmp_path, [{
        "name": "unchanged",
        "columns": ["a"],
        "rows": rows,
    }])
    monkeypatch.setattr(local_config, "CONFIG_PATH", tmp_path / "config.yaml")

    profiles = data_profile.profile_sources()
    original_id = id(profiles)
    original_keys = set(profiles.keys())
    result = data_profile.refresh_if_stale(profiles)
    assert result is False
    assert id(profiles) == original_id
    assert set(profiles.keys()) == original_keys


def test_refresh_if_stale_true_when_config_changed(monkeypatch, tmp_path):
    """Returns True and updates when the config changed."""
    rows = [[1]]
    _write_csv_and_config(monkeypatch, tmp_path, [{
        "name": "source_a",
        "columns": ["a"],
        "rows": rows,
    }, {
        "name": "source_b",
        "columns": ["b"],
        "rows": rows,
    }])
    monkeypatch.setattr(local_config, "CONFIG_PATH", tmp_path / "config.yaml")

    # Profile only source_a
    # Built through yaml, with `type`, for the same reason the helper
    # does: build_connector selects the connector class from `type`,
    # and omitting it makes every source fail to profile - which looks
    # exactly like the staleness this test is trying to assert.
    config_a = tmp_path / "config_a.yaml"
    config_a.write_text(yaml.safe_dump({"sources": [{
        "name": "source_a", "type": "csv", "mode": "local",
        "path": str(tmp_path / "source_a.csv"),
    }]}))
    monkeypatch.setattr(local_config, "CONFIG_PATH", config_a)
    profiles = data_profile.profile_sources()
    assert "source_a" in profiles
    assert "source_b" not in profiles

    # Now config has both
    monkeypatch.setattr(local_config, "CONFIG_PATH", tmp_path / "config.yaml")
    result = data_profile.refresh_if_stale(profiles)
    assert result is True
    assert "source_a" in profiles
    assert "source_b" in profiles


def test_refresh_if_stale_mutates_same_dict_object(monkeypatch, tmp_path):
    """Mutates the SAME dict object in place; a second reference sees the new contents."""
    rows = [[1]]
    _write_csv_and_config(monkeypatch, tmp_path, [{
        "name": "source_a",
        "columns": ["a"],
        "rows": rows,
    }, {
        "name": "source_b",
        "columns": ["b"],
        "rows": rows,
    }])
    monkeypatch.setattr(local_config, "CONFIG_PATH", tmp_path / "config.yaml")

    # Profile only source_a
    # Built through yaml, with `type`, for the same reason the helper
    # does: build_connector selects the connector class from `type`,
    # and omitting it makes every source fail to profile - which looks
    # exactly like the staleness this test is trying to assert.
    config_a = tmp_path / "config_a.yaml"
    config_a.write_text(yaml.safe_dump({"sources": [{
        "name": "source_a", "type": "csv", "mode": "local",
        "path": str(tmp_path / "source_a.csv"),
    }]}))
    monkeypatch.setattr(local_config, "CONFIG_PATH", config_a)
    profiles = data_profile.profile_sources()
    original_id = id(profiles)
    second_ref = profiles  # hold a second reference

    # Now config has both
    monkeypatch.setattr(local_config, "CONFIG_PATH", tmp_path / "config.yaml")
    result = data_profile.refresh_if_stale(profiles)

    assert result is True
    assert id(profiles) == original_id
    assert "source_b" in profiles
    assert "source_b" in second_ref


def test_refresh_if_stale_does_not_apply_empty_rebuild(monkeypatch, tmp_path):
    """Does NOT apply an empty rebuild over non-empty profiles."""
    rows = [[1]]
    _write_csv_and_config(monkeypatch, tmp_path, [{
        "name": "source_a",
        "columns": ["a"],
        "rows": rows,
    }])
    monkeypatch.setattr(local_config, "CONFIG_PATH", tmp_path / "config.yaml")

    profiles = data_profile.profile_sources()
    assert "source_a" in profiles
    original_id = id(profiles)

    # Point config at empty sources
    config_empty = tmp_path / "config_empty.yaml"
    config_empty.write_text("sources: []")
    monkeypatch.setattr(local_config, "CONFIG_PATH", config_empty)

    result = data_profile.refresh_if_stale(profiles)
    assert result is False
    assert id(profiles) == original_id
    assert "source_a" in profiles


# ---------------------------------------------------------------------
# Helper: ensure local_config is reloaded fresh per test
# ---------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_local_config(monkeypatch, tmp_path):
    """Reset local_config.CONFIG_PATH before each test."""
    # Import local_config fresh to avoid cached state
    import importlib
    import scarlet_agentic_harness.local_config as lc
    importlib.reload(lc)
    # Set a default that won't break tests
    default_config = tmp_path / "default_config.yaml"
    default_config.write_text("sources: []")
    lc.CONFIG_PATH = default_config
    yield
    # Reload again to clear any changes
    importlib.reload(lc)
