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
    if v is None:
        return None
    if hasattr(v, "isoformat"):  # pd.Timestamp (the time column, once reset from the index)
        return v.isoformat()
    if hasattr(v, "item"):  # numpy scalar
        v = v.item()
    return v if isinstance(v, (str, int, float, bool)) else str(v)


def _truthy(v) -> bool:
    # config_value() may return a real bool (from a config dict a site
    # engineer wrote as YAML `true`/`false`) or a string (from an env var,
    # which has no native bool type) - handle both.
    return v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes")


class InfluxConnector(Connector):
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
        """Real, live measurement/field names via InfluxQL's own SHOW
        MEASUREMENTS + SHOW FIELD KEYS - neither starts with SELECT, so
        DataFrameClient.query() hands back a raw ResultSet instead of a
        DataFrame (see query()'s own module docstring for that branch) -
        .get_points() is the real influxdb-python idiom for reading one
        of those. Not the query() path, so this never touches actual
        row data, only schema."""
        measurements = [p["name"] for p in self.client.query("SHOW MEASUREMENTS").get_points()]
        tags = []
        for measurement in measurements:
            # InfluxQL identifier quoting is double quotes, not a Python
            # string literal - measurement names can contain spaces/
            # special characters.
            fields = [p["fieldKey"] for p in self.client.query(f'SHOW FIELD KEYS FROM "{measurement}"').get_points()]
            tags.append({"table": measurement, "columns": fields})
        return tags
