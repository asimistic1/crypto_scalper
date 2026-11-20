"""Load and slice historical Parquet candles (no look-ahead)."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from backtest.paths import history_parquet
from core.config import (
    ANALYSIS_CANDLES,
    HTF_CANDLES,
    HIGHER_TIMEFRAMES,
    MIN_24H_QUOTE_VOLUME_USDT,
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
    work = df.copy()
    add_all_indicators(work)
    return work


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
    closed = slice_closed_at(df, as_of)
    if closed.empty or "quote_volume" not in closed.columns:
        return float(MIN_24H_QUOTE_VOLUME_USDT)
    tail = closed[closed["close_time"] > int(as_of.timestamp() * 1000) - 86_400_000]
    qv = float(tail["quote_volume"].sum())
    return max(qv, float(MIN_24H_QUOTE_VOLUME_USDT))

