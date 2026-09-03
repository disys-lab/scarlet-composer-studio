"""
Local site config - ~/.scarlet/config.yaml, the primary mechanism for a
worker to reach data sources a site manages itself, rather than routing
through composer-api's centralized registry/broker path. Built for
industrial multi-site deployments with real site autonomy: a plant
manager who's territorial about their own data can hand-author this file
without composer-api (or anyone off-site) ever seeing it, let alone
writing to it - there is deliberately no push path from composer-ui into
this file, ever.

File shape:
    sources:
      - name: plant_pg
        type: postgres
        mode: local
        description: "Roll speed, feed rate, surface pressure for
          PaperRoller1. Columns: roll_speed, feed_rate, pressure."
        host: 127.0.0.1
        port: 5432
        database: plant
        user: plant_reader
        password: "..."
      - name: central_erp
        type: mssql
        mode: broker
        description: "Corporate ERP inventory figures."
        broker_url: "https://broker.example.com"

Two entry modes:
  - mode: local - this worker holds the real credential itself and talks
    to the data source directly, in-process, via the matching connector
    class from data_connectors (data_connectors.postgres.PostgresConnector
    etc.) - no broker, no network hop beyond the data source itself. For
    mode: local entries, presence in this file *is* the authorization -
    there is no server-side check, deliberately (see build_connector()).
  - mode: broker - this entry only ever holds {name, type, broker_url} -
    the real credential lives in a separately-deployed broker instead
    (scarlet_composer_studio_open_source/broker/), and querying it goes
    through the existing ctx.query_data_source() HTTP path unchanged. A
    caller branches on `entry["mode"]` to pick which path to use;
    build_connector() only ever handles mode: local.

Every entry also gets a natural-language `description` - fed into agent
context (see describe_sources(), used by both the directory report and
AgentDialogue's context_fn), the same role a scarlet's own description
plays: it's the only way another agent learns what this data actually
means and how to use it.

Credentials in this file are never redacted or protected by this module -
no file-permission enforcement, deliberately (matches the convention
other local-config-holding agentic tools already use). describe_sources()
is the one function that's safe to expose off this worker: name/type/
mode/description only, never the raw entry.
"""
import os
from pathlib import Path

import yaml
from scarlets.utils.RedisLogger import RedisLogger

CONFIG_PATH = Path(
    os.environ.get("SCARLET_LOCAL_CONFIG", str(Path.home() / ".scarlet" / "config.yaml"))
)

# (type, canonical identity fields) - used only to flag potential naming
# conflicts in the aggregated directory view (Component 4): two entries
# with the same `name` but a different canonical identity are a real
# conflict worth surfacing, not something to silently pick a winner for.
_IDENTITY_FIELDS = {
    "mssql": ("server", "database"),
    "postgres": ("host", "port", "database"),
    "mysql": ("host", "port", "database"),
    "pi": ("af_server_name", "url"),
    "influx": ("host", "port", "dbname"),
    "redis": ("host", "port", "db"),
    "csv": ("path",),
    "excel": ("path", "sheet"),
}


def load_local_config() -> list[dict]:
    """
    Read this worker's local data-source config file.

    Reads ``~/.scarlet/config.yaml`` (or `SCARLET_LOCAL_CONFIG`, if set).
    Re-reads the file on every call, no caching - both the periodic
    directory report and on-demand lookups need to see a hand-edited
    file's changes without a process restart.

    Returns
    -------
    list of dict
        The file's ``sources`` list, or `[]` if the file doesn't exist -
        not an error, most workers won't have local sources at all.
    """
    if not CONFIG_PATH.exists():
        return []
    with CONFIG_PATH.open() as f:
        raw = yaml.safe_load(f) or {}
    return raw.get("sources") or []


def find_source(name: str) -> dict | None:
    """
    Look up one entry in this worker's local config by name.

    Used by `skills.query_feature`'s `contribute` to self-filter.

    Parameters
    ----------
    name : str

    Returns
    -------
    dict or None
        The matching entry, or `None` if this worker has no local source
        named `name`.
    """
    for entry in load_local_config():
        if entry.get("name") == name:
            return entry
    return None


def _connector_class(connector_type: str):
    """
    Resolve a `data_connectors.base.Connector` subclass by type name.

    Lazy import per branch, mirrors ``broker/main.py``'s own
    ``_load_connector()`` discipline exactly - a worker that only ever
    queries postgres shouldn't need `pyodbc`/`pitalk`/`influxdb`
    importable at all.

    Parameters
    ----------
    connector_type : str
        One of ``"mssql"``/``"postgres"``/``"mysql"``/``"pi"``/
        ``"influx"``/``"redis"``/``"csv"``/``"excel"``.

    Returns
    -------
    type
        The matching `Connector` subclass.

    Raises
    ------
    ValueError
        If `connector_type` isn't recognized.
    """
    if connector_type == "mssql":
        from data_connectors.mssql import MssqlConnector
        return MssqlConnector
    if connector_type == "postgres":
        from data_connectors.postgres import PostgresConnector
        return PostgresConnector
    if connector_type == "mysql":
        from data_connectors.mysql import MysqlConnector
        return MysqlConnector
    if connector_type == "pi":
        from data_connectors.pi import PiConnector
        return PiConnector
    if connector_type == "influx":
        from data_connectors.influx import InfluxConnector
        return InfluxConnector
    if connector_type == "redis":
        from data_connectors.redis_connector import RedisConnector
        return RedisConnector
    if connector_type == "csv":
        from data_connectors.csv_connector import CsvConnector
        return CsvConnector
    if connector_type == "excel":
        from data_connectors.excel_connector import ExcelConnector
        return ExcelConnector
    raise ValueError(f"unknown data source type {connector_type!r}")


def build_connector(entry: dict):
    """
    Construct a real `Connector` in-process for a `mode: local` entry.

    The exact same classes the broker uses, just constructed from this
    entry's own fields instead of from env vars (each connector's
    `__init__` accepts an optional config dict for precisely this - see
    `data_connectors.base.config_value`).

    Parameters
    ----------
    entry : dict
        A `load_local_config` entry with ``mode: local``. `mode: broker`
        entries are never turned into a `Connector` at all - the caller
        uses `HarnessContext.query_data_source` instead.

    Returns
    -------
    data_connectors.base.Connector

    Raises
    ------
    ValueError
        If ``entry["mode"] != "local"``.
    """
    if entry.get("mode") != "local":
        raise ValueError(
            f"build_connector() only handles mode: local entries "
            f"(got mode={entry.get('mode')!r} for {entry.get('name')!r})"
        )
    connector_cls = _connector_class(entry["type"])
    config = {k: v for k, v in entry.items() if k not in ("name", "type", "mode", "description")}
    return connector_cls(config=config)


def canonical_identity(entry: dict) -> tuple:
    """
    Fingerprint an entry by its real connection fields, not its human-chosen name.

    Two entries (possibly on different workers, possibly under different
    names) with the same canonical identity are provably the same
    underlying data source. Used only to annotate the directory view
    with a naming-conflict warning; never used for authorization or
    dispatch.

    Parameters
    ----------
    entry : dict
        A `load_local_config` entry.

    Returns
    -------
    tuple
        ``(connector_type, *identity_field_values)`` - identity fields
        are type-specific (e.g. `host`/`port`/`database` for postgres).
    """
    connector_type = entry.get("type")
    fields = _IDENTITY_FIELDS.get(connector_type, ())
    return (connector_type,) + tuple(entry.get(f) for f in fields)


def describe_sources(tag_cache: dict[str, list] | None = None) -> list[dict]:
    """
    Build a redacted view of every locally-configured source.

    name/type/mode/description only, never a credential field. This is
    the one function safe to expose off this worker process:
    `Buses.report_status`'s `data_sources` field (admin-facing
    directory, calls this with no `tag_cache`) and `AgentDialogue`'s
    ``context_fn`` (on-request tag discovery grounding, calls this with
    the worker's live tag cache) both use this directly.

    Parameters
    ----------
    tag_cache : dict or None, optional
        An optional ``{name: list_tags() result}`` mapping (see
        `build_tag_cache`) - when a source's name is present, its entry
        in the returned list gains a ``"tags"`` key with that real, live
        schema. Absent (the default) or missing for a given source, no
        ``"tags"`` key is added - keeps this function the single place
        the credential-redaction guarantee lives, rather than
        duplicating that logic wherever tags get merged in.

    Returns
    -------
    list of dict
        One entry per source: ``{"name", "type", "mode", "description"}``,
        plus ``"tags"`` when available from `tag_cache`.
    """
    tag_cache = tag_cache or {}
    entries = []
    for entry in load_local_config():
        name = entry.get("name")
        described = {
            "name": name,
            "type": entry.get("type"),
            "mode": entry.get("mode"),
            "description": entry.get("description", ""),
        }
        if name in tag_cache:
            described["tags"] = tag_cache[name]
        entries.append(described)
    return entries


def build_tag_cache() -> dict[str, list]:
    """
    One fresh pass over every `mode: local` entry, calling its connector's `list_tags`.

    The actual introspection work behind the cache ``__main__.py``'s
    periodic refresh loop maintains. Returns a plain dict, doesn't
    mutate anything - the caller decides how/when to swap it in (a fresh
    dict is built each cycle and the reference reassigned, not mutated
    in place, so a concurrent reader never sees a half-updated cache).

    `mode: broker` entries are skipped entirely, not attempted-and-failed
    - `list_tags` has no broker-relay path yet, so calling it for one of
    these would just log a known, expected failure on every refresh
    cycle forever.

    Returns
    -------
    dict
        ``{name: list_tags() result}`` for every `mode: local` entry
        that introspected successfully. A source that fails to
        introspect is logged (not raised) and simply absent from the
        result - one bad source (a briefly-down DB, say) must not stop
        the others from refreshing, and must not raise out of whatever
        loop calls this repeatedly (an uncaught exception there would
        kill that loop's thread permanently, taking every future refresh
        down with it).
    """
    cache: dict[str, list] = {}
    for entry in load_local_config():
        if entry.get("mode") != "local":
            continue
        name = entry.get("name")
        try:
            cache[name] = build_connector(entry).list_tags()
        except Exception as exc:
            RedisLogger.warning(f"local_config.build_tag_cache: {name!r} failed: {exc}")
    return cache
