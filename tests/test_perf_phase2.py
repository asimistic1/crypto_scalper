"""
Phase 2 performance targets (run via pytest, no network).
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.config import HIGHER_TIMEFRAMES, MIN_24H_QUOTE_VOLUME_USDT
from core.setup_builder import build_setup
from core.weight_budget import reset_for_tests, weight_used_this_minute
from core.candle_store import get_closed_candles, reset_for_tests as reset_candle_store
from unittest.mock import patch


def _make_df(n: int, period_min: int = 15) -> pd.DataFrame:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    rows = []
    for i in range(n):
        t = start + timedelta(minutes=period_min * i)
        c = 50_000.0 + i * 5.0
        close_ms = int((t + timedelta(minutes=period_min) - timedelta(milliseconds=1)).timestamp() * 1000)
        rows.append(
            {
                "time": t,
                "open": c - 2,
                "high": c + 10,
                "low": c - 10,
                "close": c,
                "volume": 100_000.0,
                "close_time": close_ms,
            }
        )
    return pd.DataFrame(rows)


@pytest.fixture(autouse=True)
def _reset_stores() -> None:
    reset_for_tests()
    reset_candle_store()


def test_build_setup_under_150ms() -> None:
    ltf = _make_df(1000)
    htf_dfs = {"1h": _make_df(300, 60), "4h": _make_df(300, 240)}
    daily = _make_df(100, 24 * 60)
    as_of = pd.to_datetime(ltf["close_time"].iloc[-1], unit="ms", utc=True).to_pydatetime()
    t0 = time.perf_counter()
    build_setup(
        "BTCUSDT",
        "15m",
        ltf,
        htf_dfs,
        daily,
        as_of,
        0.1,
        MIN_24H_QUOTE_VOLUME_USDT * 2,
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    assert elapsed_ms < 150.0, f"build_setup took {elapsed_ms:.1f} ms (target <150)"


def test_incremental_refresh_weight_budget() -> None:
    """Simulate tail refresh: weight budget should stay tiny (≤3 for limit=3)."""
    reset_for_tests()
    with patch("core.candle_store._fetch_klines") as mock_fetch:
        mock_fetch.return_value = _make_df(3)
        with patch("core.candle_store.binance_server_time_ms", return_value=9_999_999_999_000):
            with patch("core.candle_store._integrity_ok", return_value=True):
                reset_candle_store()
                w0 = weight_used_this_minute()
                # First fill store
                get_closed_candles("BTCUSDT", "15m", full=True)
                w1 = weight_used_this_minute()
                # Incremental tail
                get_closed_candles("BTCUSDT", "15m")
                w2 = weight_used_this_minute()
    delta_tail = w2 - w1
    assert delta_tail <= 3, f"incremental delta weight {delta_tail} (target ≤3)"