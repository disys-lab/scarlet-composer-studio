"""Generate deterministic test data for f_test."""
import numpy as np, pandas as pd


def make(path_a, path_b, rows_a=50, rows_b=60, seed=0):
    """
    Generate two datasets with different variances.
    
    Both datasets have the same mean but different variances to make
    the F-test meaningful. Group A has variance 4.0, Group B has variance 1.0.
    
    Parameters
    ----------
    path_a : str or Path
        Path to write group A data.
    path_b : str or Path
        Path to write group B data.
    rows_a : int, default 50
        Number of rows in group A.
    rows_b : int, default 60
        Number of rows in group B.
    seed : int, default 0
        Random seed for reproducibility.
    
    Returns
    -------
    tuple of DataFrames
        (group_a_df, group_b_df)
    """
    rng = np.random.default_rng(seed)
    
    mean = 100.0
    sd_a = 2.0  # variance = 4.0
    sd_b = 1.0  # variance = 1.0
    
    df_a = pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=rows_a, freq="min"),
        "value": rng.normal(mean, sd_a, rows_a),
    })
    df_a.to_csv(path_a, index=False)
    
    df_b = pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=rows_b, freq="min"),
        "value": rng.normal(mean, sd_b, rows_b),
    })
    df_b.to_csv(path_b, index=False)
    
    return df_a, df_b
