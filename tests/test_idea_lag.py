"""Zone distance uses only bars through index i (lag-safe step)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from core.idea_features import _zone_distances_at


def test_zone_distances_use_prefix_only():
    n = 120
    rng = np.random.default_rng(0)
    close = 100 + np.cumsum(rng.normal(0, 0.5, n))
    t0 = pd.Timestamp("2024-01-01", tz="UTC")
    times = [t0 + pd.Timedelta(hours=i) for i in range(n)]
    df = pd.DataFrame(
        {
            "time": times,
            "close_time": np.arange(n) * 3_600_000,
            "open": close,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 1000.0,
            "atr_14": 1.0,
        }
    )
    a1, _ = _zone_distances_at(df, 80, 1.0)
    df2 = df.copy()
    df2.loc[81:, "close"] = 1e6
    a2, _ = _zone_distances_at(df2, 80, 1.0)
    assert a1 == a2