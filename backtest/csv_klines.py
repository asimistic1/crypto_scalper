"""Parse Binance Vision kline CSV (with or without header); normalize timestamps to ms."""

from __future__ import annotations

import io

import numpy as np
import pandas as pd

CANDLE_COLUMNS = (
    "time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "taker_buy_quote_volume",
)

_HEADER_MARKERS = ("open_time", "Open time", "open time")


def _maybe_header(first_cell: str) -> bool:
    return any(m in first_cell for m in _HEADER_MARKERS) or not first_cell.strip().isdigit()


def _normalize_ts(series: pd.Series) -> pd.Series:
    """Detect ms vs µs (and rare seconds) and return int64 ms."""
    arr = pd.to_numeric(series, errors="coerce").astype("float64")
    med = float(np.nanmedian(arr.to_numpy()))
    if med > 1e16:
        return (arr / 1000.0).astype(np.int64)
    if med > 1e14:
        return (arr / 1000.0).astype(np.int64)
    if med > 1e11:
        return arr.astype(np.int64)
    if med > 1e9:
        return (arr * 1000.0).astype(np.int64)
    raise ValueError(f"cannot infer timestamp unit (median={med})")


def parse_kline_csv(raw: bytes | str) -> pd.DataFrame:
    text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    first_line = text.splitlines()[0] if text else ""
    has_header = _maybe_header(first_line.split(",")[0])
    df = pd.read_csv(io.StringIO(text), header=0 if has_header else None)
    if not has_header:
        if df.shape[1] < 11:
            raise ValueError(f"expected >=11 columns, got {df.shape[1]}")
        df.columns = [
            "open_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "close_time",
            "quote_volume",
            "count",
            "taker_buy_volume",
            "taker_buy_quote_volume",
            "ignore",
        ][: df.shape[1]]
    else:
        df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
        if "open_time" not in df.columns and "open time" in df.columns:
            df = df.rename(columns={"open time": "open_time"})
    open_ms = _normalize_ts(df["open_time"])
    close_ms = _normalize_ts(df["close_time"])
    out = pd.DataFrame(
        {
            "time": pd.to_datetime(open_ms, unit="ms", utc=True),
            "open": pd.to_numeric(df["open"], errors="coerce"),
            "high": pd.to_numeric(df["high"], errors="coerce"),
            "low": pd.to_numeric(df["low"], errors="coerce"),
            "close": pd.to_numeric(df["close"], errors="coerce"),
            "volume": pd.to_numeric(df["volume"], errors="coerce"),
            "close_time": close_ms.astype(np.int64),
            "quote_volume": pd.to_numeric(df["quote_volume"], errors="coerce"),
            "taker_buy_quote_volume": pd.to_numeric(df["taker_buy_quote_volume"], errors="coerce"),
        }
    )
    return out.dropna(subset=["open", "high", "low", "close"])