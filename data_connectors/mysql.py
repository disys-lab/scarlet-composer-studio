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
import pymysql

from data_connectors.base import Connector, config_value


class MysqlConnector(Connector):
    """
    `Connector` for MySQL via `PyMySQL`, raw SQL passthrough.

    Plain username/password auth (`PyMySQL`'s own standard TLS support
    via ``ssl_verify_cert``/``ssl_ca`` is not enabled by default here). The
    credential lives entirely in this connector's own configuration,
    never passed in from a caller, never returned to one - same property
    as every other `Connector`.

    `PyMySQL` is a pure-Python MySQL client (no C extension, no
    `libmysqlclient` system dependency) - the simplest choice for a
    broker image with no MySQL-specific system packages installed.

    Parameters
    ----------
    config : dict or None, optional
        Per-instance config dict (`local_config.py`, `mode: local`
        entries) with keys ``host``, ``port``, ``database``, ``user``,
        ``password``. When `None` (the broker's own usage), each falls
        back to the matching ``MYSQL_*`` env var - see
        `data_connectors.base.config_value`.

    Attributes
    ----------
    conn_kwargs : dict
        Keyword arguments passed to `pymysql.connect` on every query.
    """

    def __init__(self, config: dict | None = None):
        self.conn_kwargs = {
            "host": config_value(config, "host", "MYSQL_HOST", required=True),
            "port": int(config_value(config, "port", "MYSQL_PORT", default="3306")),
            "database": config_value(config, "database", "MYSQL_DATABASE", required=True),
            "user": config_value(config, "user", "MYSQL_USER", required=True),
            "password": config_value(config, "password", "MYSQL_PASSWORD", required=True),
        }

    def query(self, payload: dict) -> dict:
        """
        Run a raw SQL statement and return its result set.

        Parameters
        ----------
        payload : dict
            Must include a ``query`` key holding the raw SQL string. No
            query-type restriction is enforced here - composer-api's
            ``/authorize`` check bounds who can reach this broker at all,
            not what they can run once authorized.

        Returns
        -------
        dict
            ``{"columns": [...], "rows": [[...], ...]}``, built from
            ``cursor.description``/``fetchall()``. Non-native-JSON types
            (`Decimal`, `datetime`, etc.) are coerced to `str`. A
            statement with no result set returns empty
            `columns`/`rows` rather than raising.

        Raises
        ------
        ValueError
            If `payload` has no ``query`` key.
        """
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

    def list_tags(self) -> list:
        """
        List tables and their columns via `information_schema`.

        Real, live schema introspection, scoped to this connection's own
        database (``DATABASE()``) - not the `query` path, so this never
        touches actual row data, only schema.

        Returns
        -------
        list of dict
            One entry per table: ``{"table": "<name>", "columns": [...]}``.
        """
        conn = pymysql.connect(**self.conn_kwargs)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = DATABASE() ORDER BY table_name, ordinal_position"
            )
            tables: dict[str, list[str]] = {}
            for table, column in cursor.fetchall():
                tables.setdefault(table, []).append(column)
            return [{"table": table, "columns": columns} for table, columns in tables.items()]
        finally:
            conn.close()
