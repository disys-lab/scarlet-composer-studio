"""
InfluxConnector — adapts the real, already-existing InfluxDB usage pattern
from dockerApps/anomaly_detection and dockerApps/process_optimization (the
InfluxDB 1.x `influxdb` client's DataFrameClient, InfluxQL - not the 2.x
`influxdb-client` package/Flux, which those apps never use), not a
reimplementation.

Like MssqlConnector, this accepts a raw query string (InfluxQL, e.g.
"select speed, speed_mode from controlchart where time >= now() - 1m") -
composer-api's authorize check is what bounds who can reach this broker at
all, not a declared-tag allowlist like PiConnector's.

DataFrameClient.query() returns a dict keyed by measurement name (plain
string for an untagged/ungrouped query - the only shape the reference
apps' own queries ever produce; a `GROUP BY` tag query would key by
`(name, tags)` tuples instead, not handled here since nothing in this
codebase uses it yet), each value a DataFrame indexed by time (verified
this session against the real DataFrameClient/ResultSet parsing code,
with a synthetic InfluxDB JSON response standing in for a live server).
query() picks payload['measurement'] if given, else the query's sole
result key, else raises rather than guessing among several.
"""
from influxdb import DataFrameClient

from data_connectors.base import Connector, config_value


def _json_safe(v):
    """
    Coerce one Influx query-result value to something JSON-serializable.

    Parameters
    ----------
    v : object
        A single cell value from `DataFrameClient.query`'s result
        `DataFrame`, after resetting the time index.

    Returns
    -------
    str, int, float, bool, or None
        ISO-8601 string if `v` is a `pandas.Timestamp` (the reset time
        column); `v` unchanged if already a JSON-safe scalar type;
        `None` if `v` was `None`; `str(v)` otherwise.
    """
    if v is None:
        return None
    if hasattr(v, "isoformat"):  # pd.Timestamp (the time column, once reset from the index)
        return v.isoformat()
    if hasattr(v, "item"):  # numpy scalar
        v = v.item()
    return v if isinstance(v, (str, int, float, bool)) else str(v)


def _truthy(v) -> bool:
    """
    Interpret a config value as a boolean.

    Parameters
    ----------
    v : bool or str
        `config_value` may return a real `bool` (from a config dict a
        site engineer wrote as YAML ``true``/``false``) or a `str` (from
        an env var, which has no native bool type) - this handles both.

    Returns
    -------
    bool
    """
    return v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes")


class InfluxConnector(Connector):
    """
    `Connector` for InfluxDB 1.x via the `influxdb` package's `DataFrameClient`.

    Uses InfluxQL (the 1.x query language), not Flux/`influxdb-client`
    (the 2.x package). Accepts a raw InfluxQL query string, like the SQL
    connectors - composer-api's ``/authorize`` check is what bounds who
    can reach this broker at all, not a declared-tag allowlist (unlike
    `PiConnector`).

    Parameters
    ----------
    config : dict or None, optional
        Per-instance config dict (`local_config.py`, `mode: local`
        entries) with keys ``host``, ``port``, ``user``, ``password``,
        ``dbname``, ``ssl``, ``verify_ssl``. When `None` (the broker's
        own usage), each falls back to the matching ``INFLUXDB_*`` env
        var - see `data_connectors.base.config_value`.

    Attributes
    ----------
    client : influxdb.DataFrameClient
        The underlying Influx client used for every query.
    """

    def __init__(self, config: dict | None = None):
        self.client = DataFrameClient(
            config_value(config, "host", "INFLUXDB_HOST", required=True),
            int(config_value(config, "port", "INFLUXDB_PORT", default="8086")),
            config_value(config, "user", "INFLUXDB_USER", default="root"),
            config_value(config, "password", "INFLUXDB_PASSWORD", default="root"),
            config_value(config, "dbname", "INFLUXDB_DBNAME", required=True),
            ssl=_truthy(config_value(config, "ssl", "INFLUXDB_SSL", default="false")),
            verify_ssl=_truthy(config_value(config, "verify_ssl", "INFLUXDB_VERIFY_SSL", default="false")),
        )

    def query(self, payload: dict) -> dict:
        """
        Run a raw InfluxQL query and return one measurement's result set.

        Parameters
        ----------
        payload : dict
            Must include a ``query`` key holding the raw InfluxQL string
            (e.g. ``"select speed from controlchart where time >= now() - 1m"``).
            Optional ``measurement`` key selects which measurement's
            `DataFrame` to return when the query touches more than one;
            required in that case.

        Returns
        -------
        dict
            ``{"columns": [...], "rows": [[...], ...]}``, with a
            ``"time"`` column first (the query result's `DataFrame`
            index, reset into a regular column).

        Raises
        ------
        ValueError
            If `payload` has no ``query`` key; if ``measurement`` is
            given but the query returned no rows for it; or if the query
            touched more than one measurement and ``measurement`` wasn't
            given to disambiguate.
        """
        query = payload.get("query")
        if not query:
            raise ValueError("payload must include a 'query' string")

        result = self.client.query(query)
        if not result:
            return {"columns": [], "rows": []}

        measurement = payload.get("measurement")
        if measurement is not None:
            df = result.get(measurement)
            if df is None:
                raise ValueError(f"query did not return any rows for measurement {measurement!r}")
        elif len(result) == 1:
            df = next(iter(result.values()))
        else:
            raise ValueError(
                f"query returned {len(result)} measurements ({sorted(str(k) for k in result.keys())}) - "
                "pass 'measurement' in the payload to pick one"
            )

        df.index.name = "time"
        df = df.reset_index()
        columns = list(df.columns)
        rows = [[_json_safe(v) for v in row] for row in df.values.tolist()]
        return {"columns": columns, "rows": rows}

    def list_tags(self) -> list:
        """
        List measurements and their field names via ``SHOW MEASUREMENTS``/``SHOW FIELD KEYS``.

        Real, live schema introspection. Neither statement starts with
        ``SELECT``, so `DataFrameClient.query` hands back a raw
        `ResultSet` instead of a `DataFrame` - ``.get_points()`` is the
        `influxdb-python` idiom for reading one of those. Not the `query`
        path, so this never touches actual row data, only schema.

        Returns
        -------
        list of dict
            One entry per measurement: ``{"table": "<measurement>", "columns": [...]}``.
        """
        measurements = [p["name"] for p in self.client.query("SHOW MEASUREMENTS").get_points()]
        tags = []
        for measurement in measurements:
            # InfluxQL identifier quoting is double quotes, not a Python
            # string literal - measurement names can contain spaces/
            # special characters.
            fields = [p["fieldKey"] for p in self.client.query(f'SHOW FIELD KEYS FROM "{measurement}"').get_points()]
            tags.append({"table": measurement, "columns": fields})
        return tags
