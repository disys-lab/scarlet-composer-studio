"""
CsvConnector — a new connector (no existing reference code to adapt).
Unlike the network-service connectors here, there's no live connection to
hold - just a local file path. Re-reads the file fresh on every query()
call rather than caching it in memory across calls: simplest correct
behavior (a hand-edited/regenerated CSV is picked up on the very next
query, no stale-cache bugs to reason about), and a CSV small enough for
this pattern to matter is not the kind of file this is meant for anyway.

payload["query"] is a raw SQL string, same open-ended trust boundary as
MssqlConnector/PostgresConnector's raw SQL - composer-api's authorize
check bounds who reaches this broker at all, not a query-type
restriction. It must reference the loaded file as `data` (e.g. "SELECT
name, value FROM data WHERE value > 100") - duckdb's Python client
resolves an unrecognized table name against a same-named local variable
in the calling frame (its "replacement scan": https://duckdb.org/docs/
guides/python/sql_on_pandas), which is exactly how query() below runs
the caller's SQL directly against the pandas DataFrame just read from
disk, without a separate load/register step or a persistent connection.

query() returns {"columns": [...], "rows": [[...], ...]}, same shape as
every other SQL-like connector here. NaN (pandas' own representation for
a missing CSV cell) is coerced to None via base.py's json_safe(), same as
every other connector's None-for-missing convention - confirmed this
session that duckdb/pandas hand back a real float('nan'), not already
JSON-safe.
"""
import duckdb
import pandas as pd

from data_connectors.base import Connector, config_value, json_safe


class CsvConnector(Connector):
    def __init__(self, config: dict | None = None):
        self.path = config_value(config, "path", "CSV_PATH", required=True)
        self.delimiter = config_value(config, "delimiter", "CSV_DELIMITER", default=",")
        self.encoding = config_value(config, "encoding", "CSV_ENCODING", default="utf-8")

    def query(self, payload: dict) -> dict:
        sql = payload.get("query")
        if not sql:
            raise ValueError(
                "payload must include a 'query' string, referencing the loaded "
                "file as 'data' (e.g. \"SELECT * FROM data WHERE value > 100\")"
            )

        data = pd.read_csv(self.path, delimiter=self.delimiter, encoding=self.encoding)
        result_df = duckdb.query(sql).to_df()  # `data` above resolved via duckdb's replacement scan

        columns = list(result_df.columns)
        rows = [[json_safe(v) for v in row] for row in result_df.values.tolist()]
        return {"columns": columns, "rows": rows}
