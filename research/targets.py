"""Forward return targets (cost-aware) for edge research."""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.config import BacktestConfig


def _round_trip_frac(cfg: BacktestConfig, *, low_fee: bool) -> float:
    if low_fee:
        return 2 * (cfg.low_fee_taker + cfg.slippage)
    if cfg.fee_model == "conservative":
        return 2 * (cfg.taker_fee + cfg.slippage)
    return 2 * (cfg.taker_fee + cfg.slippage)


def add_forward_targets(
    df: pd.DataFrame,
    cfg: BacktestConfig,
    horizons: tuple[int, ...] = (1, 4, 12, 24),
) -> pd.DataFrame:
    """Add simple and log forward returns; net = simple minus round-trip cost fraction."""
    out = df.copy()
    close = out["close"].astype(float)
    cost_std = _round_trip_frac(cfg, low_fee=False)
    cost_low = _round_trip_frac(cfg, low_fee=True)
    for h in horizons:
        fwd = close.shift(-h) / close - 1.0
        out[f"fwd_ret_{h}"] = fwd
        out[f"fwd_log_ret_{h}"] = np.log(close.shift(-h) / close)
        out[f"fwd_net_std_{h}"] = fwd - cost_std
        out[f"fwd_net_low_{h}"] = fwd - cost_low
    return out