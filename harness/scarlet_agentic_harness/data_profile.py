"""
Data profiling utilities for the scarlet_agentic_harness package.

Profiles every local data source a worker holds, once at boot, producing
both machine-readable shape facts and a human-readable summary for the
consensus step and agent context.

Staleness detection ensures profiles stay in sync with the live config:
if the set of local sources changes after boot, `refresh_if_stale()` can
rebuild the profiles in place to prevent mismatches between the worker's
cached view and the current configuration.
"""
import datetime as _dt

from scarlets.utils.RedisLogger import RedisLogger
from scarlet_agentic_harness import local_config


def profile_sources() -> dict:
    """
    Profile every local data source defined in the local config.

    For each `mode: local` entry, builds a profile containing row count,
    column metadata, numeric column detection, and a shape tuple
    (rows, numeric_column_count). Skips `mode: broker` entries entirely.

    Per-source failures are logged and the source is omitted from the
    result — one unreadable source must never stop a worker booting.

    Returns
    -------
    dict
        Mapping of source name to profile dict with keys:
        - "rows": int
        - "columns": list of {"name": str, "numeric": bool,
          "temporal": bool, "format": str or None, "nulls": int}
        - "numeric_columns": list of str
        - "temporal_columns": list of str
        - "shape": [rows, numeric_column_count]
        - "description": str (empty if absent in config)

    "numeric_columns" and "temporal_columns" are disjoint, and they serve
    different purposes: only numeric columns can be aggregated, because
    the matrix conversion floats every value, but any column may be
    filtered on.
    """
    profiles = {}
    for entry in local_config.load_local_config():
        if entry.get("mode") != "local":
            continue

        name = entry.get("name")
        try:
            connector = local_config.build_connector(entry)

            # Step a: get column names via list_tags
            tags = connector.list_tags()
            # tags is [{"table": "data", "columns": [...]}]
            columns_info = next((t for t in tags if t.get("table") == "data"), None)
            if not columns_info or not columns_info.get("columns"):
                RedisLogger.warning(f"profile_sources: {name!r} has no columns in list_tags")
                continue
            col_names = columns_info["columns"]

            # Step b: run one query to get row count and per-column non-null counts
            # Build: SELECT COUNT(*) AS total_rows, COUNT("col1") AS c0, ...
            count_selects = ["COUNT(*) AS total_rows"]
            for i, col in enumerate(col_names):
                count_selects.append(f'COUNT("{col}") AS c{i}')
            count_query = "SELECT " + ", ".join(count_selects) + " FROM data"
            count_result = connector.query({"query": count_query})

            if not count_result.get("rows") or not count_result["rows"][0]:
                RedisLogger.warning(f"profile_sources: {name!r} count query returned no rows")
                continue

            row_counts = count_result["rows"][0]
            total_rows = row_counts[0]
            # Map column index to non-null count
            non_null_counts = {col_names[i]: row_counts[i + 1] for i in range(len(col_names))}

            # Step c: sample up to 25 rows to infer numeric columns
            sample_query = "SELECT * FROM data LIMIT 25"
            sample_result = connector.query({"query": sample_query})
            sample_rows = sample_result.get("rows", [])
            sample_columns = sample_result.get("columns", [])

            # Determine which columns are numeric, and - only for those that
            # are not - which are temporal. The two are mutually exclusive by
            # construction: numeric needs float() to succeed, temporal needs a
            # string that parses as ISO-8601 or an already-parsed date object,
            # and no value satisfies both.
            numeric_columns = []
            temporal_columns = []
            temporal_formats = {}
            for col_idx, col_name in enumerate(sample_columns):
                if _is_numeric_column(sample_rows, col_idx):
                    numeric_columns.append(col_name)
                    continue
                fmt = _temporal_format(sample_rows, col_idx)
                if fmt is not None:
                    temporal_columns.append(col_name)
                    temporal_formats[col_name] = fmt

            # Build column metadata
            columns = []
            for col_name in col_names:
                non_null = non_null_counts.get(col_name, 0)
                nulls = total_rows - non_null if total_rows is not None else 0
                columns.append({
                    "name": col_name,
                    "numeric": col_name in numeric_columns,
                    "temporal": col_name in temporal_columns,
                    "format": temporal_formats.get(col_name),
                    "nulls": nulls
                })

            # Build profile
            profile = {
                "rows": int(total_rows) if total_rows is not None else 0,
                "columns": columns,
                "numeric_columns": numeric_columns,
                "temporal_columns": temporal_columns,
                "shape": [
                    int(total_rows) if total_rows is not None else 0,
                    len(numeric_columns)
                ],
                "description": entry.get("description", "")
            }
            profiles[name] = profile

        except Exception as exc:
            RedisLogger.warning(f"profile_sources: {name!r} failed: {exc}")

    return profiles


def _is_numeric_column(rows, col_idx):
    """
    Determine if a column is numeric based on a sample of values.

    A column is numeric if every non-None sampled value can be converted
    to float. Booleans are explicitly rejected (float(True) succeeds
    but we don't want bools counted as numeric).

    Parameters
    ----------
    rows : list of list
        Sample rows from the data.
    col_idx : int
        Index of the column to test.

    Returns
    -------
    bool
        True if the column is numeric, False otherwise.
    """
    for row in rows:
        if col_idx >= len(row):
            continue
        val = row[col_idx]
        if val is None or val == "":
            continue
        # Reject booleans explicitly
        if isinstance(val, bool):
            return False
        try:
            float(val)
        except (ValueError, TypeError):
            return False
    # If all non-None values passed, it's numeric
    # If all values were None/empty, it's NOT numeric
    has_non_null = any(
        row[col_idx] is not None and row[col_idx] != ""
        for row in rows if col_idx < len(row)
    )
    return has_non_null


def _temporal_format(rows, col_idx):
    """
    Detect whether a column holds timestamps, and in what form.

    ISO is recognised directly. A non-ISO column is accepted only when
    exactly one known pattern parses every sampled value, and the pattern
    itself is returned - that is what lets each worker cast its own column
    to the one logical instant the fleet agreed on, whatever shape it
    stores dates in.

    Ambiguity is refused rather than guessed. "03/01/2025" parses under
    both ``%m/%d/%Y`` and ``%d/%m/%Y``, and nothing in the data says which
    was meant; picking one shifts the whole series by months without ever
    erroring. An ambiguous column stays untyped, and `build_where` then
    refuses to filter on it.

    Never falls back to comparing dates as strings: lexicographic order
    agrees with chronological order for ISO and for nothing else, so
    ``'03/01/2025' >= '01/15/2026'`` is True - wrong by a year, and silent.

    Called only for columns `_is_numeric_column` already rejected, so the
    two classifications cannot both be true.

    Parameters
    ----------
    rows : list of list
        Sample rows from the data.
    col_idx : int
        Index of the column to test.

    Returns
    -------
    str or None
        ``"native"`` when the connector returned date/datetime objects,
        ``"iso"`` when every sampled value is an ISO-8601 string, a
        `strptime` pattern when exactly one known non-ISO format fits every
        value, and `None` when the column is not temporal, is ambiguous, or
        the sample was all null.
    """
    kind = None
    seen = 0
    non_iso = []
    for row in rows:
        if col_idx >= len(row):
            return None
        val = row[col_idx]
        if val is None or val == "":
            continue
        if isinstance(val, (_dt.datetime, _dt.date)):
            this = "native"
        elif isinstance(val, str):
            probe = val[:-1] + "+00:00" if val.endswith("Z") else val
            try:
                _dt.datetime.fromisoformat(probe)
                this = "iso"
            except ValueError:
                this = None  # resolved after the loop, against the whole sample
                non_iso.append(val)
        else:
            return None
        if this is None:
            continue
        if kind is not None and this != kind:
            return None
        kind = this
        seen += 1

    # Non-ISO strings are only accepted if ONE known pattern parses every
    # sampled value. Several patterns matching means the column is genuinely
    # ambiguous - "03/01/2025" is March 1st or January 3rd depending on the
    # convention, and nothing in the data says which. Guessing shifts the
    # whole series by months without erroring, so an ambiguous column stays
    # untyped and the predicate builder refuses to filter on it.
    if non_iso:
        if kind is not None:
            return None  # mixed ISO and non-ISO in one column
        matched = [f for f in _KNOWN_DATE_FORMATS
                   if all(_parses(v, f) for v in non_iso)]
        if len(matched) != 1:
            return None
        return matched[0]

    return kind if seen else None


# Tried in order, and only used when exactly one of them parses every sampled
# value. Deliberately short: each addition is another chance for two patterns
# to both match and make a column ambiguous.
_KNOWN_DATE_FORMATS = (
    "%m/%d/%Y",
    "%d/%m/%Y",
    "%m/%d/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M:%S",
    "%d-%m-%Y",
    "%d.%m.%Y",
    "%Y%m%d",
)


def _parses(value: str, fmt: str) -> bool:
    """True if `value` parses cleanly under `fmt`."""
    try:
        _dt.datetime.strptime(value, fmt)
        return True
    except (ValueError, TypeError):
        return False


def render_profile_markdown(profiles: dict) -> str:
    """
    Render a human-readable markdown summary of data profiles.

    Designed for inclusion in agent context — a compact format a language
    model can read back later.

    Parameters
    ----------
    profiles : dict
        The profiles dict returned by `profile_sources()`.

    Returns
    -------
    str
        Markdown-formatted string with one section per source.
    """
    lines = ["# Local data profile", ""]
    for name, profile in profiles.items():
        lines.append(f"## {name}")
        description = profile.get("description", "")
        if description:
            lines.append(description)
        rows = profile.get("rows", 0)
        numeric_cols = profile.get("numeric_columns", [])
        lines.append(f"- shape: {rows} x {len(numeric_cols)}  (rows x numeric columns)")
        lines.append(f"- numeric columns: {', '.join(numeric_cols)}")

        all_cols = [col["name"] for col in profile.get("columns", [])]
        non_numeric = [c for c in all_cols if c not in numeric_cols]
        lines.append(f"- non-numeric columns: {', '.join(non_numeric) if non_numeric else '(none)'}")

        # Gaps: per-column null counts
        gaps = []
        for col in profile.get("columns", []):
            if col.get("nulls", 0) > 0:
                gaps.append(f'{col["name"]}={col["nulls"]}')
        if gaps:
            lines.append(f"- gaps: {', '.join(gaps)}")
        else:
            lines.append("- gaps: (none)")

        lines.append("")  # blank line between sources

    return "\n".join(lines)


def profiles_are_stale(profiles: dict) -> bool:
    """
    Check if the provided profiles are stale relative to the live config.

    Compares the set of source names in `profiles` against the set of
    `mode: local` source names currently in `local_config.load_local_config()`.
    Re-profiling is not free (three connector queries per source), so it
    must trigger on a real structural change, not on an edited description.

    If reading the live config raises, return False and log a warning:
    an unreadable config is not evidence that the profiles are wrong, and
    re-profiling against a file we cannot read would replace good data
    with nothing.

    Parameters
    ----------
    profiles : dict
        The profiles dict returned by `profile_sources()`.

    Returns
    -------
    bool
        True if the set of source names differs from the current config,
        False otherwise (including when config read fails).
    """
    try:
        current_sources = {
            entry.get("name")
            for entry in local_config.load_local_config()
            if entry.get("mode") == "local"
        }
    except Exception as exc:
        RedisLogger.warning(f"profiles_are_stale: failed to read live config: {exc}")
        return False

    current_names = {name for name in current_sources if name is not None}
    profile_names = set(profiles.keys())

    return current_names != profile_names


def refresh_if_stale(profiles: dict) -> bool:
    """
    Rebuild profiles in place if they are stale.

    If `profiles_are_stale(profiles)` returns True, rebuild via
    `profile_sources()` and update `profiles` in place using `.clear()`
    then `.update()`. Otherwise return False without touching it.

    In place is required: the same dict object is shared between the
    worker's boot-time local, every HarnessContext built for every
    request, and the periodic refresh loop. Rebinding a new dict would
    update only the caller's reference and leave every other holder on
    the stale copy.

    Log at warning level when a refresh happens, naming the source names
    before and after. A config changing under a running worker is
    legitimate but worth seeing in the log.

    If the rebuild yields an EMPTY dict while `profiles` was non-empty,
    do NOT apply it — log a warning and return False. An empty profile
    set almost always means the config was caught mid-write, and
    replacing working profiles with nothing would turn a transient
    condition into a worker that can no longer answer anything.

    Parameters
    ----------
    profiles : dict
        The profiles dict returned by `profile_sources()`. Updated in place.

    Returns
    -------
    bool
        True if profiles were rebuilt, False otherwise.
    """
    if not profiles_are_stale(profiles):
        return False

    old_names = set(profiles.keys())
    try:
        new_profiles = profile_sources()
    except Exception as exc:
        RedisLogger.warning(f"refresh_if_stale: profile_sources raised: {exc}")
        return False

    if not new_profiles and profiles:
        RedisLogger.warning(
            f"refresh_if_stale: rebuild produced empty profiles while old profiles "
            f"had {len(profiles)} sources. Skipping update."
        )
        return False

    RedisLogger.warning(
        f"refresh_if_stale: config changed. Old sources: {sorted(old_names)}. "
        f"New sources: {sorted(new_profiles.keys())}. Refreshing in place."
    )
    profiles.clear()
    profiles.update(new_profiles)
    # Keep the readable copy in step with the structured one - see
    # write_profile_markdown's docstring for why this cannot be boot-only.
    write_profile_markdown(profiles)
    return True


def write_profile_markdown(profiles: dict) -> None:
    """
    Write the readable profile next to the worker's own config.

    Best-effort: an unwritable home is never a reason to fail a request or
    refuse to boot, because `profiles` itself is the authoritative copy and
    lives in memory regardless.

    Called from both the boot path and `refresh_if_stale`. It has to be
    both: this file is what a worker's own LLM is pointed at to recall what
    it holds, so leaving it describing sources the worker dropped an hour
    ago is worse than having no file at all.

    Parameters
    ----------
    profiles : dict
        As returned by `profile_sources`.
    """
    try:
        path = local_config.CONFIG_PATH.parent / "data_profile.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_profile_markdown(profiles))
    except Exception as exc:
        RedisLogger.warning(f"write_profile_markdown: could not write: {exc}")
