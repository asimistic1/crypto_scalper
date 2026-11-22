"""Lag-safety: future auxiliary data must not change past feature values."""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.config import BacktestConfig
from research.features import _zscore


def test_zscore_unchanged_before_future_shift():
    s = pd.Series(np.arange(100, dtype=float))
    z = _zscore(s, 24)
    z_future = _zscore(pd.concat([s, pd.Series([10_000.0])], ignore_index=True), 24)
    pd.testing.assert_series_equal(z, z_future.iloc[: len(z)], check_names=False)


def test_merge_asof_backward_no_lookahead():
    left = pd.DataFrame({"close_time": [1000, 2000, 3000], "close": [1.0, 2.0, 3.0]})
    right = pd.DataFrame({"close_time": [1500, 2500], "aux": [10.0, 20.0]})
    m = pd.merge_asof(left.sort_values("close_time"), right.sort_values("close_time"), on="close_time", direction="backward")
    assert np.isnan(m.loc[0, "aux"])
    assert m.loc[1, "aux"] == 10.0
    poison = pd.concat([right, pd.DataFrame({"close_time": [9000], "aux": [1e6]})], ignore_index=True)
    m2 = pd.merge_asof(left.sort_values("close_time"), poison.sort_values("close_time"), on="close_time", direction="backward")
    pd.testing.assert_series_equal(m["aux"], m2["aux"], check_names=False)