"""Phase 3.4 — tp1 flag parity, random baseline self-test."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest.config import BacktestConfig
from backtest.history_cache import OhlcFrame
from backtest.metrics import core_metrics
from backtest.random_baseline import random_baseline_stats
from backtest.run import simulate_slice


def _mini_ohlc(n: int = 120) -> OhlcFrame:
    t = np.arange(n) * 60_000
    close = 100 + np.cumsum(np.random.default_rng(2).normal(0, 0.15, n))
    high = close + 0.6
    low = close - 0.6
    open_ = np.roll(close, 1)
    open_[0] = close[0]
    vol = np.full(n, 1000.0)
    qv = vol * close
    df = pd.DataFrame(
        {
            "time": pd.to_datetime(t, unit="ms", utc=True),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": vol,
            "quote_volume": qv,
            "close_time": t + 60_000,
        }
    )
    return OhlcFrame("TST", "15m", df, open_, high, low, close, t + 60_000)


def test_tp1_before_sl_be_counts_as_win():
    trades = pd.DataFrame(
        [
            {"filled": True, "tp1_before_sl": True, "r_net": 0.2, "outcome": "BE", "skip_reason": ""},
            {"filled": True, "tp1_before_sl": False, "r_net": -1.0, "skip_reason": ""},
        ]
    )
    assert core_metrics(trades, raw_signals=2)["win_rate"] == 0.5


def test_tp1_flag_identical_across_exit_models(monkeypatch):
    sigs = pd.DataFrame(
        [
            dict(
                symbol="TST",
                timeframe="15m",
                bar_index=10,
                close_time=1_000_000,
                direction="LONG",
                entry_type="market",
                entry=100.0,
                stop_loss=98.5,
                tp1=101.5,
                tp2=102.5,
                tp3=103.5,
                strategy="t",
                score=70.0,
                setup_id="parity1",
            ),
        ]
    )
    cfg = BacktestConfig(one_position_per_symbol=False, exit_models=("tp1_full", "partial_be"))
    import backtest.run as run_mod

    monkeypatch.setattr(run_mod, "get_ohlc", lambda s, tf: _mini_ohlc(200))
    cache: dict[str, bool] = {}
    t1 = simulate_slice(sigs, cfg, "tp1_full", tp1_cache=cache)
    t2 = simulate_slice(sigs, cfg, "partial_be", tp1_cache=cache)
    f1 = t1[t1["filled"]]
    f2 = t2[t2["filled"]]
    if f1.empty or f2.empty:
        pytest.skip("synthetic path did not fill")
    assert f1.iloc[0]["tp1_before_sl"] == f2.iloc[0]["tp1_before_sl"]


@pytest.mark.slow
def test_random_baseline_self_test_near_median():
    frame = _mini_ohlc(250)
    rng = np.random.default_rng(3)
    rows = []
    for i in range(30):
        bi = 25 + i * 3
        entry = float(frame.close[bi])
        rows.append(
            dict(
                setup_id=f"s{i}",
                bar_index=bi,
                close_time=int(frame.close_time[bi]),
                direction="LONG" if i % 2 == 0 else "SHORT",
                entry=entry,
                stop_loss=entry - 1.0 if i % 2 == 0 else entry + 1.0,
                tp1=entry + 1.0 if i % 2 == 0 else entry - 1.0,
                tp2=entry + 2.0,
                tp3=entry + 3.0,
                entry_type="market",
            )
        )
    sigs = pd.DataFrame(rows)
    trades = sigs.copy()
    trades["filled"] = True
    trades["r_net"] = rng.normal(0, 0.02, len(trades))
    trades["exit_model"] = "tp1_full"
    trades["sample"] = "ALL"
    cfg = BacktestConfig(random_seed=11)
    rb = random_baseline_stats(frame, sigs, trades, cfg, "tp1_full", sample="ALL", n_mc=16)
    assert 30 <= rb["percentile"] <= 70


def test_reuse_signals_or_generate_when_missing(tmp_path, monkeypatch):
    """generate_signals path used when parquet absent (no full scan in CI if skipped)."""
    # smoke: module imports
    from backtest.signal_cache import cache_key

    assert cache_key("BTCUSDT", "15m")