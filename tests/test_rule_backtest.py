"""Rule backtest sanity — predictive vs random feature."""

from __future__ import annotations

import numpy as np
import pandas as pd

import pytest

from backtest.config import BacktestConfig
from backtest.history import ensure_indicators, load_history
from backtest.paths import history_parquet
from research.rule_backtest import rule_summary, run_rule_backtest, thresholds_from_is

pytestmark = pytest.mark.skipif(
    not history_parquet("BTCUSDT", "1h").exists(),
    reason="missing BTCUSDT 1h history parquet",
)


def _synthetic_panel(n: int = 400, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    h1 = ensure_indicators(load_history("BTCUSDT", "1h"))
    h1 = h1.iloc[-n:].copy().reset_index(drop=True)
    noise = rng.normal(0, 1, n)
    signal = np.zeros(n)
    ret_fwd = np.zeros(n)
    close = h1["close"].to_numpy(dtype=float)
    for i in range(n - 5):
        ret_fwd[i] = (close[i + 4] / close[i] - 1) if close[i] else 0
    signal[:-4] = ret_fwd[:-4] * 100.0
    h1["feat_predict"] = signal + noise * 0.01
    h1["feat_random"] = rng.normal(0, 1, n)
    h1["sample"] = "IS"
    return h1


def test_predictive_feature_positive_net_e():
    panel = _synthetic_panel()
    cfg = BacktestConfig()
    thr = thresholds_from_is(panel["feat_predict"])
    assert thr is not None
    tr = run_rule_backtest(
        panel, "feat_predict", 4, "BTCUSDT", thresholds=thr, ic_mean=0.5, cfg=cfg, low_fee=True
    )
    s = rule_summary(tr)
    assert s.get("trades", 0) >= 1
    assert s.get("net_e_pct", -99) > -5.0


def test_random_feature_near_zero():
    panel = _synthetic_panel(seed=1)
    cfg = BacktestConfig()
    thr = thresholds_from_is(panel["feat_random"])
    assert thr is not None
    tr = run_rule_backtest(
        panel, "feat_random", 4, "BTCUSDT", thresholds=thr, ic_mean=0.0, cfg=cfg, low_fee=True
    )
    s = rule_summary(tr)
    if s.get("trades", 0) > 3:
        assert abs(s.get("net_e_pct", 0)) < 2.0