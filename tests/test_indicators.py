"""
Indicator accuracy tests vs slow reference and optional TradingView fixture.
Run: python tests/test_indicators.py
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.indicators import (  # noqa: E402
    _atr_wilder,
    _ema_tradingview,
    _rsi_wilder,
    add_all_indicators,
    add_emas,
    add_basic_indicators,
)

FIXTURE = ROOT / "tests" / "fixtures" / "tradingview_reference.json"


def _slow_ema(close: list[float], period: int) -> list[float]:
    return _ema_tradingview(np.asarray(close, dtype=float), period).tolist()


def _slow_rsi(close: list[float], period: int) -> list[float]:
    return _rsi_wilder(np.asarray(close, dtype=float), period).tolist()


def _make_ohlcv(n: int = 300, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 0.5, n))
    high = close + rng.uniform(0.1, 1.0, n)
    low = close - rng.uniform(0.1, 1.0, n)
    open_ = close + rng.normal(0, 0.2, n)
    vol = rng.uniform(100, 5000, n)
    t0 = pd.Timestamp("2024-01-01", tz="UTC")
    times = pd.date_range(t0, periods=n, freq="15min", tz="UTC")
    return pd.DataFrame(
        {"time": times, "open": open_, "high": high, "low": low, "close": close, "volume": vol}
    )


class IndicatorFastVsSlowTests(unittest.TestCase):
    def test_ema_matches_slow_impl(self) -> None:
        df = _make_ohlcv(250)
        close = df["close"].tolist()
        fast = add_emas(df)
        for col, p in (("ema_9", 9), ("ema_21", 21), ("ema_50", 50), ("ema_200", 200)):
            slow = _slow_ema(close, p)
            a = fast[col].to_numpy(dtype=float)
            b = np.asarray(slow, dtype=float)
            mask = ~(np.isnan(a) | np.isnan(b))
            self.assertTrue(mask.any())
            rel = np.abs(a[mask] - b[mask]) / np.maximum(np.abs(b[mask]), 1e-9)
            self.assertLessEqual(rel.max(), 1e-9)

    def test_rsi_atr_match_slow(self) -> None:
        df = _make_ohlcv(200)
        fast = add_basic_indicators(df)
        c = df["close"].to_numpy(dtype=float)
        rsi_slow = _slow_rsi(df["close"].tolist(), 14)
        atr_slow = _atr_wilder(
            df["high"].to_numpy(), df["low"].to_numpy(), c, 14
        )
        for col, slow_arr in (("rsi_14", rsi_slow), ("atr_14", atr_slow)):
            a = fast[col].to_numpy(dtype=float)
            b = np.asarray(slow_arr, dtype=float)
            mask = ~(np.isnan(a) | np.isnan(b))
            rel = np.abs(a[mask] - b[mask]) / np.maximum(np.abs(b[mask]), 1e-9)
            self.assertLessEqual(rel.max(), 1e-9)

    def test_add_all_indicators_columns(self) -> None:
        df = _make_ohlcv(400)
        out = add_all_indicators(df)
        for col in (
            "ema_200",
            "macd_hist",
            "stochrsi_k",
            "bb_width",
            "vwap_daily",
            "obv_ema_slope_5",
            "volume_ratio",
        ):
            self.assertIn(col, out.columns)
        self.assertFalse(out["close"].isna().any())


@unittest.skipUnless(FIXTURE.exists(), "fixture missing")
class TradingViewFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.bars = raw.get("bars") or []

    def test_tradingview_reference_when_filled(self) -> None:
        if not self.bars:
            self.skipTest("tradingview_reference.json bars[] is empty — fill per file instructions")

        # Build minimal history ending at fixture closes (uses live API elsewhere for full test).
        # Here we only validate the last bar values when user provides a pre-built CSV-style series.
        last = self.bars[-1]
        n = max(250, len(self.bars) + 200)
        df = _make_ohlcv(n)
        # Overwrite tail with synthetic closes leading into reference close
        for i, bar in enumerate(self.bars):
            idx = len(df) - len(self.bars) + i
            df.loc[idx, "close"] = float(bar["close"])
            df.loc[idx, "time"] = pd.Timestamp(bar["time_utc"])

        out = add_all_indicators(df)
        idx = len(df) - 1
        tol = 0.0001  # 0.01% relative
        for key in ("ema_9", "ema_21", "ema_50", "ema_200", "rsi_14", "atr_14"):
            if key not in last:
                continue
            expected = float(last[key])
            got = float(out[key].iloc[idx])
            if expected == 0:
                self.assertAlmostEqual(got, expected, places=2)
            else:
                rel = abs(got - expected) / abs(expected)
                self.assertLessEqual(rel, tol, msg=f"{key} got={got} expected={expected}")


def main() -> int:
    suite = unittest.TestSuite()
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(IndicatorFastVsSlowTests))
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(TradingViewFixtureTests))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print("\nINDICATOR TESTS PASSED")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())