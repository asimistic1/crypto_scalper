"""Backtest metrics, honesty checks, baselines."""

from __future__ import annotations

import math
import random
from typing import Any

import numpy as np
import pandas as pd

from backtest.config import BacktestConfig
from backtest.costs import cost_sensitivity_slice

MIN_BUCKET_TRADES = 100


def wilson_ci(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = wins / n
    denom = 1 + z**2 / n
    centre = p + z**2 / (2 * n)
    margin = z * math.sqrt((p * (1 - p) + z**2 / (4 * n)) / n)
    lo = (centre - margin) / denom
    hi = (centre + margin) / denom
    return max(0.0, lo), min(1.0, hi)


def bootstrap_mean_ci(values: list[float], n_boot: int = 500, seed: int = 42) -> tuple[float, float, float]:
    if not values:
        return 0.0, 0.0, 0.0
    rng = random.Random(seed)
    means = []
    for _ in range(n_boot):
        sample = [values[rng.randrange(len(values))] for _ in range(len(values))]
        means.append(float(np.mean(sample)))
    means.sort()
    lo = means[int(0.025 * len(means))]
    hi = means[int(0.975 * len(means)) - 1]
    return float(np.mean(values)), lo, hi


def core_metrics(
    trades: pd.DataFrame,
    *,
    raw_signals: int | None = None,
    cfg: BacktestConfig | None = None,
) -> dict[str, Any]:
    """trades includes skipped rows (position_busy) with filled=False for signal counts."""
    skipped = trades[trades.get("skip_reason", "") == "position_busy"] if "skip_reason" in trades.columns else pd.DataFrame()
    sim_rows = trades[trades.get("skip_reason", "") != "position_busy"] if "skip_reason" in trades.columns else trades
    n_sig = raw_signals if raw_signals is not None else len(sim_rows) + len(skipped)
    filled = sim_rows[sim_rows["filled"]]
    n = len(filled)
    taken = len(sim_rows)
    if n == 0:
        out: dict[str, Any] = {
            "signals": n_sig,
            "trades_taken": taken,
            "trades": 0,
            "skipped_busy": len(skipped),
            "fill_rate": 0.0,
        }
        if cfg is not None:
            out["cost_1_5_expectancy"] = 0.0
            out["cost_2_0_expectancy"] = 0.0
        return out
    if "tp1_before_sl" not in filled.columns:
        wins_mask = filled["outcome"].isin(("TP1", "TP2", "TP3"))
    else:
        wins_mask = filled["tp1_before_sl"].astype(bool)
    wlo, whi = wilson_ci(int(wins_mask.sum()), n)
    r_net = filled["r_net"].astype(float)
    expectancy, exp_lo, exp_hi = bootstrap_mean_ci(r_net.tolist())
    gross_w = filled.loc[r_net > 0, "r_net"].sum()
    gross_l = abs(filled.loc[r_net < 0, "r_net"].sum())
    pf = float(gross_w / gross_l) if gross_l > 0 else float("inf")
    eq = r_net.cumsum()
    dd = float((eq - eq.cummax()).min())
    out = {
        "signals": n_sig,
        "trades_taken": taken,
        "trades": n,
        "skipped_busy": len(skipped),
        "fill_rate": n / taken if taken else 0.0,
        "win_rate": float(wins_mask.mean()),
        "win_rate_ci": (wlo, whi),
        "expectancy_r": expectancy,
        "expectancy_ci": (exp_lo, exp_hi),
        "profit_factor": pf,
        "total_net_r": float(r_net.sum()),
        "max_dd_r": dd,
        "avg_win_r": float(filled.loc[r_net > 0, "r_net"].mean()) if (r_net > 0).any() else 0.0,
        "avg_loss_r": float(filled.loc[r_net < 0, "r_net"].mean()) if (r_net < 0).any() else 0.0,
    }
    if cfg is not None:
        out["cost_1_5_expectancy"] = cost_sensitivity_slice(filled, cfg, 1.5)["expectancy_r"]
        out["cost_2_0_expectancy"] = cost_sensitivity_slice(filled, cfg, 2.0)["expectancy_r"]
    return out


def score_calibration(trades: pd.DataFrame) -> pd.DataFrame:
    filled = trades[trades["filled"]].copy()
    if filled.empty:
        return pd.DataFrame()
    if "tp1_before_sl" in filled.columns:
        win = filled["tp1_before_sl"].astype(bool)
    else:
        win = filled["outcome"].isin(("TP1", "TP2", "TP3"))
    filled["_win"] = win
    filled["bucket"] = pd.cut(
        filled["score"],
        bins=[55, 60, 65, 70, 75, 80, 85, 90, 95, 100],
        right=False,
    )
    rows = []
    for b, grp in filled.groupby("bucket", observed=True):
        n = len(grp)
        wins = int(grp["_win"].sum())
        lo, hi = wilson_ci(wins, n)
        rows.append(
            {
                "bucket": str(b),
                "trades": n,
                "win_rate": wins / n if n else 0.0,
                "ci_low": lo,
                "ci_high": hi,
                "avg_net_r": float(grp["r_net"].mean()),
                "note": "" if n >= MIN_BUCKET_TRADES else "not enough data",
            }
        )
    return pd.DataFrame(rows)


def _rankdata(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=np.float64)
    ranks[order] = np.arange(1, len(values) + 1, dtype=np.float64)
    return ranks


def spearman_score_r(trades: pd.DataFrame) -> float | None:
    filled = trades[trades["filled"]]
    if len(filled) < 10:
        return None
    x = filled["score"].astype(float).to_numpy()
    y = filled["r_net"].astype(float).to_numpy()
    rx = _rankdata(x)
    ry = _rankdata(y)
    rx = rx - rx.mean()
    ry = ry - ry.mean()
    denom = float(np.sqrt((rx**2).sum() * (ry**2).sum()))
    if denom <= 0:
        return None
    return float((rx * ry).sum() / denom)


def monte_carlo_max_dd(trades: pd.DataFrame, *, n: int = 1000, seed: int = 42) -> float:
    filled = trades[trades["filled"]]
    r = filled["r_net"].astype(float).tolist()
    if not r:
        return 0.0
    rng = random.Random(seed)
    dds: list[float] = []
    for _ in range(n):
        shuffled = r[:]
        rng.shuffle(shuffled)
        eq = np.cumsum(shuffled)
        dd = float((eq - np.maximum.accumulate(eq)).min())
        dds.append(dd)
    dds.sort()
    return dds[int(0.95 * len(dds)) - 1]


def too_good_alarm(metrics: dict[str, Any], scope: str) -> list[str]:
    alarms: list[str] = []
    n = metrics.get("trades", 0)
    if n < MIN_BUCKET_TRADES:
        return alarms
    if metrics.get("win_rate", 0) > 0.75 or metrics.get("profit_factor", 0) > 3:
        alarms.append(
            f"Suspicious OOS ({scope}): win_rate={metrics.get('win_rate'):.2f} "
            f"PF={metrics.get('profit_factor'):.2f} — check for look-ahead"
        )
    return alarms