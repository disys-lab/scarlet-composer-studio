"""
MssqlConnector — adapts the real, already-existing QueryExecutionEngine
(assurant_decentralized_analytics/claim_analytics/app/QueryExecutionEngine.py),
not a reimplementation: same pyodbc + `ODBC Driver 18 for SQL Server` +
`Authentication=ActiveDirectoryIntegrated` connection string shape.

Windows/AD Integrated auth, not a stored username/password: this
connector assumes a valid Kerberos ticket already exists in the container's
environment when query() is called (a keytab + krb5.conf mounted in, and
`kinit` run at container startup - an entrypoint/ops concern, not something
this class does itself). See docker/broker/Dockerfile's own comments for
the exact system-package setup this depends on (msodbcsql18, krb5-user,
unixodbc - mirrors assurant_decentralized_analytics/claim_analytics/
Dockerfile's already-proven install).

query() returns {"columns": [...], "rows": [[...], ...]} rather than
QueryExecutionEngine's own CSV-file-writing behavior, since the broker
hands this back as a JSON HTTP response, not a file on disk. Non-native-
JSON pyodbc types (datetime, Decimal, etc.) are coerced to str - same
defensive conversion QueryExecutionEngine.execute_query_to_csv already
does, just producing JSON values instead of CSV cells.
"""
import pyodbc

from data_connectors.base import Connector, config_value


class MssqlConnector(Connector):
    def __init__(self, config: dict | None = None):
        self.server = config_value(config, "server", "MSSQL_SERVER", required=True)
        self.database = config_value(config, "database", "MSSQL_DATABASE", required=True)
        self.conn_string = (
            f"DRIVER={{ODBC Driver 18 for SQL Server}};"
            f"SERVER={self.server};"
            f"DATABASE={self.database};"
            f"Encrypt=yes;"
            f"TrustServerCertificate=yes;"
            f"Authentication=ActiveDirectoryIntegrated;"
        )

    def query(self, payload: dict) -> dict:
        sql = payload.get("query")
        if not sql:
            raise ValueError("payload must include a 'query' string")

        conn = pyodbc.connect(self.conn_string)
        try:
            cursor = conn.cursor()
            cursor.execute(sql)

            if cursor.description is None:
                # A statement with no result set (rare for a read-only
                # query, but handled cleanly rather than raising).
                return {"columns": [], "rows": []}

            columns = [desc[0] for desc in cursor.description]
            rows = [
                [None if v is None else (v if isinstance(v, (str, int, float, bool)) else str(v)) for v in row]
                for row in cursor.fetchall()
            ]
            return {"columns": columns, "rows": rows}
        finally:
            conn.close()

    def list_tags(self) -> list:
        """Real, live table/column names via SQL Server's own
        INFORMATION_SCHEMA.COLUMNS (ANSI-standard, T-SQL implements it
        too) - not the query() path, so this never touches actual row
        data, only schema."""
        conn = pyodbc.connect(self.conn_string)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                "ORDER BY TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION"
            )
            tables: dict[str, list[str]] = {}
            for schema, table, column in cursor.fetchall():
                key = f"{schema}.{table}"
                tables.setdefault(key, []).append(column)
            return [{"table": table, "columns": columns} for table, columns in tables.items()]
        finally:
            conn.close()
