"""In-sample / out-of-sample split on signal time."""

from __future__ import annotations

import pandas as pd

from backtest.config import BacktestConfig


def split_times_ms(close_times: pd.Series, cfg: BacktestConfig) -> int:
    """Return cutoff close_time (ms): signals with close_time < cutoff are IS."""
    if close_times.empty:
        return 0
    t0 = int(close_times.min())
    t1 = int(close_times.max())
    return int(t0 + cfg.in_sample_fraction * (t1 - t0))


def tag_sample(df: pd.DataFrame, cfg: BacktestConfig, *, time_col: str = "close_time") -> pd.DataFrame:
    if df.empty or time_col not in df.columns:
        out = df.copy()
        out["sample"] = "ALL"
        return out
    out = df.copy()
    cutoff = split_times_ms(out[time_col], cfg)
    out["sample"] = out[time_col].apply(lambda t: "IS" if int(t) < cutoff else "OOS")
    return out


def filter_sample(df: pd.DataFrame, sample: str) -> pd.DataFrame:
    if df.empty or sample == "ALL":
        return df
    return df[df["sample"] == sample]