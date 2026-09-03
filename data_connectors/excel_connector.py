"""
ExcelConnector — a new connector (no existing reference code to adapt).
Same shape as CsvConnector (see that module's own docstring for the full
rationale: re-reads the file fresh per query(), raw SQL against the
loaded data via duckdb's replacement scan against a local variable named
`data`) - the one real difference is a workbook can have multiple
sheets, so which one to read is a second, optional axis: payload["sheet"]
picks a sheet for this one query, falling back to this connector's own
configured default (sheet=0, pandas' own convention for "the first
sheet") if not given.

pandas' default Excel engine (openpyxl for .xlsx) is a separate system-
level-free Python dependency (pure Python, unlike pyodbc/psycopg2's C
extensions) - see setup_connectors.py.
"""
import duckdb
import pandas as pd

from data_connectors.base import Connector, config_value, json_safe


class ExcelConnector(Connector):
    """
    `Connector` for a local Excel workbook, queried via `duckdb` SQL over `pandas`.

    Same shape as `data_connectors.csv_connector.CsvConnector` (re-reads
    the file fresh per `query`, raw SQL against the loaded sheet via
    `duckdb`'s replacement scan against a local variable named ``data``)
    - the one real difference is a workbook can have multiple sheets, so
    which one to read is a second, optional axis.

    Parameters
    ----------
    config : dict or None, optional
        Per-instance config dict (`local_config.py`, `mode: local`
        entries) with keys ``path``, ``sheet``. When `None` (the
        broker's own usage), each falls back to the matching
        ``EXCEL_*`` env var - see `data_connectors.base.config_value`.

    Attributes
    ----------
    path : str
        Filesystem path to the workbook.
    default_sheet : int or str
        Sheet used when a query's `payload` doesn't specify one -
        pandas' own `sheet_name` convention: an int index (``0`` = first
        sheet) or a sheet name string.
    """

    def __init__(self, config: dict | None = None):
        self.path = config_value(config, "path", "EXCEL_PATH", required=True)
        # pandas' own sheet_name convention: an int index (0 = first sheet)
        # or a sheet name string. Env var fallback is always a string, so
        # coerce a purely-numeric one to int the same way pandas itself
        # would expect for an index.
        default_sheet = config_value(config, "sheet", "EXCEL_SHEET", default=0)
        self.default_sheet = int(default_sheet) if str(default_sheet).lstrip("-").isdigit() else default_sheet

    def query(self, payload: dict) -> dict:
        """
        Run a SQL query against one sheet of the workbook.

        Parameters
        ----------
        payload : dict
            Must include a ``query`` key holding a SQL string that
            references the loaded sheet as ``data`` (e.g.
            ``"SELECT * FROM data WHERE value > 100"``). Optional
            ``sheet`` key (int index or sheet name) overrides
            `default_sheet` for this one query.

        Returns
        -------
        dict
            ``{"columns": [...], "rows": [[...], ...]}``. NaN is coerced
            to `None` via `data_connectors.base.json_safe`.

        Raises
        ------
        ValueError
            If `payload` has no ``query`` key.
        """
        sql = payload.get("query")
        if not sql:
            raise ValueError(
                "payload must include a 'query' string, referencing the loaded "
                "sheet as 'data' (e.g. \"SELECT * FROM data WHERE value > 100\")"
            )
        sheet = payload.get("sheet", self.default_sheet)

        data = pd.read_excel(self.path, sheet_name=sheet)
        result_df = duckdb.query(sql).to_df()  # `data` above resolved via duckdb's replacement scan

        columns = list(result_df.columns)
        rows = [[json_safe(v) for v in row] for row in result_df.values.tolist()]
        return {"columns": columns, "rows": rows}

    def list_tags(self) -> list:
        """
        List every sheet's name and column names.

        Real, live schema introspection, across every sheet in the
        workbook (not just `default_sheet`) - a workbook commonly has
        more than one sheet worth surfacing. ``nrows=0`` per sheet reads
        just its header, not its actual data.

        Returns
        -------
        list of dict
            One entry per sheet: ``{"table": "<sheet name>", "columns": [...]}``.
        """
        workbook = pd.ExcelFile(self.path)
        tags = []
        for sheet_name in workbook.sheet_names:
            columns = pd.read_excel(workbook, sheet_name=sheet_name, nrows=0).columns.tolist()
            tags.append({"table": sheet_name, "columns": columns})
        return tags
