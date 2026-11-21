"""Phase 3.2 hot-path regressions: new code matches legacy on real bars."""

from __future__ import annotations

import sys
import unittest
from datetime import UTC, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backtest.history import load_history, ensure_indicators
from backtest.paths import history_parquet
from core.indicators import add_all_indicators
from core.levels import _bar_index_at_or_before, build_zones, find_swings, swings_confirmed_as_of


def _legacy_bar_index_at_or_before(df: pd.DataFrame, ts: datetime) -> int:
    times = pd.to_datetime(df["time"], utc=True)
    pt = pd.Timestamp(ts if ts.tzinfo else ts.replace(tzinfo=UTC))
    pt = pt.tz_convert("UTC")
    mask = times <= pt
    if not mask.any():
        return 0
    return int(mask.to_numpy().nonzero()[0][-1])


def _legacy_stoch_rsi(close: np.ndarray, rsi_len: int = 14, stoch_len: int = 14, k_smooth: int = 3, d_smooth: int = 3):
    from core.indicators import _rsi_wilder

    rsi = _rsi_wilder(close, rsi_len)
    n = len(close)
    stoch = np.full(n, np.nan, dtype=float)
    for i in range(rsi_len + stoch_len, n):
        window = rsi[i - stoch_len + 1 : i + 1]
        lo, hi = np.nanmin(window), np.nanmax(window)
        stoch[i] = 0.0 if hi == lo else (rsi[i] - lo) / (hi - lo) * 100.0
    k = pd.Series(stoch).rolling(k_smooth, min_periods=k_smooth).mean().to_numpy()
    return k


@unittest.skipUnless(history_parquet("BTCUSDT", "15m").exists(), "need BTC 15m history")
class HotPathRegressionTests(unittest.TestCase):
    def test_bar_index_matches_legacy(self) -> None:
        df = load_history("BTCUSDT", "15m").iloc[500:3500]
        rng = np.random.default_rng(42)
        picks = rng.choice(len(df), size=300, replace=False)
        for i in picks:
            ts = pd.Timestamp(df["time"].iloc[int(i)]).to_pydatetime()
            self.assertEqual(_bar_index_at_or_before(df, ts), _legacy_bar_index_at_or_before(df, ts))

    def test_stochrsi_matches_legacy(self) -> None:
        df = ensure_indicators(load_history("BTCUSDT", "15m").iloc[:800])
        close = df["close"].to_numpy(dtype=float)
        legacy = _legacy_stoch_rsi(close)
        new = df["stochrsi_k"].to_numpy(dtype=float)
        start = 14 + 14 + 3 - 1
        legacy = legacy[start:]
        new = new[start:]
        ok = ~(np.isnan(legacy) | np.isnan(new))
        np.testing.assert_allclose(legacy[ok], new[ok], rtol=0, atol=1e-6)

    def test_swings_zones_stable(self) -> None:
        df = ensure_indicators(load_history("BTCUSDT", "15m").iloc[1000:1400])
        swings = find_swings(df)
        as_of = pd.Timestamp(df["time"].iloc[-10]).to_pydatetime()
        swings = swings_confirmed_as_of(swings, as_of)
        atr = float(df["atr_14"].iloc[-1])
        z1 = build_zones(swings, atr, reference_price=float(df["close"].iloc[-1]), df=df, as_of=as_of)
        z2 = build_zones(swings, atr, reference_price=float(df["close"].iloc[-1]), df=df, as_of=as_of)
        self.assertEqual(len(z1), len(z2))
        for a, b in zip(z1, z2, strict=True):
            self.assertEqual(a.price_low, b.price_low)
            self.assertEqual(a.origin, b.origin)


if __name__ == "__main__":
    unittest.main()