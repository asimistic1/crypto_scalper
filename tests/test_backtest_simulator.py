"""Simulator rule tests (hand-built candles)."""

from __future__ import annotations

import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backtest.config import BacktestConfig
from backtest.simulator import Outcome, SimSignal, simulate_trade
from core.models import Direction, EntryType


def _df(rows: list[dict]) -> pd.DataFrame:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    out = []
    for i, r in enumerate(rows):
        t = start + timedelta(minutes=15 * i)
        out.append(
            {
                "time": t,
                "open": r["open"],
                "high": r["high"],
                "low": r["low"],
                "close": r["close"],
                "volume": 1000.0,
                "close_time": int((t + timedelta(minutes=14)).timestamp() * 1000),
            }
        )
    return pd.DataFrame(out)


class SimulatorTests(unittest.TestCase):
    def test_market_long_tp1(self) -> None:
        df = _df(
            [
                {"open": 100, "high": 101, "low": 99, "close": 100},
                {"open": 100, "high": 103, "low": 99.5, "close": 102},
                {"open": 102, "high": 106, "low": 101, "close": 105},
            ]
        )
        sig = SimSignal(
            Direction.LONG,
            EntryType.MARKET,
            entry=100.0,
            stop_loss=98.0,
            tp1=104.0,
            tp2=106.0,
            tp3=108.0,
            signal_bar=0,
        )
        cfg = BacktestConfig()
        tr = simulate_trade(df, sig, cfg, exit_model="tp1_full")
        self.assertTrue(tr.filled)
        self.assertEqual(tr.outcome, Outcome.TP1.value)

    def test_gap_through_sl_long(self) -> None:
        df = _df(
            [
                {"open": 100, "high": 101, "low": 99, "close": 100},
                {"open": 100, "high": 100.5, "low": 99.8, "close": 100.2},
                {"open": 96.0, "high": 97, "low": 95, "close": 96.5},
            ]
        )
        sig = SimSignal(Direction.LONG, EntryType.MARKET, 100, 97.5, 105, 106, 107, 0)
        tr = simulate_trade(df, sig, BacktestConfig(), exit_model="tp1_full")
        self.assertEqual(tr.outcome, Outcome.SL.value)
        self.assertLess(tr.exit_price, 97.5)

    def test_same_bar_sl_before_tp(self) -> None:
        df = _df(
            [
                {"open": 100, "high": 101, "low": 99, "close": 100},
                {"open": 100, "high": 105, "low": 97, "close": 101},
            ]
        )
        sig = SimSignal(Direction.LONG, EntryType.MARKET, 100, 98, 104, 106, 108, 0)
        tr = simulate_trade(df, sig, BacktestConfig(), exit_model="tp1_full")
        self.assertEqual(tr.outcome, Outcome.SL.value)

    def test_limit_expired(self) -> None:
        df = _df(
            [
                {"open": 100, "high": 101, "low": 99, "close": 100},
                {"open": 101, "high": 102, "low": 100.5, "close": 101.5},
                {"open": 101.5, "high": 102, "low": 101.2, "close": 101.8},
                {"open": 102, "high": 102.5, "low": 101.8, "close": 102.2},
            ]
        )
        sig = SimSignal(Direction.LONG, EntryType.LIMIT, 99.5, 97, 105, 106, 107, 0)
        tr = simulate_trade(df, sig, BacktestConfig(), exit_model="tp1_full")
        self.assertFalse(tr.filled)
        self.assertEqual(tr.outcome, Outcome.EXPIRED.value)


if __name__ == "__main__":
    unittest.main()