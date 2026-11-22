"""Phase 3.3 — honest metrics, one-position, IS/OOS, costs, random baseline."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest.config import BacktestConfig
from backtest.costs import cost_sensitivity_slice, recompute_net_r_row
from backtest.history_cache import OhlcFrame
from backtest.metrics import core_metrics
from backtest.position import busy_until_bar
from backtest.random_baseline import random_baseline_percentile
from backtest.run import simulate_slice
from backtest.split import split_times_ms, tag_sample


def _mini_ohlc(n: int = 80) -> OhlcFrame:
    t = np.arange(n) * 60_000
    close = 100 + np.cumsum(np.random.default_rng(0).normal(0, 0.2, n))
    high = close + 0.5
    low = close - 0.5
    open_ = np.roll(close, 1)
    open_[0] = close[0]
    df = pd.DataFrame(
        {
            "time": pd.to_datetime(t, unit="ms", utc=True),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "close_time": t + 60_000,
        }
    )
    return OhlcFrame("TST", "15m", df, open_, high, low, close, t + 60_000)


def test_one_position_skips_overlap(monkeypatch):
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
                stop_loss=99.0,
                tp1=101.0,
                tp2=102.0,
                tp3=103.0,
                strategy="t",
                score=70.0,
                setup_id="a",
            ),
            dict(
                symbol="TST",
                timeframe="15m",
                bar_index=11,
                close_time=1_100_000,
                direction="LONG",
                entry_type="market",
                entry=100.0,
                stop_loss=99.0,
                tp1=101.0,
                tp2=102.0,
                tp3=103.0,
                strategy="t",
                score=70.0,
                setup_id="b",
            ),
        ]
    )
    cfg = BacktestConfig(one_position_per_symbol=True, exit_models=("tp1_full",))
    calls = {"n": 0}

    def fake_sim(df, signal, cfg, **kw):
        calls["n"] += 1
        from backtest.simulator import SimTrade
        from datetime import datetime, UTC

        return SimTrade(
            symbol="TST",
            timeframe="15m",
            exit_model="tp1_full",
            direction="LONG",
            strategy="t",
            score=70.0,
            entry_type="market",
            signal_time=datetime.now(tz=UTC),
            fill_time=datetime.now(tz=UTC),
            exit_time=datetime.now(tz=UTC),
            entry_price=100.0,
            exit_price=101.0,
            outcome="TP1",
            r_gross=1.0,
            r_net=0.9,
            fees_paid=0.0,
            funding_paid=0.0,
            bars_held=5,
            mae_r=0.0,
            mfe_r=1.0,
            filled=True,
            tp1_before_sl=True,
            exit_bar=signal.signal_bar + 5,
            fill_bar=signal.signal_bar + 1,
        )

    import backtest.run as run_mod

    monkeypatch.setattr(run_mod, "simulate_trade", fake_sim)
    monkeypatch.setattr(run_mod, "get_ohlc", lambda s, tf: _mini_ohlc())
    trades = simulate_slice(sigs, cfg, "tp1_full")
    skipped = trades[trades["skip_reason"] == "position_busy"]
    assert len(skipped) == 1
    assert calls["n"] == 1


def test_tp1_before_sl_win_definition():
    trades = pd.DataFrame(
        [
            {"filled": True, "tp1_before_sl": True, "r_net": 1.0, "skip_reason": ""},
            {"filled": True, "tp1_before_sl": False, "r_net": -1.0, "skip_reason": ""},
            {"filled": True, "tp1_before_sl": True, "r_net": 0.2, "outcome": "BE", "skip_reason": ""},
        ]
    )
    m = core_metrics(trades, raw_signals=3)
    assert m["win_rate"] == pytest.approx(2 / 3)


def test_is_oos_split_boundary():
    cfg = BacktestConfig(in_sample_fraction=0.6)
    ct = pd.Series([0, 100, 200, 300, 400, 500])
    cutoff = split_times_ms(ct, cfg)
    assert cutoff == 300
    df = pd.DataFrame({"close_time": ct, "x": 1})
    tagged = tag_sample(df, cfg)
    assert tagged.iloc[0]["sample"] == "IS"
    assert tagged.iloc[-1]["sample"] == "OOS"
    assert tagged.iloc[3]["sample"] == "OOS"


def test_cost_sensitivity_hand_trade():
    cfg = BacktestConfig()
    row = pd.Series(
        {
            "filled": True,
            "entry_price": 100.0,
            "exit_price": 102.0,
            "direction": "LONG",
            "entry_type": "MARKET",
            "entry": 100.0,
            "stop_loss": 99.0,
            "r_net": 1.5,
        }
    )
    base = recompute_net_r_row(row, cfg, 1.0)
    high = recompute_net_r_row(row, cfg, 2.0)
    assert high < base
    df = pd.DataFrame([row])
    s15 = cost_sensitivity_slice(df, cfg, 1.5)
    assert s15["expectancy_r"] < base


def test_random_baseline_deterministic():
    frame = _mini_ohlc(120)
    sigs = pd.DataFrame(
        [
            dict(
                setup_id="x",
                bar_index=30,
                close_time=int(frame.close_time[30]),
                direction="LONG",
                entry_type="market",
                entry=float(frame.close[30]),
                stop_loss=float(frame.close[30]) - 1.0,
                tp1=float(frame.close[30]) + 1.0,
                tp2=float(frame.close[30]) + 2.0,
                tp3=float(frame.close[30]) + 3.0,
            )
        ]
    )
    trades = pd.DataFrame(
        [
            {
                "filled": True,
                "r_net": 0.1,
                "setup_id": "x",
                "exit_model": "tp1_full",
                "sample": "ALL",
                "bar_index": 30,
                "close_time": int(frame.close_time[30]),
                "direction": "LONG",
                "entry_type": "MARKET",
                "entry": float(frame.close[30]),
                "stop_loss": float(frame.close[30]) - 1.0,
                "tp1": float(frame.close[30]) + 1.0,
                "tp2": float(frame.close[30]) + 2.0,
                "tp3": float(frame.close[30]) + 3.0,
            }
        ]
    )
    cfg = BacktestConfig(random_seed=99)
    kwargs = dict(n_mc=8)
    a = random_baseline_percentile(frame, sigs, trades, cfg, "tp1_full", sample="ALL", **kwargs)
    b = random_baseline_percentile(frame, sigs, trades, cfg, "tp1_full", sample="ALL", **kwargs)
    assert a == b


@pytest.mark.slow
def test_pure_random_near_median():
    """Strategy with zero edge should land near 50th percentile vs random baseline."""
    frame = _mini_ohlc(200)
    rng = np.random.default_rng(1)
    rows = []
    for i in range(25):
        bi = 20 + i * 3
        entry = float(frame.close[bi])
        rows.append(
            dict(
                setup_id=f"s{i}",
                bar_index=bi,
                close_time=int(frame.close_time[bi]),
                direction="LONG" if i % 2 == 0 else "SHORT",
                entry_type="market",
                entry=entry,
                stop_loss=entry - 1.0 if i % 2 == 0 else entry + 1.0,
                tp1=entry + 1.0 if i % 2 == 0 else entry - 1.0,
                tp2=entry + 2.0,
                tp3=entry + 3.0,
            )
        )
    sigs = pd.DataFrame(rows)
    trades = sigs.copy()
    trades["filled"] = True
    trades["r_net"] = rng.normal(0, 0.01, len(trades))
    trades["exit_model"] = "tp1_full"
    trades["sample"] = "ALL"
    cfg = BacktestConfig(random_seed=7)
    pct = random_baseline_percentile(frame, sigs, trades, cfg, "tp1_full", sample="ALL", n_mc=40)
    assert 25 <= pct <= 75


def test_busy_until_unfilled():
    assert busy_until_bar(10, filled=False, fill_bar=None, exit_bar=None, outcome="EXPIRED") == 10 + 3