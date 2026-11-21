"""Breakout-retest uses zone origin, not role (Phase 3.2 fix 1)."""

from __future__ import annotations

import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.models import Direction, TrendBias, TrendResult, Zone
from core.strategies.breakout_retest import detect
from core.strategies.types import StrategyContext
def _df(rows: list[dict]) -> pd.DataFrame:
    start = datetime(2024, 6, 1, tzinfo=UTC)
    out = []
    for i, r in enumerate(rows):
        t = start + timedelta(hours=i)
        out.append(
            {
                "time": t,
                "open": r["open"],
                "high": r["high"],
                "low": r["low"],
                "close": r["close"],
                "volume": r.get("volume", 1000.0),
                "volume_ratio": r.get("volume_ratio", 1.0),
                "close_time": int((t + timedelta(minutes=59)).timestamp() * 1000),
            }
        )
    return pd.DataFrame(out)


class BreakoutOriginTests(unittest.TestCase):
    def test_long_retest_above_flipped_resistance(self) -> None:
        """After breakout, zone mid is below price → role=support but origin=high."""
        df = _df(
            [{"open": 100, "high": 101, "low": 99, "close": 100, "volume_ratio": 1.0}] * 10
            + [
                {
                    "open": 100,
                    "high": 106,
                    "low": 99,
                    "close": 105.2,
                    "volume_ratio": 2.0,
                }
            ]
            + [{"open": 104, "high": 105, "low": 103.5, "close": 104.5, "volume_ratio": 1.0}] * 8
            + [{"open": 104, "high": 105.5, "low": 103.8, "close": 105.2, "volume_ratio": 1.1}]
        )
        zone = Zone(
            price_low=104.0,
            price_high=105.0,
            mid=104.5,
            touches=2,
            last_touch_time=df["time"].iloc[0].to_pydatetime(),
            strength=2.0,
            role="support",
            origin="high",
            flipped=True,
        )
        as_of = pd.to_datetime(df["close_time"].iloc[-1], unit="ms", utc=True).to_pydatetime()
        htf = {"1h": TrendResult(TrendBias.NEUTRAL)}
        ctx = StrategyContext(
            symbol="BTCUSDT",
            timeframe="15m",
            df=df,
            htf_trends=htf,
            zones=(zone,),
            as_of=as_of,
            tick_size=0.1,
        )
        cand = detect(ctx)
        self.assertIsNotNone(cand)
        self.assertEqual(cand.direction, Direction.LONG)
        self.assertEqual(cand.strategy, "breakout_retest")

    def test_short_mirror(self) -> None:
        df = _df(
            [{"open": 100, "high": 101, "low": 99, "close": 100, "volume_ratio": 1.0}] * 10
            + [{"open": 100, "high": 101, "low": 94, "close": 94.8, "volume_ratio": 2.0}]
            + [{"open": 96, "high": 97, "low": 95, "close": 96, "volume_ratio": 1.0}] * 8
            + [{"open": 96, "high": 96.5, "low": 94.5, "close": 95.2, "volume_ratio": 1.1}]
        )
        zone = Zone(
            price_low=95.0,
            price_high=96.0,
            mid=95.5,
            touches=2,
            last_touch_time=df["time"].iloc[0].to_pydatetime(),
            strength=2.0,
            role="resistance",
            origin="low",
            flipped=True,
        )
        as_of = pd.to_datetime(df["close_time"].iloc[-1], unit="ms", utc=True).to_pydatetime()
        ctx = StrategyContext(
            symbol="BTCUSDT",
            timeframe="15m",
            df=df,
            htf_trends={"1h": TrendResult(TrendBias.NEUTRAL)},
            zones=(zone,),
            as_of=as_of,
            tick_size=0.1,
        )
        cand = detect(ctx)
        self.assertIsNotNone(cand)
        self.assertEqual(cand.direction, Direction.SHORT)

    def test_failed_retest_no_signal(self) -> None:
        df = _df(
            [{"open": 100, "high": 101, "low": 99, "close": 100, "volume_ratio": 1.0}] * 10
            + [{"open": 100, "high": 106, "low": 99, "close": 105, "volume_ratio": 2.0}]
            + [{"open": 104, "high": 105, "low": 103, "close": 104, "volume_ratio": 1.0}] * 8
            + [{"open": 104, "high": 104.5, "low": 103.0, "close": 103.2, "volume_ratio": 1.1}]
        )
        zone = Zone(
            104.0,
            105.0,
            104.5,
            2,
            df["time"].iloc[0].to_pydatetime(),
            2.0,
            "support",
            "high",
        )
        as_of = pd.to_datetime(df["close_time"].iloc[-1], unit="ms", utc=True).to_pydatetime()
        ctx = StrategyContext(
            symbol="BTCUSDT",
            timeframe="15m",
            df=df,
            htf_trends={"1h": TrendResult(TrendBias.NEUTRAL)},
            zones=(zone,),
            as_of=as_of,
            tick_size=0.1,
        )
        self.assertIsNone(detect(ctx))


if __name__ == "__main__":
    unittest.main()