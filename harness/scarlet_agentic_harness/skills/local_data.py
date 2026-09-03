"""
Where a worker's local numeric data comes from - a LOCAL_NUMBERS env var
(comma-separated floats) for now. Shared by any skill that operates over
"the numbers this worker holds" (median, sum, ...). This is a deliberate
placeholder for scarlet-composer-studio's own three-tier data source system
(DESIGN_v3.md section 9), not a permanent design choice.
"""
import os


def local_numbers() -> list[float]:
    """
    Read this worker's local numeric data.

    A `LOCAL_NUMBERS` env var (comma-separated floats), for now -
    shared by any skill that operates over "the numbers this worker
    holds" (`skills.median`, `skills.sum`). A deliberate placeholder,
    not a permanent design choice.

    Returns
    -------
    list of float
        `[]` if `LOCAL_NUMBERS` is unset or empty.
    """
    raw = os.environ.get("LOCAL_NUMBERS", "")
    if not raw.strip():
        return []
    return [float(tok) for tok in raw.split(",") if tok.strip()]
