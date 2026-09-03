"""
PostgresConnector — a new connector (no existing reference code to adapt,
unlike MssqlConnector/PiConnector/InfluxConnector), built to the same
shape: raw SQL passthrough via psycopg2, same open-ended trust boundary
as MssqlConnector's raw SQL (composer-api's authorize check bounds who
can reach this broker at all, not a query-type restriction).

Plain username/password auth over TLS (Postgres's own standard
`sslmode`), not Kerberos/AD - unlike MS SQL, there's no Windows-specific
integrated-auth convention to mirror here, so this is the simpler,
standard case: PGPASSWORD-equivalent held entirely in this broker's own
env vars, never passed in from a caller, never returned to one (same
"credential lives entirely in this broker's own deployment" property as
every other connector here).

query() returns {"columns": [...], "rows": [[...], ...]}, same shape as
MssqlConnector - built from cursor.description/fetchall(), with the same
non-native-JSON coercion (Decimal, datetime, UUID, etc. -> str).

psycopg2-binary bundles its own libpq, so no system-level Postgres client
library is needed in the broker image (see requirements.txt).
"""
import psycopg2

from data_connectors.base import Connector, config_value


class PostgresConnector(Connector):
    def __init__(self, config: dict | None = None):
        self.conn_kwargs = {
            "host": config_value(config, "host", "POSTGRES_HOST", required=True),
            "port": int(config_value(config, "port", "POSTGRES_PORT", default="5432")),
            "dbname": config_value(config, "database", "POSTGRES_DATABASE", required=True),
            "user": config_value(config, "user", "POSTGRES_USER", required=True),
            "password": config_value(config, "password", "POSTGRES_PASSWORD", required=True),
            "sslmode": config_value(config, "sslmode", "POSTGRES_SSLMODE", default="prefer"),
        }

    def query(self, payload: dict) -> dict:
        sql = payload.get("query")
        if not sql:
            raise ValueError("payload must include a 'query' string")

        conn = psycopg2.connect(**self.conn_kwargs)
        try:
            cursor = conn.cursor()
            cursor.execute(sql)

            if cursor.description is None:
                # A statement with no result set (rare for a read-only
                # query, but handled cleanly rather than raising).
                conn.commit()
                return {"columns": [], "rows": []}

            columns = [desc[0] for desc in cursor.description]
            rows = [
                [None if v is None else (v if isinstance(v, (str, int, float, bool)) else str(v)) for v in row]
                for row in cursor.fetchall()
            ]
            conn.commit()
            return {"columns": columns, "rows": rows}
        finally:
            conn.close()

    def list_tags(self) -> list:
        """Real, live table/column names via information_schema - not the
        query() path, so this never touches actual row data, only schema.
        Excludes Postgres's own system schemas (pg_catalog,
        information_schema) - only user tables are "tags" worth
        surfacing."""
        conn = psycopg2.connect(**self.conn_kwargs)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT table_schema, table_name, column_name FROM information_schema.columns "
                "WHERE table_schema NOT IN ('pg_catalog', 'information_schema') "
                "ORDER BY table_schema, table_name, ordinal_position"
            )
            tables: dict[str, list[str]] = {}
            for schema, table, column in cursor.fetchall():
                key = f"{schema}.{table}"
                tables.setdefault(key, []).append(column)
            return [{"table": table, "columns": columns} for table, columns in tables.items()]
        finally:
            conn.close()
