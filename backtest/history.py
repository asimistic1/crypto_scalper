"""Load and slice historical Parquet candles (no look-ahead)."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd

from backtest.paths import history_parquet
from core.config import (
    ANALYSIS_CANDLES,
    HIGHER_TIMEFRAMES,
    HTF_CANDLES,
)
from core.indicators import add_all_indicators
from core.trend import slice_closed_at


def load_history(symbol: str, interval: str) -> pd.DataFrame:
    path = history_parquet(symbol, interval)
    if not path.exists():
        raise FileNotFoundError(path)
    df = pd.read_parquet(path)
    if "time" in df.columns and not pd.api.types.is_datetime64_any_dtype(df["time"]):
        df["time"] = pd.to_datetime(df["time"], utc=True)
    return df.sort_values("time").reset_index(drop=True)


def ensure_indicators(df: pd.DataFrame) -> pd.DataFrame:
    return add_all_indicators(df)


def as_of_from_close_ms(close_ms: int) -> datetime:
    return datetime.fromtimestamp(close_ms / 1000.0, tz=UTC)


def slice_ltf_window(df: pd.DataFrame, as_of: datetime, max_bars: int = ANALYSIS_CANDLES) -> pd.DataFrame:
    closed = slice_closed_at(df, as_of)
    if len(closed) > max_bars:
        closed = closed.iloc[-max_bars:].copy()
    return closed


def slice_htf_frames(
    symbol: str,
    ltf_tf: str,
    as_of: datetime,
    cache: dict[str, pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for tf in HIGHER_TIMEFRAMES.get(ltf_tf, ()):
        if tf not in cache:
            cache[tf] = load_history(symbol, tf)
        closed = slice_closed_at(cache[tf], as_of)
        if len(closed) > HTF_CANDLES:
            closed = closed.iloc[-HTF_CANDLES:].copy()
        out[tf] = closed
    return out


def quote_volume_24h_at(df: pd.DataFrame, as_of: datetime) -> float:
    """True rolling 24h quote volume at as_of (no liquidity floor)."""
    from backtest.windows import precompute_quote_volume_24h

    if df.empty or "quote_volume" not in df.columns:
        return 0.0
    as_ms = int(as_of.timestamp() * 1000)
    full_ct = df["close_time"].to_numpy(dtype=np.int64)
    end = int(np.searchsorted(full_ct, as_ms, side="right")) - 1
    if end < 0:
        return 0.0
    series = precompute_quote_volume_24h(
        full_ct,
        df["quote_volume"].to_numpy(dtype=np.float64),
    )
    return float(series[end])

