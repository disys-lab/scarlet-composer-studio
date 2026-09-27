"""
Where a worker's local numeric data comes from - either a CSV_PATH env var
(read via data_connectors.CsvConnector, one "value" column) or a
LOCAL_NUMBERS env var (comma-separated floats), CSV_PATH taking priority
if both are set. Shared by any skill that operates over "the numbers this
worker holds" (median, sum, ...). This is a deliberate placeholder for
scarlet-composer-studio's own three-tier data source system (DESIGN_v3.md
section 9), not a permanent design choice.
"""
import os


def local_numbers() -> list[float]:
    """
    Read this worker's local numeric data.

    `CSV_PATH` (a real `data_connectors.CsvConnector`, one "value" column)
    if set, otherwise `LOCAL_NUMBERS` (comma-separated floats) - shared by
    any skill that operates over "the numbers this worker holds"
    (`skills.median`, `skills.sum`). A deliberate placeholder, not a
    permanent design choice.

    `data_connectors` is only imported when `CSV_PATH` is actually set -
    a deployment that only ever uses `LOCAL_NUMBERS` shouldn't need that
    package (or its own dependencies, e.g. `duckdb`) importable at all.

    Returns
    -------
    list of float
        `[]` if neither `CSV_PATH` nor `LOCAL_NUMBERS` is set.
    """
    csv_path = os.environ.get("CSV_PATH", "")
    if csv_path.strip():
        from data_connectors.csv_connector import CsvConnector

        connector = CsvConnector({"path": csv_path})
        result = connector.query({"query": "SELECT value FROM data"})
        return [float(row[0]) for row in result["rows"]]

    raw = os.environ.get("LOCAL_NUMBERS", "")
    if not raw.strip():
        return []
    return [float(tok) for tok in raw.split(",") if tok.strip()]
