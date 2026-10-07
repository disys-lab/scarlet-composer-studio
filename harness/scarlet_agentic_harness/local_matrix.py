"""
Worker-local matrix generation - a worker turns a broad objective into a
2-D numeric matrix drawn from its own local data, deciding for itself
which source to read and writing its own SQL.

This module replaces the retired `local_numbers()` function, which read a
single `CSV_PATH` env var with a hardcoded "SELECT value FROM data". All
data access now goes through `local_config.build_connector(entry)` and
its `.query({"query": ...})` method. The SQL table is always named
`data`.

Public API
----------
choose_source(ctx, objective) -> str | None
    Pick which of this worker's own sources to read.
generate_sql(ctx, source_name, objective) -> str
    Ask the LLM to write ONE SQL SELECT over the table `data`.
load_local_matrix(ctx, objective) -> tuple
    Returns `(matrix, meta)` where matrix is a 2-D numpy array of
    float64 and meta is a dict with keys "source", "sql", "columns",
    "rows_returned", "rows_dropped", "shape".
"""
import re
from typing import Any

import numpy as np
from scarlet_agentic_harness import local_config
from scarlet_agentic_harness import data_profile
from scarlet_agentic_harness.skills import predicate
from scarlets.utils.RedisLogger import RedisLogger


def choose_source(ctx: Any, objective: str) -> str | None:
    """
    Pick which of this worker's own sources to read.

    Parameters
    ----------
    ctx : Any
        The harness context. Must have `data_profiles` (dict) and
        optionally `llm_client`.
    objective : str
        The worker's objective text.

    Returns
    -------
    str or None
        The chosen source name, or `None` if there are no profiles at
        all.
    """
    profiles = ctx.data_profiles
    if not profiles:
        return None

    if len(profiles) == 1:
        return next(iter(profiles.keys()))

    # More than one profile: ask the LLM to choose.
    if ctx.llm_client is None:
        # Fallback to heuristic when no LLM is available
        return _fallback_source(profiles)

    # Build a compact listing for the prompt.
    source_info = []
    for name, profile in profiles.items():
        source_info.append(
            f"- {name}: {profile.get('description', '')} "
            f"(shape={profile.get('shape', 'unknown')}, "
            f"numeric_columns={profile.get('numeric_columns', [])})"
        )
    listing = "\n".join(source_info)

    prompt = (
        f"Choose ONE source name from the list below that best serves "
        f"the objective: {objective}\n\n"
        f"{listing}\n\n"
        f"Return ONLY the chosen source name, nothing else."
    )

    try:
        reply = ctx.llm_client.chat([{"role": "user", "content": prompt}])
        chosen = (reply.get("content") or "").strip()
    except Exception as exc:
        RedisLogger.warning(f"choose_source LLM call failed: {exc}")
        return _fallback_source(profiles)

    if chosen in profiles:
        return chosen

    # Fallback if the model didn't return a valid name
    RedisLogger.warning(
        f"LLM chose {chosen!r} which is not a known source; "
        f"falling back to heuristic."
    )
    return _fallback_source(profiles)


def _fallback_source(profiles: dict) -> str:
    """Return the source with most numeric columns, tie-break by rows, then name."""
    # Sort key: (-numeric_columns count, -rows, name)
    def sort_key(name: str) -> tuple:
        profile = profiles[name]
        num_cols = len(profile.get("numeric_columns") or [])
        rows = profile.get("rows", 0)
        return (-num_cols, -rows, name)

    return sorted(profiles.keys(), key=sort_key)[0]


def generate_sql(ctx: Any, source_name: str, objective: str) -> str:
    """
    Ask `ctx.llm_client` to write ONE SQL SELECT over the table `data`
    that pulls the numeric columns needed for the objective.

    Parameters
    ----------
    ctx : Any
        The harness context. Must have `data_profiles` and `llm_client`.
    source_name : str
        The name of the source to query.
    objective : str
        The worker's objective text.

    Returns
    -------
    str
        The validated SQL query string.

    Raises
    ------
    ValueError
        If `ctx.llm_client` is None, or if the generated query fails
        validation.
    """
    if ctx.llm_client is None:
        raise ValueError(
            "worker-local SQL generation requires an LLM backend "
            "(ctx.llm_client is None)"
        )

    profile = ctx.data_profiles.get(source_name)
    if not profile:
        raise ValueError(f"unknown source {source_name!r}")

    columns = profile.get("numeric_columns") or []
    row_count = profile.get("rows", 0)

    prompt = (
        f"Write ONE SQL SELECT statement over the table `data` that "
        f"pulls the numeric columns needed for the objective: {objective}\n\n"
        f"Table: data\n"
        f"Row count: {row_count}\n"
        f"Numeric columns: {columns}\n\n"
        f"Requirements:\n"
        f"- Return only the SQL, nothing else.\n"
        f"- The table is always named `data`.\n"
        f"- Only select numeric columns.\n"
        f"- Do not include any non-SELECT statements."
    )

    try:
        reply = ctx.llm_client.chat([{"role": "user", "content": prompt}])
        query = (reply.get("content") or "").strip()
    except Exception as exc:
        raise ValueError(f"SQL generation LLM call failed: {exc}")

    return _validate_sql(query)


def _validate_sql(query: str) -> str:
    """
    Validate the SQL query and return it, or raise ValueError.

    Rules:
    - Single statement (no ';' except optional trailing ';')
    - Starts with SELECT (case-insensitive)
    - Contains ' FROM data' (case-insensitive)
    - No forbidden keywords (INSERT, UPDATE, DELETE, DROP, ALTER,
      CREATE, ATTACH, COPY, PRAGMA, EXPORT, INSTALL, LOAD)

    Parameters
    ----------
    query : str
        The SQL query string.

    Returns
    -------
    str
        The cleaned query (trailing semicolon stripped).

    Raises
    ------
    ValueError
        If validation fails, with a clear message naming the rule broken.
    """
    # Strip trailing semicolon if present
    if query.endswith(";"):
        query = query[:-1].strip()

    # Rule 1: must start with SELECT
    if not re.match(r"^\s*SELECT\s", query, re.IGNORECASE):
        raise ValueError(
            f"SQL query must start with SELECT: {query!r}"
        )

    # Rule 2: must contain ' FROM data' (case-insensitive)
    # Match 'data' as a whole word, allowing end of string, whitespace, semicolon, or closing paren
    if not re.search(r"\sFROM\s+data(?:\s|$|;|\))", query, re.IGNORECASE):
        raise ValueError(
            f"SQL query must contain ' FROM data': {query!r}"
        )

    # Rule 3: no forbidden keywords (word-boundary match)
    # Removed LOAD and COPY as they are plausible column names
    forbidden = (
        r"\bINSERT\b|\bUPDATE\b|\bDELETE\b|\bDROP\b|\bALTER\b"
        r"|\bCREATE\b|\bATTACH\b|\bPRAGMA\b"
        r"|\bEXPORT\b|\bINSTALL\b"
    )
    if re.search(forbidden, query, re.IGNORECASE):
        raise ValueError(
            f"SQL query contains forbidden keyword: {query!r}"
        )

    return query


def load_local_matrix(ctx: Any, objective: str, columns: list | None = None,
                      conditions: list | None = None) -> tuple:
    """
    Load a 2-D numeric matrix from the worker's local data.

    Steps:
    1. choose_source
    2. generate_sql
    3. build the connector and run the query
    4. convert to numpy array with explicit row-dropping rules

    Parameters
    ----------
    ctx : Any
        The harness context.
    objective : str
        The worker's objective text.
    columns : list of str or None, optional
        The agreed column list. When given, the SELECT list is built from
        it rather than generated, so every worker returns the same columns
        in the same order.
    conditions : list of dict or None, optional
        Structured row filter, each ``{"column", "op", "value"}``, combined
        with AND by `skills.predicate.build_where`. Settled once by the
        caller and passed to every worker unchanged - a predicate applied
        by some workers and not others silently answers a different
        question. `None` or empty reads every row.

    Returns
    -------
    tuple
        `(matrix, meta)` where:
        - matrix: 2-D numpy array of float64, shape (rows, cols)
        - meta: dict with keys "source", "sql", "columns", "rows_returned",
          "rows_dropped", "shape", "rows_matched", "filtered"

        `rows_matched` is how many rows the filter admitted before
        conversion. A worker that matched nothing returns an empty matrix
        with ``rows_matched == 0`` rather than raising - see below.

    Raises
    ------
    ValueError
        If choose_source returns None, if the filter names a column this
        worker does not have, or if rows were matched but none survived
        conversion to float. Matching no rows at all is NOT an error: an
        empty window is an ordinary outcome once filtering exists, and the
        caller needs to tell "nothing in range here" apart from "this
        worker is broken".
    """
    # Profiles are built once at boot, but local_config re-reads the file on
    # every call - so a config rewritten underneath a running worker (which
    # is what happens every time a notebook regenerates its data) leaves the
    # two views disagreeing. Choosing from stale profiles then failed with
    # "source 'x' not found in local config", naming a source the worker
    # itself had proposed. Detect that and re-profile rather than making an
    # operator guess that a restart was required.
    data_profile.refresh_if_stale(ctx.data_profiles)

    source_name = choose_source(ctx, objective)
    if source_name is None:
        raise ValueError(
            "this worker has no profiled local sources "
            "(choose_source returned None)"
        )

    if columns:
        # A consensus round has already agreed exactly which columns every
        # worker will contribute, so the query is fully determined and is
        # built here rather than generated. This is still worker-local - the
        # head never named these columns, the workers agreed them among
        # themselves - but spending an LLM call to re-derive a list we were
        # just handed would only add latency and a chance to deviate from
        # the agreement, which would break aggregation.
        #
        # Column order follows the agreed list, not the file's own order, so
        # every worker's matrix has the same column in the same position.
        # Without that, the sums would align by accident at best.
        quoted = ", ".join('"' + c.replace('"', '""') + '"' for c in columns)
        sql = _validate_sql(f"SELECT {quoted} FROM data")
    else:
        sql = generate_sql(ctx, source_name, objective)

    # The filter is appended after the SELECT is settled, by the same code
    # on every worker, from conditions the caller fixed once. The LLM never
    # writes this clause - see skills.predicate for why that matters.
    #
    # The columns we may filter on are not the columns we may aggregate.
    # Aggregation is numeric-only because _convert_to_matrix floats every
    # value, but a time window filters on a timestamp, which is never
    # numeric. So this validates against the profile's full column list,
    # not against `columns` above.
    where = ""
    if conditions:
        profile = ctx.data_profiles.get(source_name) or {}
        where = predicate.build_where(conditions, profile)
        sql = sql + where

    entry = local_config.find_source(source_name)
    if entry is None:
        raise ValueError(f"source {source_name!r} not found in local config")

    connector = local_config.build_connector(entry)
    result = connector.query({"query": sql})

    # Extract columns and rows from result
    # Expecting result to have 'columns' and 'rows' keys
    columns = result.get("columns", [])
    rows = result.get("rows", [])

    # Convert to numpy array with explicit row-dropping rules
    matrix, rows_dropped = _convert_to_matrix(rows, len(columns))

    # Two different empties, and conflating them hides a real failure.
    #
    # The filter matching nothing is an ordinary outcome once row filtering
    # exists - a window this worker simply has no readings for. It returns
    # an empty matrix and lets the caller see rows_matched == 0, so an
    # empty window reads as "nothing here" rather than as a broken worker,
    # and never contributes a silent zero to an average.
    #
    # Rows coming back that then all fail conversion is still an error:
    # the worker matched data it cannot turn into numbers.
    if matrix.shape[0] == 0 and rows:
        raise ValueError(
            f"no rows survived conversion for source {source_name!r} "
            f"with query {sql!r}"
        )

    meta = {
        "source": source_name,
        "sql": sql,
        "columns": columns,
        "rows_returned": matrix.shape[0],
        "rows_dropped": rows_dropped,
        "rows_matched": len(rows),
        "filtered": bool(where),
        "where": where,
        "sql_source": "agreed_columns" if columns else "llm",
        "shape": matrix.shape,
    }

    return matrix, meta


def _convert_to_matrix(rows: list, num_cols: int) -> tuple:
    """
    Convert raw rows to a 2-D numpy array of float64.

    Every value must convert with float(). A row containing any value
    that does not convert, or that is None/empty, is DROPPED.
    Non-finite values (NaN, inf) count as undroppable-to-float too:
    drop those rows as well.

    Parameters
    ----------
    rows : list
        List of row tuples/lists from the query result.
    num_cols : int
        Expected number of columns.

    Returns
    -------
    tuple
        `(matrix, rows_dropped)` where matrix is a 2-D numpy array of
        float64, and rows_dropped is the count of dropped rows.
    """
    if not rows:
        return np.empty((0, num_cols), dtype=np.float64), 0

    valid_rows = []
    rows_dropped = 0

    for row in rows:
        if len(row) != num_cols:
            rows_dropped += 1
            continue

        converted = []
        valid = True
        for val in row:
            if val is None or val == "":
                valid = False
                break
            try:
                f = float(val)
                if not np.isfinite(f):
                    valid = False
                    break
                converted.append(f)
            except (TypeError, ValueError):
                valid = False
                break

        if valid:
            valid_rows.append(converted)
        else:
            rows_dropped += 1

    if not valid_rows:
        return np.empty((0, num_cols), dtype=np.float64), rows_dropped

    matrix = np.array(valid_rows, dtype=np.float64)

    # Ensure 2-D shape
    if matrix.ndim == 1:
        matrix = matrix.reshape(-1, 1)

    return matrix, rows_dropped
