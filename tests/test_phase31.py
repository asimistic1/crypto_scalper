"""Phase 3.1 proof tests (skip when history parquet is missing)."""

from __future__ import annotations

import sys
import time
import unittest
from datetime import UTC, datetime
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backtest.history import load_history, quote_volume_24h_at
from backtest.paths import history_parquet
from backtest.prefilter import candidate_mask
from backtest.signals import evaluate_bar
from backtest.windows import BarWindows
from core.exchange_info import tick_size
from core.models import Direction
from core.setup_builder import build_setup

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
TFS = ("5m", "15m", "1h")


def _history_ready(symbol: str, tf: str) -> bool:
    return history_parquet(symbol, tf).exists()


def _load_pkg(symbol: str, tf: str) -> tuple | None:
    if not _history_ready(symbol, tf):
        return None
    from core.config import HIGHER_TIMEFRAMES

    ltf = load_history(symbol, tf)
    htf_frames = {h: load_history(symbol, h) for h in HIGHER_TIMEFRAMES.get(tf, ()) if _history_ready(symbol, h)}
    daily = load_history(symbol, "1d") if _history_ready(symbol, "1d") else None
    windows = BarWindows.from_frames(tf, ltf, htf_frames, daily)
    tick = float(tick_size(symbol))
    return ltf, htf_frames, daily, windows, tick


@unittest.skipUnless(_history_ready("BTCUSDT", "15m"), "BTCUSDT 15m history required")
class WindowPerfTests(unittest.TestCase):
    def test_build_setup_time_flat(self) -> None:
        pkg = _load_pkg("BTCUSDT", "15m")
        assert pkg is not None
        ltf, htf_frames, daily, windows, tick = pkg
        ltf_ind = __import__("backtest.history", fromlist=["ensure_indicators"]).ensure_indicators(ltf)
        mask = candidate_mask(ltf_ind)
        indices = np.nonzero(mask)[0]
        if len(indices) < 1000:
            indices = np.arange(249, min(249 + 1000, len(ltf)))
        else:
            rng = np.random.default_rng(42)
            indices = rng.choice(indices, size=min(400, len(indices)), replace=False)

        times: list[float] = []
        htf_cache: dict = {}
        warm = int(indices[0])
        build_setup(
            "BTCUSDT",
            "15m",
            windows.ltf_window(warm),
            windows.htf_windows(warm),
            windows.daily_window(warm),
            windows.as_of_dt(warm),
            tick,
            windows.quote_volume_24h(warm),
            htf_trend_cache=htf_cache,
        )
        for i in sorted(indices):
            t0 = time.perf_counter()
            _ = evaluate_bar("BTCUSDT", "15m", windows, int(i), tick, htf_trend_cache=htf_cache)
            times.append(time.perf_counter() - t0)

        p95 = float(np.percentile(times, 95))
        med = float(np.median(times))
        self.assertLess(med * 1000, 500.0, f"median {med*1000:.1f} ms (target 130)")
        self.assertLess(p95 * 1000, 600.0, f"p95 {p95*1000:.1f} ms max {max(times)*1000:.1f} ms")
        tail = float(np.median(times[-50:]))
        head = float(np.median(times[:50]))
        self.assertLess(tail / max(head, 1e-9), 2.5, "per-bar time grew with index")


@unittest.skipUnless(any(_history_ready(s, tf) for s in SYMBOLS for tf in TFS), "no history")
class SupersetMaskTests(unittest.TestCase):
    def test_setups_subset_of_prefilter(self) -> None:
        rng = np.random.default_rng(7)
        for symbol in SYMBOLS:
            for tf in TFS:
                if not _history_ready(symbol, tf):
                    continue
                pkg = _load_pkg(symbol, tf)
                if pkg is None:
                    continue
                ltf, _, _, windows, tick = pkg
                ltf_ind = __import__("backtest.history", fromlist=["ensure_indicators"]).ensure_indicators(ltf)
                mask = candidate_mask(ltf_ind)
                viable = np.arange(249, len(ltf))
                pick = rng.choice(viable, size=min(250, len(viable)), replace=False)
                htf_cache: dict = {}
                for i in pick:
                    row = evaluate_bar(symbol, tf, windows, int(i), tick, htf_trend_cache=htf_cache)
                    if row and not mask[int(i)]:
                        self.fail(f"setup outside mask {symbol} {tf} bar {i}: {row}")


@unittest.skipUnless(_history_ready("BTCUSDT", "15m"), "BTCUSDT 15m history required")
class ParityTests(unittest.TestCase):
    def test_evaluate_matches_analysis_service(self) -> None:
        pkg = _load_pkg("BTCUSDT", "15m")
        assert pkg is not None
        ltf, htf_frames, daily, windows, tick = pkg
        rng = np.random.default_rng(99)
        indices = rng.choice(np.arange(300, len(ltf) - 1), size=50, replace=False)
        htf_cache: dict = {}

        for i in indices:
            i = int(i)
            as_of = windows.as_of_dt(i)
            qv = windows.quote_volume_24h(i)
            bt = evaluate_bar("BTCUSDT", "15m", windows, i, tick, htf_trend_cache=htf_cache)
            setup = build_setup(
                "BTCUSDT",
                "15m",
                windows.ltf_window(i),
                windows.htf_windows(i),
                windows.daily_window(i),
                as_of,
                tick,
                qv,
                htf_trend_cache={},
            )
            if bt is None:
                self.assertNotIn(setup.direction, (Direction.LONG, Direction.SHORT))
            else:
                self.assertEqual(bt["direction"], setup.direction.value)
                self.assertEqual(bt["strategy"], setup.strategy)
                self.assertAlmostEqual(bt["entry"], setup.entry, places=6)


@unittest.skipUnless(_history_ready("BTCUSDT", "15m"), "BTCUSDT 15m history required")
class LookAheadTests(unittest.TestCase):
    def test_future_bars_do_not_change_past_setups(self) -> None:
        pkg = _load_pkg("BTCUSDT", "15m")
        assert pkg is not None
        ltf, htf_frames, daily, windows_full, tick = pkg
        cut = len(ltf) - 500
        if cut < 400:
            self.skipTest("history too short")
        ltf_short = ltf.iloc[:cut].copy()
        windows_short = BarWindows.from_frames("15m", ltf_short, htf_frames, daily)
        htf_cache: dict = {}
        baseline: dict[int, dict | None] = {}
        sample = range(300, cut - 10, max(1, (cut - 310) // 80))
        for i in sample:
            baseline[i] = evaluate_bar("BTCUSDT", "15m", windows_short, i, tick, htf_trend_cache=htf_cache)

        windows_long = BarWindows.from_frames("15m", ltf, htf_frames, daily)
        htf_cache2: dict = {}
        for i, row in baseline.items():
            row2 = evaluate_bar("BTCUSDT", "15m", windows_long, i, tick, htf_trend_cache=htf_cache2)
            self.assertEqual(row, row2, f"lookahead drift at bar {i}")


class QuoteVolume24hTests(unittest.TestCase):
    def test_low_volume_no_trade(self) -> None:
        from datetime import timedelta

        rows = []
        start = datetime(2024, 1, 1, tzinfo=UTC)
        for i in range(30):
            t = start + timedelta(minutes=15 * i)
            rows.append(
                {
                    "time": t,
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.0,
                    "volume": 1.0,
                    "quote_volume": 100.0,
                    "close_time": int((t + timedelta(minutes=14)).timestamp() * 1000),
                }
            )
        df = pd.DataFrame(rows)
        as_of = rows[-1]["time"]
        qv = quote_volume_24h_at(df, as_of)
        self.assertLess(qv, 50_000_000)
        tick = 0.1
        setup = build_setup(
            "BTCUSDT",
            "15m",
            df,
            {},
            None,
            as_of,
            tick,
            qv,
        )
        self.assertEqual(setup.direction, Direction.NO_TRADE)


if __name__ == "__main__":
    unittest.main()