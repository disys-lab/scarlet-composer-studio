"""
RedisConnector — a new connector (no existing reference code to adapt).
Unlike the SQL/InfluxDB connectors, Redis has no natural tabular result
shape, so query() doesn't force one: it returns {"result": <value>}
instead of {"columns": [...], "rows": [...]} - Connector.query()'s own
contract only requires a JSON-serializable dict, not a specific shape.

payload["command"] is a raw Redis command as a list of strings, e.g.
["HGETALL", "sensor:1"] or ["GET", "sensor:temp:1"] - passed straight to
redis-py's execute_command(), same open-ended-passthrough trust boundary
as the SQL connectors' raw query string (composer-api's authorize check
bounds who can reach this broker at all, not a command-type
restriction - this can issue writes too, e.g. SET/DEL, same as a SQL
connector's raw query can issue INSERT/UPDATE/DELETE).

Plain password (Redis AUTH) held entirely in this broker's own env vars,
same "never passed in from a caller, never returned to one" property
every other connector here has.

redis-py's decode_responses=True keeps replies as native str rather than
bytes; _json_safe() below still handles the handful of non-JSON-native
shapes redis-py itself returns (set for SMEMBERS/SINTER/etc., tuple in
some list contexts).
"""
from data_connectors.base import Connector, config_value


def _json_safe(v):
    """
    Recursively coerce one Redis reply value to something JSON-serializable.

    Parameters
    ----------
    v : object
        A value (or nested value) from `redis.Redis.execute_command`'s
        reply. With ``decode_responses=True``, replies are already
        native `str` rather than `bytes` in the common case; this still
        handles the non-JSON-native shapes redis-py returns for some
        commands (`set` for ``SMEMBERS``/``SINTER``/etc., `tuple` in
        some list contexts) and raw `bytes` as a fallback.

    Returns
    -------
    object
        `v` unchanged if already `None`/`str`/`int`/`float`/`bool`; a
        `list` (recursively coerced) if `v` was a `list`/`tuple`/`set`;
        a `dict` (recursively coerced) if `v` was a `dict`; a decoded
        `str` if `v` was `bytes`; `str(v)` otherwise.
    """
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, (list, tuple, set)):
        return [_json_safe(x) for x in v]
    if isinstance(v, dict):
        return {k: _json_safe(x) for k, x in v.items()}
    if isinstance(v, bytes):
        return v.decode("utf-8", errors="replace")
    return str(v)


class RedisConnector(Connector):
    """
    `Connector` for Redis, raw command passthrough via `redis-py`.

    Unlike the SQL/InfluxDB connectors, Redis has no natural tabular
    result shape, so `query` doesn't force one - it returns
    ``{"result": <value>}`` rather than ``{"columns": [...], "rows": [...]}``;
    `Connector.query`'s own contract only requires a JSON-serializable
    dict, not a specific shape. No query-type restriction is enforced -
    this can issue writes too (``SET``/``DEL``), same as a SQL
    connector's raw query can issue ``INSERT``/``UPDATE``/``DELETE``.
    Does not override `list_tags` - Redis has no fixed schema to
    introspect, so the base `Connector.list_tags` (raises
    `NotImplementedError`) applies.

    Parameters
    ----------
    config : dict or None, optional
        Per-instance config dict (`local_config.py`, `mode: local`
        entries) with keys ``host``, ``port``, ``password``, ``db``.
        When `None` (the broker's own usage), each falls back to the
        matching ``REDIS_*`` env var - see
        `data_connectors.base.config_value`.

    Attributes
    ----------
    client : redis.Redis
        The underlying Redis client used for every command.
    """

    def __init__(self, config: dict | None = None):
        import redis
        self.client = redis.Redis(
            host=config_value(config, "host", "REDIS_HOST", required=True),
            port=int(config_value(config, "port", "REDIS_PORT", default="6379")),
            password=config_value(config, "password", "REDIS_PASSWORD") or None,
            db=int(config_value(config, "db", "REDIS_DB", default="0")),
            decode_responses=True,
        )

    def query(self, payload: dict) -> dict:
        """
        Execute a raw Redis command and return its reply.

        Parameters
        ----------
        payload : dict
            Must include a ``command`` key: a list of strings forming
            one Redis command, e.g. ``["HGETALL", "sensor:1"]`` or
            ``["GET", "sensor:temp:1"]`` - passed straight to
            `redis.Redis.execute_command`.

        Returns
        -------
        dict
            ``{"result": <reply>}``, with the reply coerced to a
            JSON-serializable shape by `_json_safe`.

        Raises
        ------
        ValueError
            If `payload` has no ``command`` key, or it isn't a list.
        """
        command = payload.get("command")
        if not command or not isinstance(command, list):
            raise ValueError('payload must include a "command" list, e.g. ["GET", "mykey"]')

        result = self.client.execute_command(*command)
        return {"result": _json_safe(result)}
