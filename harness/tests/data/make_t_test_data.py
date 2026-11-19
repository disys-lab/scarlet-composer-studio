"""Generate deterministic test data for t_test."""
import numpy as np, pandas as pd


def make(path, rows=100, seed=0):
    """
    Generate a single dataset with known mean and variance.
    
    Parameters
    ----------
    path : str or Path
        Path to write the data.
    rows : int, default 100
        Number of rows to generate.
    seed : int, default 0
        Random seed for reproducibility.
    
    Returns
    -------
    DataFrame
        The generated dataset.
    """
    rng = np.random.default_rng(seed)
    
    df = pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=rows, freq="min"),
        "value": rng.normal(100, 15, rows),
    })
    df.to_csv(path, index=False)
    return df
