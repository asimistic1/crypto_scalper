"""
Setup builder tests (Phase 2 step 6).
Run: python tests/test_setup_builder.py
"""

from __future__ import annotations

import random
import sys
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.config import MIN_24H_QUOTE_VOLUME_USDT, MIN_SETUP_SCORE
from core.indicators import add_all_indicators
from core.models import Direction, EntryType
from core.setup_builder import _order_valid, _round_price, _rr_triple, build_setup


def _bars(n: int, base: float = 100.0, step: float = 0.4) -> pd.DataFrame:
    start = datetime(2024, 8, 1, tzinfo=timezone.utc)
    rows = []
    for i in range(n):
        t = start + timedelta(minutes=15 * i)
        c = base + i * step
        close_ms = int((t + timedelta(minutes=15) - timedelta(milliseconds=1)).timestamp() * 1000)
        rows.append(
            {
                "time": t,
                "open": c - 0.05,
                "high": c + 1.0,
                "low": c - 1.0,
                "close": c,
                "volume": 50_000.0,
                "close_time": close_ms,
            }
        )
    return pd.DataFrame(rows)


def _htf_bull(n: int = 300) -> pd.DataFrame:
    return _bars(n, base=5000, step=2.0)


def _craft_long_signal(df: pd.DataFrame) -> pd.DataFrame:
    df = add_all_indicators(df.copy())
    prev = df.iloc[-2].copy()
    cur = df.iloc[-1].copy()
    cur["low"] = float(cur["ema_21"])
    cur["high"] = float(cur["ema_21"]) + 0.5
    cur["close"] = float(prev["high"]) + 0.2
    cur["open"] = float(cur["ema_21"])
    cur["rsi_14"] = 48.0
    prev["rsi_14"] = 45.0
    cur["volume_ratio"] = 1.3
    # Keep ATR% in band
    cur["atr_14"] = float(cur["close"]) * 0.01
    df.iloc[-2] = prev
    df.iloc[-1] = cur
    return df


class SetupBuilderTests(unittest.TestCase):
    def test_rounding_long_conservative(self) -> None:
        tick = Decimal("0.1")
        self.assertEqual(_round_price(100.17, tick, "down"), 100.1)
        self.assertEqual(_round_price(100.17, tick, "up"), 100.2)

    def test_rr_math_net_below_gross(self) -> None:
        gross, net, _ = _rr_triple(Direction.LONG, 100.0, 98.0, (103.0, 106.0, 109.0))
        self.assertGreater(gross[0], net[0])
        self.assertGreater(net[0], 0.0)

    def test_order_valid_long_short(self) -> None:
        self.assertTrue(_order_valid(Direction.LONG, 100, 98, (102, 104, 106)))
        self.assertTrue(_order_valid(Direction.SHORT, 100, 102, (98, 96, 94)))
        self.assertFalse(_order_valid(Direction.LONG, 100, 101, (102, 103, 104)))

    def test_guard_low_volume(self) -> None:
        df = _craft_long_signal(_bars(260))
        as_of = pd.to_datetime(df["close_time"].iloc[-1], unit="ms", utc=True).to_pydatetime()
        out = build_setup(
            "BTCUSDT",
            "15m",
            df,
            {"1h": _htf_bull()},
            None,
            as_of,
            0.1,
            1_000_000.0,
        )
        self.assertEqual(out.direction, Direction.NO_TRADE)
        self.assertTrue(any("24h" in r.lower() for r in out.reasons))

    def test_guard_not_enough_candles(self) -> None:
        df = _bars(100)
        as_of = pd.to_datetime(df["close_time"].iloc[-1], unit="ms", utc=True).to_pydatetime()
        out = build_setup("BTCUSDT", "15m", df, {}, None, as_of, 0.1, MIN_24H_QUOTE_VOLUME_USDT + 1)
        self.assertIn("250", out.reasons[0])

    def test_determinism(self) -> None:
        df = _craft_long_signal(_bars(260))
        as_of = pd.to_datetime(df["close_time"].iloc[-1], unit="ms", utc=True).to_pydatetime()
        kwargs = dict(
            symbol="BTCUSDT",
            timeframe="15m",
            ltf_df=df,
            htf_dfs={"1h": _htf_bull()},
            daily_df=None,
            as_of=as_of,
            tick_size=0.1,
            quote_volume_24h=MIN_24H_QUOTE_VOLUME_USDT * 2,
        )
        a = build_setup(**kwargs)
        b = build_setup(**kwargs)
        self.assertEqual(a.setup_id, b.setup_id)
        self.assertEqual(a.entry, b.entry)
        self.assertEqual(a.reasons, b.reasons)

    def test_no_lookahead_random_points(self) -> None:
        random.seed(42)
        full = _bars(320, base=100.0, step=0.25)
        indices = random.sample(range(250, 310), 30)
        for i in indices:
            as_of = pd.to_datetime(full["close_time"].iloc[i], unit="ms", utc=True).to_pydatetime()
            truncated = full.iloc[: i + 1].copy()
            a = build_setup(
                "BTCUSDT",
                "15m",
                truncated,
                {"1h": _htf_bull()},
                None,
                as_of,
                0.1,
                MIN_24H_QUOTE_VOLUME_USDT * 2,
            )
            b = build_setup(
                "BTCUSDT",
                "15m",
                full,
                {"1h": _htf_bull()},
                None,
                as_of,
                0.1,
                MIN_24H_QUOTE_VOLUME_USDT * 2,
            )
            self.assertEqual(a.setup_id, b.setup_id, msg=f"mismatch at bar {i}")
            self.assertEqual(a.direction, b.direction)
            self.assertEqual(a.entry, b.entry)
            self.assertEqual(a.stop_loss, b.stop_loss)

    def test_trend_pullback_can_produce_long_or_reject_with_score(self) -> None:
        df = _craft_long_signal(_bars(260))
        as_of = pd.to_datetime(df["close_time"].iloc[-1], unit="ms", utc=True).to_pydatetime()
        out = build_setup(
            "BTCUSDT",
            "15m",
            df,
            {"1h": _htf_bull(), "4h": _htf_bull()},
            None,
            as_of,
            0.1,
            MIN_24H_QUOTE_VOLUME_USDT * 2,
        )
        if out.direction == Direction.LONG:
            self.assertIn(out.entry_type, (EntryType.MARKET, EntryType.LIMIT))
            self.assertGreaterEqual(out.score, 0)
        elif out.rejected_candidate:
            self.assertGreater(out.rejected_candidate.score, 0)
        else:
            self.assertEqual(out.direction, Direction.NO_TRADE)


if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    if result.wasSuccessful():
        print("\nSETUP BUILDER TESTS PASSED")
    sys.exit(0 if result.wasSuccessful() else 1)