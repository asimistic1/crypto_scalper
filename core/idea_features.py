"""Lag-safe feature columns for Test-my-idea (per bar, no future data in zone dist)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.history import ensure_indicators, load_history
from core.levels import nearest_zones, structure_for_symbol

IDEA_FEATURE_NAMES = (
    "rsi_14",
    "close",
    "ema_50",
    "ema_200",
    "atr_14",
    "atr_pct",
    "volume_ratio",
    "dist_support_atr",
    "dist_resistance_atr",
    "taker_buy_ratio_z24",
    "taker_delta_12h",
    "funding_z_30d",
    "oi_chg_4h",
    "basis_z72",
    "hour",
    "weekday",
)

# Rolling swing-zone approximation (lag-safe): zones from bars [: i+1] only.
_ZONE_STEP = 48


def _zone_distances_at(df: pd.DataFrame, i: int, atr: float) -> tuple[float, float]:
    if atr <= 0 or i < 50:
        return float("nan"), float("nan")
    sub = df.iloc[: i + 1]
    as_of = pd.to_datetime(int(sub["close_time"].iloc[-1]), unit="ms", utc=True)
    _, zones = structure_for_symbol(sub, as_of.to_pydatetime(), atr, None)
    price = float(sub["close"].iloc[-1])
    below, above = nearest_zones(zones, price, 1)
    ds = abs(price - below[0].price_high) / atr if below else float("nan")
    dr = abs(price - above[0].price_low) / atr if above else float("nan")
    return ds, dr


def enrich_idea_features(df: pd.DataFrame, symbol: str, timeframe: str) -> pd.DataFrame:
    """Add idea-tester columns; merges research features on 1h when data exists."""
    out = ensure_indicators(df.copy())
    close = out["close"].astype(float)
    out["atr_pct"] = 100.0 * out["atr_14"] / close.replace(0, np.nan)
    out["volume_ratio"] = out["volume"] / out["volume"].rolling(24, min_periods=5).mean()
    ct = pd.to_datetime(out["close_time"], unit="ms", utc=True)
    out["hour"] = ct.dt.hour
    out["weekday"] = ct.dt.weekday
    ds = np.full(len(out), np.nan)
    dr = np.full(len(out), np.nan)
    for i in range(50, len(out), _ZONE_STEP):
        atr = float(out["atr_14"].iloc[i])
        if not np.isfinite(atr) or atr <= 0:
            continue
        a, b = _zone_distances_at(out, i, atr)
        end = min(i + _ZONE_STEP, len(out))
        ds[i:end] = a
        dr[i:end] = b
    out["dist_support_atr"] = ds
    out["dist_resistance_atr"] = dr
    if timeframe == "1h":
        try:
            from research.features import build_feature_table

            aux = build_feature_table(symbol, cfg=None)
            cols = [c for c in IDEA_FEATURE_NAMES if c in aux.columns and c not in out.columns]
            if cols:
                merged = out.merge(aux[["close_time", *cols]], on="close_time", how="left", suffixes=("", "_aux"))
                for c in cols:
                    out[c] = merged[c]
        except Exception:
            pass
    return out


def load_idea_feature_frame(symbol: str, timeframe: str) -> pd.DataFrame:
    return enrich_idea_features(load_history(symbol.upper(), timeframe), symbol, timeframe)