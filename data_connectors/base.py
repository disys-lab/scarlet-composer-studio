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
    """
    Pluggable interface every data-source-specific connector implements.

    The broker (``main.py``) never knows about SQL, PI, Redis, etc.
    directly - it only ever calls ``.query(payload)`` on whichever
    `Connector` its own deployment is configured with
    (``BROKER_CONNECTOR_TYPE`` env var, see ``main.py``'s
    ``_load_connector()``).

    The credential a connector uses lives entirely in its own
    ``__init__`` - never passed in from a caller, never returned to one.
    Two callers construct connectors: the broker (``main.py``'s
    ``_load_connector()``, no config dict - falls back to this process's
    own env vars) and ``scarlet_agentic_harness``'s
    ``local_config.build_connector()`` (a real config dict, one per
    ``~/.scarlet/config.yaml`` entry, needed since a single worker
    process can hold more than one local source of the same type - env
    vars alone can't disambiguate two local Postgres entries on one
    worker).
    """

    @abstractmethod
    def query(self, payload: dict) -> dict:
        """
        Execute a query against this connector's configured data source.

        Parameters
        ----------
        payload : dict
            Caller-supplied query payload. Shape is connector-specific
            (e.g. a raw SQL string for `mssql`/`postgres`/`mysql`, a tag
            list + time range for `pi`/`influx`).

        Returns
        -------
        dict
            The query result - not the credential, not the connection.
            JSON-serializable.

        Raises
        ------
        Exception
            On any failure executing the query. ``main.py``'s ``/query``
            handler turns this into a clean error response, never a raw
            stack trace - subclasses don't need to catch and reformat
            their own driver exceptions.
        """
        ...

    def list_tags(self) -> list:
        """
        Real, live schema/tag introspection for this connector's data source.

        E.g. table/column names for a SQL connector, the declared tag
        list for PI. Not abstract: unlike `query`, this doesn't map
        cleanly onto every connector type (Redis has no fixed schema), so
        the default implementation raises rather than forcing every
        subclass to implement something meaningless for it. A subclass
        that supports introspection overrides this; one that doesn't is
        left alone.

        This is the "dynamic" half of tag discovery - see
        ``scarlet_agentic_harness``'s ``skills/list_tags.py`` (any agent
        can ask for this on demand, given a source name) and
        ``__main__.py``'s periodic tag-cache refresh (feeds
        `AgentDialogue`'s ``context_fn``, so a responder's grounding
        reflects what's actually there, not just a hand-written
        description).

        Returns
        -------
        list
            Tag/column/table names available on this data source.

        Raises
        ------
        NotImplementedError
            If this connector type doesn't support schema introspection.
        """
        raise NotImplementedError(f"{type(self).__name__} does not support list_tags()")


def config_value(config: dict | None, key: str, env_var: str, default=None, required: bool = False):
    """
    Resolve one connector setting from a config dict, falling back to an env var.

    The one seam every connector's ``__init__`` uses to support both
    `Connector` callers (broker: env-var-only; harness local mode: a real
    per-instance config dict) without duplicating the same fallback logic
    in every connector.

    Parameters
    ----------
    config : dict or None
        Per-instance config dict (a `local_config.py` entry), or `None`
        to read only from the environment.
    key : str
        Key to look up in `config`.
    env_var : str
        Environment variable to fall back to when `config` is `None` or
        doesn't have `key`.
    default : optional
        Value to use if neither `config` nor the environment has a value.
    required : bool, optional
        If `True`, raise when no value is found anywhere. Default `False`.

    Returns
    -------
    object
        The resolved value, or `default`.

    Raises
    ------
    ValueError
        If `required` is `True` and no value was found in `config`, the
        environment, or `default`.
    """
    value = (config or {}).get(key)
    if value is None:
        value = os.environ.get(env_var, default)
    if required and value is None:
        raise ValueError(f"{key!r} is required - set it in the config dict, or the {env_var} env var")
    return value


def json_safe(v):
    """
    Coerce one query-result value to something JSON-serializable.

    Shared by every connector that hands back a pandas/numpy-derived
    value (`csv_connector.py`, `excel_connector.py`; the other
    connectors' own driver types are narrow enough to coerce inline).
    NaN (pandas' own representation for a missing cell) becomes `None`,
    matching every connector's existing None-for-missing convention -
    confirmed via a real duckdb/pandas round-trip that this needs to be
    explicit, not already JSON-safe.

    Parameters
    ----------
    v : object
        A single cell/scalar value from a query result.

    Returns
    -------
    str, int, float, bool, or None
        `v` unchanged if already a JSON-safe scalar type; `None` if `v`
        was `None` or NaN; `str(v)` otherwise.
    """
    if v is None:
        return None
    if hasattr(v, "item"):  # numpy scalar
        v = v.item()
    if isinstance(v, float) and math.isnan(v):
        return None
    return v if isinstance(v, (str, int, float, bool)) else str(v)
