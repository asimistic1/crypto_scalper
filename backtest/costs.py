"""Recompute net R with scaled fees/slippage from actual fills."""

from __future__ import annotations

import pandas as pd

from backtest.config import BacktestConfig


def _fee_rates(cfg: BacktestConfig, mult: float, *, is_maker: bool) -> float:
    if cfg.fee_model == "conservative":
        return (cfg.taker_fee + cfg.slippage) * mult
    fee = cfg.maker_fee if is_maker else cfg.taker_fee
    return (fee + cfg.slippage) * mult


def recompute_net_r_row(
    row: pd.Series,
    cfg: BacktestConfig,
    mult: float,
) -> float:
    if not row.get("filled"):
        return 0.0
    entry = float(row["entry_price"])
    exit_p = float(row["exit_price"])
    risk = abs(float(row.get("entry_level", row.get("entry", entry))) - float(row["stop_loss"]))
    if risk <= 0:
        return float(row["r_net"])
    direction = str(row["direction"])
    legs = 1.0
    if direction == "LONG":
        gross = (exit_p - entry) / risk * legs
    else:
        gross = (entry - exit_p) / risk * legs
    entry_type = str(row.get("entry_type", "MARKET"))
    maker_entry = entry_type not in ("MARKET", "market") and cfg.fee_model != "conservative"
    fee_entry = entry * _fee_rates(cfg, mult, is_maker=maker_entry)
    fee_exit = exit_p * _fee_rates(cfg, mult, is_maker=False)
    fee_r = (fee_entry + fee_exit) / risk
    return gross - fee_r


def cost_sensitivity_slice(trades: pd.DataFrame, cfg: BacktestConfig, mult: float) -> dict[str, float]:
    filled = trades[trades["filled"]].copy()
    if filled.empty:
        return {"expectancy_r": 0.0, "profit_factor": 0.0}
    adj = filled.apply(lambda r: recompute_net_r_row(r, cfg, mult), axis=1)
    gross_w = adj[adj > 0].sum()
    gross_l = abs(adj[adj < 0].sum())
    pf = float(gross_w / gross_l) if gross_l > 0 else float("inf")
    return {"expectancy_r": float(adj.mean()), "profit_factor": pf}