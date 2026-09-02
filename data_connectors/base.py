"""
Connector — the pluggable interface every data-source-specific connector
implements. The broker itself (main.py) never knows about SQL, PI, Redis,
etc. directly - it only ever calls .query(payload) on whichever Connector
its own deployment is configured with (BROKER_CONNECTOR_TYPE env var,
see main.py's _load_connector()).

query() takes a caller-supplied payload and returns a plain JSON-
serializable dict - the *result*, not the credential, not the connection.
The credential this connector uses lives entirely in its own __init__ -
never passed in from a caller, never returned to one. Two callers
construct these: the broker (main.py's _load_connector(), no config dict -
falls back to this process's own env vars, exactly as before) and
scarlet-agentic-harness's local_config.build_connector() (a real config
dict, one per ~/.scarlet/config.yaml entry, needed since a single worker
process can hold more than one local source of the same type - env vars
alone can't disambiguate two local Postgres entries on one worker).
"""
import math
import os
from abc import ABC, abstractmethod


class Connector(ABC):
    @abstractmethod
    def query(self, payload: dict) -> dict:
        """Execute payload's query against this connector's configured data
        source and return a JSON-serializable result. Raise on failure -
        main.py's /query handler turns that into a clean error response,
        never a raw stack trace."""
        ...


def config_value(config: dict | None, key: str, env_var: str, default=None, required: bool = False):
    """
    Read `key` from a per-instance config dict if given, else fall back to
    this process's own env var `env_var` - the one seam every connector's
    __init__ uses to support both callers described above without
    duplicating the same fallback logic six times.
    """
    value = (config or {}).get(key)
    if value is None:
        value = os.environ.get(env_var, default)
    if required and value is None:
        raise ValueError(f"{key!r} is required - set it in the config dict, or the {env_var} env var")
    return value


def json_safe(v):
    """
    Coerce one query-result value to something JSON-serializable - shared
    by every connector that hands back a pandas/numpy-derived value
    (csv_connector.py, excel_connector.py; the others' own driver types
    are narrow enough to coerce inline). NaN (pandas' own representation
    for a missing cell) becomes None, same as every connector's existing
    None-for-missing convention - confirmed via a real duckdb/pandas
    round-trip that this needs to be explicit, not already JSON-safe.
    """
    if v is None:
        return None
    if hasattr(v, "item"):  # numpy scalar
        v = v.item()
    if isinstance(v, float) and math.isnan(v):
        return None
    return v if isinstance(v, (str, int, float, bool)) else str(v)
