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
}


def load_local_config() -> list[dict]:
    """
    Read ~/.scarlet/config.yaml (or SCARLET_LOCAL_CONFIG, if set) and
    return its `sources` list. A missing file returns an empty list, not
    an error - most workers won't have local sources at all. Re-reads
    the file on every call, no caching - both the periodic directory
    report (Component 4) and on-demand lookups (Component 3) need to see
    a hand-edited file's changes without a process restart.
    """
    if not CONFIG_PATH.exists():
        return []
    with CONFIG_PATH.open() as f:
        raw = yaml.safe_load(f) or {}
    return raw.get("sources") or []


def find_source(name: str) -> dict | None:
    """The one entry (if any) in this worker's local config named `name` -
    used by query_feature's contribute() to self-filter (see skills/
    query_feature.py)."""
    for entry in load_local_config():
        if entry.get("name") == name:
            return entry
    return None


def _connector_class(connector_type: str):
    # Lazy import per branch, mirrors broker/main.py's own
    # _load_connector() discipline exactly - a worker that only ever
    # queries postgres shouldn't need pyodbc/pitalk/influxdb importable
    # at all.
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
    raise ValueError(f"unknown data source type {connector_type!r}")


def build_connector(entry: dict):
    """
    Construct the real Connector (data_connectors.base.Connector subclass)
    for a mode: local entry - the exact same classes the broker uses,
    just constructed in-process from this entry's own fields instead of
    from env vars (each connector's __init__ accepts an optional config
    dict for precisely this - see data_connectors/base.py's
    config_value()). Only ever call this for entry["mode"] == "local";
    mode: broker entries are never turned into a Connector at all - the
    caller uses ctx.query_data_source(entry["name"], payload) instead.
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
    """A fingerprint derived from an entry's real connection fields, not
    its human-chosen name - two entries (possibly on different workers,
    possibly under different names) with the same canonical identity are
    provably the same underlying data source. Used only to annotate the
    directory view (Component 4) with a naming-conflict warning; never
    used for authorization or dispatch."""
    connector_type = entry.get("type")
    fields = _IDENTITY_FIELDS.get(connector_type, ())
    return (connector_type,) + tuple(entry.get(f) for f in fields)


def describe_sources() -> list[dict]:
    """
    Redacted view of every locally-configured source - name/type/mode/
    description only, never a credential field. This is the one function
    safe to expose off this worker process: report_status()'s
    `data_sources` field (Component 4, admin-facing directory) and
    AgentDialogue's context_fn (Component 5, on-request tag discovery)
    both use this directly.
    """
    return [
        {
            "name": entry.get("name"),
            "type": entry.get("type"),
            "mode": entry.get("mode"),
            "description": entry.get("description", ""),
        }
        for entry in load_local_config()
    ]
