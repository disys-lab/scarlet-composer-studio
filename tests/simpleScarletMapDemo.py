"""
Minimal end-to-end demo: Map local data to a Mapper scarlet and AllGather it back.

Requirements:
  REDIS_HOST, REDIS_PORT, REDIS_AUTH_TOKEN must be set.

Run:
  python tests/simpleScarletMapDemo.py
"""
import os
import numpy as np
from scarlets.core.Mapper import Mapper

os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("REDIS_PORT", "6379")
os.environ.setdefault("REDIS_AUTH_TOKEN", "")
os.environ.setdefault("APP_ID", "demo_worker")

local_data = {
    "feature1": np.ones(10, dtype=np.float64),
    "feature2": 2 * np.ones(10, dtype=np.float64),
    "feature3": 3 * np.ones(10, dtype=np.float64),
}

mpr = Mapper("Regressor")

chunks, ok, exc = mpr.Map(local_data, mpr.super.address)
print(f"Map ok={ok}  chunks={chunks}  exc={exc}")

result, ok, exc = mpr.AllGather()
print(f"AllGather ok={ok}  keys={list(result.keys())}")
