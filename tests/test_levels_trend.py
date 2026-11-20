"""
Structure and trend tests (Phase 2 step 4).
Run: python tests/test_levels_trend.py
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.config import SWING_LEFT, SWING_RIGHT
from core.indicators import add_all_indicators
from core.levels import build_zones, find_swings, nearest_zones, swings_confirmed_as_of
from core.trend import get_trend, slice_closed_at


def _synthetic_df(closes: list[float], period_minutes: int = 15) -> pd.DataFrame:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    rows = []
    for i, c in enumerate(closes):
        t = start + timedelta(minutes=period_minutes * i)
        close_ms = int((t + timedelta(minutes=period_minutes) - timedelta(milliseconds=1)).timestamp() * 1000)
        rows.append(
            {
                "time": t,
                "open": c,
                "high": c + 0.5,
                "low": c - 0.5,
                "close": c,
                "volume": 1000.0,
                "close_time": close_ms,
            }
        )
    return pd.DataFrame(rows)


class SwingConfirmationTests(unittest.TestCase):
    def test_swing_not_visible_before_confirmation(self) -> None:
        # Clear pivot high in the middle of an uptrend segment
        n = 40
        closes = [100.0 + i * 0.1 for i in range(n)]
        pivot = SWING_LEFT + SWING_RIGHT + 5
        highs_boost = closes.copy()
        lows = [c - 0.5 for c in closes]
        highs = [c + 0.5 for c in closes]
        highs[pivot] = closes[pivot] + 5.0

        df = _synthetic_df(closes)
        df["high"] = highs
        df["low"] = lows

        swings = find_swings(df, SWING_LEFT, SWING_RIGHT)
        pivot_swings = [s for s in swings if s.kind == "high" and abs(s.price - highs[pivot]) < 1e-6]
        self.assertTrue(pivot_swings, "expected a swing high at boosted bar")

        s = pivot_swings[0]
        conf_idx = pivot + SWING_RIGHT
        conf_time = pd.to_datetime(df["close_time"].iloc[conf_idx], unit="ms", utc=True).to_pydatetime()
        early = conf_time - timedelta(seconds=1)
        self.assertEqual(swings_confirmed_as_of([s], early), [])
        self.assertEqual(len(swings_confirmed_as_of([s], conf_time)), 1)

    def test_zones_deterministic(self) -> None:
        closes = [10.0 + 0.05 * i for i in range(60)]
        df = _synthetic_df(closes)
        df.loc[20, "low"] = 8.0
        df.loc[35, "low"] = 8.1
        swings = find_swings(df)
        atr = 1.0
        ref = float(df.iloc[-1]["close"])
        z1 = build_zones(swings, atr, reference_price=ref, df=df, as_of=df["time"].iloc[-1].to_pydatetime())
        z2 = build_zones(swings, atr, reference_price=ref, df=df, as_of=df["time"].iloc[-1].to_pydatetime())
        self.assertEqual(len(z1), len(z2))
        for a, b in zip(z1, z2, strict=True):
            self.assertEqual(a.mid, b.mid)
            self.assertEqual(a.touches, b.touches)


class TrendSyntheticTests(unittest.TestCase):
    def _trend_df(self, closes: list[float]) -> pd.DataFrame:
        df = _synthetic_df(closes)
        return add_all_indicators(df)

    def test_uptrend_bullish_or_neutral(self) -> None:
        closes = [100 + i * 2.0 for i in range(250)]
        df = self._trend_df(closes)
        as_of = pd.to_datetime(df["close_time"].iloc[-1], unit="ms", utc=True).to_pydatetime()
        res = get_trend(df, as_of)
        self.assertIn(res.bias, {"bullish", "neutral"})

    def test_downtrend_bearish_or_neutral(self) -> None:
        closes = [500 - i * 2.0 for i in range(250)]
        df = self._trend_df(closes)
        as_of = pd.to_datetime(df["close_time"].iloc[-1], unit="ms", utc=True).to_pydatetime()
        res = get_trend(df, as_of)
        self.assertIn(res.bias, {"bearish", "neutral"})

    def test_sideways_neutral(self) -> None:
        closes = [100.0] * 250
        df = self._trend_df(closes)
        as_of = pd.to_datetime(df["close_time"].iloc[-1], unit="ms", utc=True).to_pydatetime()
        res = get_trend(df, as_of)
        self.assertEqual(res.bias.value, "neutral")

    def test_htf_slice_drops_partial_candle(self) -> None:
        df = _synthetic_df([1.0, 2.0, 3.0])
        mid = pd.to_datetime(df["close_time"].iloc[1], unit="ms", utc=True).to_pydatetime()
        sliced = slice_closed_at(df, mid)
        self.assertEqual(len(sliced), 2)

    def test_nearest_zones(self) -> None:
        from core.models import Zone

        zones = [
            Zone(9, 11, 10, 1, datetime.now(timezone.utc), 1.0, "support"),
            Zone(19, 21, 20, 1, datetime.now(timezone.utc), 1.0, "resistance"),
        ]
        below, above = nearest_zones(zones, 15.0, 2)
        self.assertEqual(len(below), 1)
        self.assertEqual(len(above), 1)
        self.assertLess(below[0].mid, 15.0)
        self.assertGreater(above[0].mid, 15.0)


if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    if result.wasSuccessful():
        print("\nLEVELS/TREND TESTS PASSED")
    sys.exit(0 if result.wasSuccessful() else 1)