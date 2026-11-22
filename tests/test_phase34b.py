"""Phase 3.4b — BTC 1d regime at signal."""

from __future__ import annotations

import numpy as np

from backtest.diagnostics import regime_at_signal, _d1_regime_cache


def test_regime_uses_last_closed_daily_before_signal(monkeypatch):
    _d1_regime_cache.clear()
    ct = np.array([86_400_000, 172_800_000, 259_200_000], dtype=np.int64)
    close = np.array([90.0, 100.0, 110.0], dtype=np.float64)
    ema = np.array([95.0, 98.0, 102.0], dtype=np.float64)

    import backtest.diagnostics as diag

    monkeypatch.setattr(diag, "_d1_regime_arrays", lambda _sym: (ct, close, ema))
    assert regime_at_signal("BTCUSDT", 86_400_000) == "unknown"
    assert regime_at_signal("BTCUSDT", 86_400_001) == "below_ema200"
    assert regime_at_signal("BTCUSDT", 200_000_000) == "above_ema200"
    assert regime_at_signal("BTCUSDT", 259_200_000) == "above_ema200"
    assert regime_at_signal("BTCUSDT", 259_200_001) == "above_ema200"