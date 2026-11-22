"""Metrics timestamps align with kline close_time ms."""

from research.aux_data import load_metrics_5m
from backtest.history import load_history


def test_metrics_close_time_ms_scale():
    m = load_metrics_5m("BTCUSDT")
    h = load_history("BTCUSDT", "1h")
    assert m["close_time"].max() > 10**12
    overlap = m["close_time"].between(h["close_time"].min(), h["close_time"].max())
    assert overlap.mean() > 0.5