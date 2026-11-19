"""
predicate — build SQL WHERE clauses from structured filter conditions.

The predicate originates at the head, from the question being asked - a time
window is in the user's words, not in anyone's data, so no worker can propose
one. It is settled once and broadcast, then each worker builds its own clause
from it here, against its own profile.

The LLM emits conditions as plain dicts - {"column": ..., "op": ..., "value":
...} - and never writes SQL. That is the whole point: an operator drawn from a
whitelist, a column checked against the profile, and a value parsed before it
is formatted leave no room for an injected or malformed clause, and the
condition can be inspected before anything runs.

Every failure raises ValueError with a message that names the rule that was
broken, so callers can distinguish "unknown column" from "bad operator" or
"type mismatch" and surface precise error text to the user.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional


OPS: Dict[str, str] = {
    "gt": ">",
    "gte": ">=",
    "lt": "<",
    "lte": "<=",
    "eq": "=",
    "ne": "!=",
}


# The JSON-schema fragment every filterable skill advertises, defined once so
# four copies cannot drift apart. A compound skill must declare it too: the
# plan runner seeds its namespace with the compound's own params and spreads
# them into every step, so propagation is automatic - but the head will never
# pass a parameter the tool schema does not mention.
CONDITIONS_SCHEMA: Dict[str, Any] = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "column": {"type": "string"},
            "op": {"type": "string", "enum": sorted(OPS)},
            "value": {},
        },
        "required": ["column", "op", "value"],
    },
    "description": (
        "Row filter. Every worker applies exactly these conditions, combined "
        "with AND. Omit to read every row. Give the value as a plain number for "
        "a numeric column and as an ISO-8601 timestamp (\"2026-01-01T00:00:00\") "
        "for a time column - do NOT write SQL here. A half-open window is the "
        "usual shape: gte the start and lt the end. Pass the same conditions to "
        "every call that contributes to one answer: if one worker filters and "
        "another does not, the totals are two different questions added together "
        "and the result looks entirely plausible."
    ),
}


def _parse_timestamp(column: str, value: Any) -> datetime:
    """
    Parse an ISO-8601 value, or raise naming the column.

    Only ISO is accepted, and nothing falls back to a string comparison:
    lexicographic order agrees with chronological order for ISO and for
    nothing else, so a tolerated "03/01/2025" would compare as later than
    "01/15/2026" and be wrong by a year without erroring.

    Parameters
    ----------
    column : str
        Named in the error message so the caller knows which one failed.
    value : Any
        Coerced with `str` before parsing. A trailing ``Z`` is accepted.

    Returns
    -------
    datetime.datetime

    Raises
    ------
    ValueError
        If the value is not valid ISO-8601.
    """
    val_str = str(value)
    if val_str.endswith("Z"):
        val_str = val_str[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(val_str)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"temporal column '{column}' value {value!r} is not valid ISO-8601"
        ) from exc


def _quote_ident(column: str) -> str:
    """
    Double-quote a column identifier, doubling any internal double quote.

    Parameters
    ----------
    column : str
        The column name as it appears in the profile.

    Returns
    -------
    str
        The quoted identifier, safe to interpolate into SQL.
    """
    return '"' + column.replace('"', '""') + '"'


def build_where(conditions: Optional[List[Dict[str, Any]]], profile: Dict[str, Any]) -> str:
    """
    Build a SQL WHERE clause from structured filter conditions.

    Parameters
    ----------
    conditions : list of dict, optional
        Each dict must contain keys ``"column"``, ``"op"``, and ``"value"``.
        ``"column"`` is the column name, ``"op"`` is one of the keys in
        ``OPS``, and ``"value"`` is the comparison value. ``None`` or an
        empty list is allowed and returns ``""``.
    profile : dict
        Data profile produced by ``data_profile.profile_sources``. Must
        contain a ``"columns"`` key mapping to a list of column metadata
        dicts, each with keys ``"name"``, ``"numeric"`` (bool), and
        ``"temporal"`` (bool, defaults to False if missing).

    Returns
    -------
    str
        An empty string when ``conditions`` is ``None`` or empty; otherwise a
        string starting with exactly one space, e.g.
        ``' WHERE "col1" > 1.0 AND "col2" = \'value\''``.

    Raises
    ------
    ValueError
        - If an operator is not in ``OPS``, naming the bad operator and the
          allowed ones.
        - If a column is not present in ``profile["columns"]``, with the
          phrase "does not have column" in the message.
        - If a numeric column receives a non-numeric value or a bool.
        - If a temporal column receives a value that does not parse as
          ISO-8601.
        - If a text column's value cannot be safely quoted.
    """
    if not conditions:
        return ""

    columns = profile.get("columns", [])
    column_map = {col["name"]: col for col in columns}

    clauses = []
    for cond in conditions:
        column = cond.get("column")
        op = cond.get("op")
        value = cond.get("value")

        # Rule 1: Unknown operator
        if op not in OPS:
            raise ValueError(
                f"unknown operator '{op}' - allowed: {', '.join(sorted(OPS.keys()))}"
            )

        # Rule 2: Column not present in profile
        if column not in column_map:
            raise ValueError(f"worker does not have column '{column}'")

        col_meta = column_map[column]
        is_numeric = col_meta.get("numeric", False)
        is_temporal = col_meta.get("temporal", False)

        # Rule 3: Numeric column
        if is_numeric:
            if isinstance(value, bool):
                raise ValueError(
                    f"numeric column '{column}' received a boolean value {value!r} - "
                    "booleans are not accepted for numeric columns"
                )
            try:
                float_val = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"numeric column '{column}' value {value!r} cannot be converted to float"
                ) from exc
            literal = repr(float_val)
            clauses.append(f"{_quote_ident(column)} {OPS[op]} {literal}")
            continue

        # Rule 4: Temporal column
        if is_temporal:
            parsed = _parse_timestamp(column, value)
            literal = f"TIMESTAMP '{parsed.isoformat(sep=' ')}'"
            # Each worker casts its own column to the agreed instant. The
            # window is one logical window for the whole fleet; the SQL that
            # implements it differs per worker, because a worker storing
            # "%d/%m/%Y" has to say so explicitly - duckdb cannot infer it,
            # and a plain CAST would reject or misread it.
            fmt = col_meta.get("format")
            if fmt and fmt not in ("iso", "native"):
                col_expr = f"strptime({_quote_ident(column)}, '{fmt}')"
                clauses.append(f"{col_expr} {OPS[op]} {literal}")
                continue
            # The column side is cast too, not just the literal. A CSV read
            # through pandas hands duckdb a VARCHAR column, and comparing
            # VARCHAR to TIMESTAMP is a binder error - duckdb refuses rather
            # than quietly falling back to a string comparison, which is the
            # behaviour we want and the reason this cast is explicit. Casting
            # a column that is already a native timestamp is a no-op.
            clauses.append(
                f"CAST({_quote_ident(column)} AS TIMESTAMP) {OPS[op]} {literal}"
            )
            continue

        # Rule 5: Text column (neither numeric nor temporal)
        # Escape single quotes by doubling them
        str_val = str(value)
        escaped = str_val.replace("'", "''")
        literal = f"'{escaped}'"
        clauses.append(f"{_quote_ident(column)} {OPS[op]} {literal}")

    if not clauses:
        return ""

    return " WHERE " + " AND ".join(clauses)


# --- other connector dialects ----------------------------------------------
#
# Groundwork, untested against live services by design - the connectors get
# their own sprint. The point is that it is possible at all: a structured
# condition can be rendered in each connector's own dialect, where raw SQL
# from the LLM could never have targeted Flux or PI.
#
# Redis is absent deliberately. Its payload is a raw command list with
# nowhere to put a predicate.

def render_flux(conditions, profile) -> str:
    """
    Render conditions as InfluxDB Flux pipeline stages.

    Temporal conditions become a ``range()`` call, because Flux wants the
    time bound there rather than in a filter; everything else becomes a
    ``filter()``.

    Parameters
    ----------
    conditions : list of dict or None
    profile : dict
        As `build_where`.

    Returns
    -------
    str
        Flux stages, newline-separated and each beginning ``|>``. Empty
        string when there are no conditions.

    Raises
    ------
    ValueError
        Same rules as `build_where` - unknown operator, unknown column,
        unparseable value.
    """
    if not conditions:
        return ""

    column_map = {c["name"]: c for c in profile.get("columns", [])}
    start = stop = None
    filters = []

    for cond in conditions:
        column, op, value = cond.get("column"), cond.get("op"), cond.get("value")
        if op not in OPS:
            raise ValueError(
                f"unknown operator '{op}' - allowed: {', '.join(sorted(OPS))}")
        if column not in column_map:
            raise ValueError(f"worker does not have column '{column}'")

        if column_map[column].get("temporal", False):
            parsed = _parse_timestamp(column, value)
            iso = parsed.isoformat()
            if op in ("gt", "gte"):
                start = iso
            elif op in ("lt", "lte"):
                stop = iso
            else:
                raise ValueError(
                    f"Flux range() takes a lower and an upper bound; "
                    f"operator '{op}' on time column '{column}' has no "
                    f"equivalent")
            continue

        if column_map[column].get("numeric", False):
            if isinstance(value, bool):
                raise ValueError(f"numeric column '{column}' received a bool")
            literal = repr(float(value))
        else:
            literal = '"' + str(value).replace('"', '\\"') + '"'
        filters.append(f'r["{column}"] {OPS[op]} {literal}')

    stages = []
    if start or stop:
        bounds = []
        bounds.append(f"start: {start}" if start else "start: 0")
        if stop:
            bounds.append(f"stop: {stop}")
        stages.append(f"|> range({', '.join(bounds)})")
    for f in filters:
        stages.append(f"|> filter(fn: (r) => {f})")
    return "\n".join(stages)


def render_pi(conditions, profile) -> dict:
    """
    Render conditions as PI's native ``start_time`` / ``end_time`` payload.

    PI has no SQL and no general predicate - `PiConnector.query` takes a
    tag name and a time range. A time window maps onto it exactly; nothing
    else does, so anything else raises rather than being silently dropped.

    Parameters
    ----------
    conditions : list of dict or None
    profile : dict
        As `build_where`.

    Returns
    -------
    dict
        ``{"start_time": ..., "end_time": ...}``, either key omitted when
        that bound was not given. Empty dict when there are no conditions.

    Raises
    ------
    ValueError
        If a condition is not a bound on a temporal column - PI cannot
        express it, and answering without it would answer a different
        question.
    """
    if not conditions:
        return {}

    column_map = {c["name"]: c for c in profile.get("columns", [])}
    out = {}
    for cond in conditions:
        column, op, value = cond.get("column"), cond.get("op"), cond.get("value")
        if column not in column_map:
            raise ValueError(f"worker does not have column '{column}'")
        if not column_map[column].get("temporal", False):
            raise ValueError(
                f"a PI source can only be filtered by time; '{column}' is not "
                f"a time column and PI has no way to express this condition")
        parsed = _parse_timestamp(column, value)
        if op in ("gt", "gte"):
            out["start_time"] = parsed.isoformat()
        elif op in ("lt", "lte"):
            out["end_time"] = parsed.isoformat()
        else:
            raise ValueError(
                f"a PI time range takes bounds; operator '{op}' has no "
                f"equivalent")
    return out
