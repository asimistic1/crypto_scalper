"""Load auxiliary research series with normalized UTC-ms timestamps."""

from __future__ import annotations

import pandas as pd

from backtest.paths import funding_parquet, symbol_aux_parquet

METRICS_TOLERANCE_MS = 15 * 60 * 1000


def _event_close_ms(ts: pd.Series) -> pd.Series:
    """UTC datetime → Binance-style close_time in milliseconds."""
    return pd.to_datetime(ts, utc=True).map(lambda t: int(t.timestamp() * 1000))


def load_metrics_5m(symbol: str) -> pd.DataFrame:
    path = symbol_aux_parquet(symbol.upper(), "metrics_5m")
    if not path.exists():
        return pd.DataFrame()
    met = pd.read_parquet(path).sort_values("close_time")
    met = met.copy()
    src = met["time"] if "time" in met.columns else met.get("create_time")
    if src is not None:
        met["close_time"] = _event_close_ms(src) + 300_000 - 1
    elif met["close_time"].max() < 10**12:
        met["close_time"] = met["close_time"].astype("int64") * 1000 + 299_999
    return met.drop_duplicates(subset=["close_time"], keep="last").sort_values("close_time")


def load_funding(symbol: str) -> pd.DataFrame:
    sym = symbol.upper()
    path = symbol_aux_parquet(sym, "funding")
    if not path.exists():
        path = funding_parquet(sym)
    if not path.exists():
        return pd.DataFrame()
    fund = pd.read_parquet(path).sort_values("calc_time")
    fund = fund.copy()
    fund["close_time"] = _event_close_ms(fund["calc_time"])
    rate = pd.to_numeric(fund["last_funding_rate"], errors="coerce")
    if rate.abs().max() > 0.05:
        rate = rate / 100.0
    fund["funding_rate"] = rate
    return fund[["close_time", "funding_rate"]].dropna(subset=["funding_rate"])


def merge_asof_features(
    left: pd.DataFrame,
    right: pd.DataFrame,
    value_cols: list[str],
    *,
    tolerance_ms: int = METRICS_TOLERANCE_MS,
) -> pd.DataFrame:
    if right.empty:
        for c in value_cols:
            left[c] = float("nan")
        return left
    r = right[["close_time", *value_cols]].sort_values("close_time")
    out = pd.merge_asof(
        left.sort_values("close_time"),
        r,
        on="close_time",
        direction="backward",
        tolerance=tolerance_ms,
    )
    return out.sort_index()