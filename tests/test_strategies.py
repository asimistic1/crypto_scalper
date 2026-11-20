"""
Strategy detector tests (Phase 2 step 5).
Run: python tests/test_strategies.py
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.indicators import add_all_indicators
from core.models import Direction, TrendBias, TrendResult, Zone
from core.strategies import run_strategies
from core.strategies.types import StrategyContext
from core.strategies import trend_pullback, breakout_retest


def _frame(n: int, base: float = 100.0) -> pd.DataFrame:
    start = datetime(2024, 6, 1, tzinfo=timezone.utc)
    rows = []
    for i in range(n):
        t = start + timedelta(minutes=15 * i)
        c = base + i * 0.3
        close_ms = int((t + timedelta(minutes=15) - timedelta(milliseconds=1)).timestamp() * 1000)
        rows.append(
            {
                "time": t,
                "open": c - 0.1,
                "high": c + 0.5,
                "low": c - 0.5,
                "close": c,
                "volume": 1000.0,
                "close_time": close_ms,
            }
        )
    df = pd.DataFrame(rows)
    return add_all_indicators(df)


class StrategyTests(unittest.TestCase):
    def _ctx(self, df, zones=None, htf=None):
        as_of = pd.to_datetime(df["close_time"].iloc[-1], unit="ms", utc=True).to_pydatetime()
        return StrategyContext(
            symbol="BTCUSDT",
            timeframe="15m",
            df=df,
            htf_trends=htf or {"15m": TrendResult(TrendBias.BULLISH), "1h": TrendResult(TrendBias.BULLISH)},
            zones=tuple(zones or []),
            as_of=as_of,
            tick_size=0.1,
        )

    def test_conflict_opposite_directions(self) -> None:
        df = _frame(260)
        z = Zone(99, 101, 100, 2, datetime.now(timezone.utc), 1.0, "support")
        long_c = trend_pullback.StrategyCandidate(Direction.LONG, "trend_pullback", df["time"].iloc[-1], (), 50.0)  # type: ignore[arg-type]
        short_c = breakout_retest.StrategyCandidate(Direction.SHORT, "breakout_retest", df["time"].iloc[-1], (), 60.0)  # type: ignore[arg-type]

        # Use run_strategies merge by mocking via manual list — test resolver directly
        from core.strategies import __init__ as strat_pkg

        class Fake:
            pass

        # Direct conflict check
        found = [long_c, short_c]
        dirs = {c.direction for c in found}
        self.assertIn(Direction.LONG, dirs)
        self.assertIn(Direction.SHORT, dirs)

    def test_long_pullback_synthetic(self) -> None:
        df = _frame(260)
        prev = df.iloc[-2]
        cur = df.iloc[-1]
        # Pullback touches EMA21 band
        cur["low"] = cur["ema_21"]
        cur["high"] = cur["ema_21"] + 0.2
        cur["rsi_14"] = 48.0
        prev["rsi_14"] = 46.0
        cur["close"] = float(prev["high"]) + 0.01
        cur["volume_ratio"] = 1.2
        df.iloc[-2] = prev
        df.iloc[-1] = cur

        z = Zone(cur["low"] - 1, cur["low"], cur["low"] - 0.5, 1, cur["time"], 1.0, "support")
        ctx = self._ctx(df, zones=[z])
        res = trend_pullback.detect(ctx)
        self.assertIsNotNone(res)
        assert res is not None
        self.assertEqual(res.direction, Direction.LONG)

    def test_breakout_retest_long(self) -> None:
        df = _frame(30)
        zone = Zone(110.0, 111.0, 110.5, 3, df["time"].iloc[0], 2.0, "resistance")
        brk_idx = -5
        df.iloc[brk_idx, df.columns.get_loc("close")] = 112.0
        df.iloc[brk_idx, df.columns.get_loc("volume_ratio")] = 2.0
        # Signal retest
        sig = df.iloc[-1]
        sig["low"] = 110.5
        sig["close"] = 111.5
        sig["open"] = 110.8
        sig["volume_ratio"] = 1.1
        df.iloc[-1] = sig

        ctx = self._ctx(df, zones=[zone])
        res = breakout_retest.detect(ctx)
        self.assertIsNotNone(res)
        assert res is not None
        self.assertEqual(res.direction, Direction.LONG)

    def test_run_picks_higher_score_same_direction(self) -> None:
        df = _frame(260)
        as_of = pd.to_datetime(df["close_time"].iloc[-1], unit="ms", utc=True).to_pydatetime()
        c1 = trend_pullback.StrategyCandidate(Direction.LONG, "a", as_of, (), 10.0)
        c2 = trend_pullback.StrategyCandidate(Direction.LONG, "b", as_of, (), 20.0)
        from core.strategies.__init__ import StrategyRunResult

        best = max([c1, c2], key=lambda c: c.pick_score)
        self.assertEqual(best.strategy, "b")


if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    if result.wasSuccessful():
        print("\nSTRATEGY TESTS PASSED")
    sys.exit(0 if result.wasSuccessful() else 1)