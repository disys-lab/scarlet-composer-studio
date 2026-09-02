"""
MysqlConnector — a new connector (no existing reference code to adapt),
built to the same shape: raw SQL passthrough via PyMySQL, same open-ended
trust boundary as MssqlConnector/PostgresConnector's raw SQL.

Plain username/password auth (PyMySQL's own standard TLS support via
ssl_verify_cert/ssl_ca, not enabled by default here) - a stored
credential held entirely in this broker's own env vars, same "never
passed in from a caller, never returned to one" property every other
connector here has.

query() returns {"columns": [...], "rows": [[...], ...]}, same shape as
the other SQL connectors - built from cursor.description/fetchall(),
with the same non-native-JSON coercion (Decimal, datetime, etc. -> str).

PyMySQL is a pure-Python MySQL client (no C extension, no libmysqlclient
system dependency) - simplest possible choice for a broker image that
otherwise has no MySQL-specific system packages to install (see
requirements.txt).
"""
import os

import pymysql

from data_connectors.base import Connector


class MysqlConnector(Connector):
    def __init__(self):
        self.conn_kwargs = {
            "host": os.environ["MYSQL_HOST"],
            "port": int(os.environ.get("MYSQL_PORT", "3306")),
            "database": os.environ["MYSQL_DATABASE"],
            "user": os.environ["MYSQL_USER"],
            "password": os.environ["MYSQL_PASSWORD"],
        }

    def query(self, payload: dict) -> dict:
        sql = payload.get("query")
        if not sql:
            raise ValueError("payload must include a 'query' string")

        conn = pymysql.connect(**self.conn_kwargs)
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
