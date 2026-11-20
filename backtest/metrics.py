"""Backtest metrics, honesty checks, baselines."""

from __future__ import annotations

import math
import random
from typing import Any

import numpy as np
import pandas as pd

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


def core_metrics(trades: pd.DataFrame) -> dict[str, Any]:
    filled = trades[trades["filled"]]
    n_sig = len(trades)
    n = len(filled)
    if n == 0:
        return {"trades": 0, "fill_rate": 0.0}
    wins = filled[filled["outcome"].isin(("TP1", "TP2", "TP3", "BE"))]
    wr = len(wins) / n
    wlo, whi = wilson_ci(len(wins), n)
    r_net = filled["r_net"].astype(float)
    expectancy, exp_lo, exp_hi = bootstrap_mean_ci(r_net.tolist())
    gross_w = filled.loc[r_net > 0, "r_net"].sum()
    gross_l = abs(filled.loc[r_net < 0, "r_net"].sum())
    pf = float(gross_w / gross_l) if gross_l > 0 else float("inf")
    eq = r_net.cumsum()
    dd = float((eq - eq.cummax()).min())
    return {
        "signals": n_sig,
        "trades": n,
        "fill_rate": n / n_sig if n_sig else 0.0,
        "win_rate": wr,
        "win_rate_ci": (wlo, whi),
        "expectancy_r": expectancy,
        "expectancy_ci": (exp_lo, exp_hi),
        "profit_factor": pf,
        "total_net_r": float(r_net.sum()),
        "max_dd_r": dd,
        "avg_win_r": float(filled.loc[r_net > 0, "r_net"].mean()) if (r_net > 0).any() else 0.0,
        "avg_loss_r": float(filled.loc[r_net < 0, "r_net"].mean()) if (r_net < 0).any() else 0.0,
    }


def score_calibration(trades: pd.DataFrame) -> pd.DataFrame:
    filled = trades[trades["filled"]].copy()
    if filled.empty:
        return pd.DataFrame()
    filled["bucket"] = pd.cut(
        filled["score"],
        bins=[55, 60, 65, 70, 75, 80, 85, 90, 95, 100],
        right=False,
    )
    rows = []
    for b, grp in filled.groupby("bucket", observed=True):
        n = len(grp)
        wins = (grp["outcome"].isin(("TP1", "TP2", "TP3", "BE"))).sum()
        lo, hi = wilson_ci(int(wins), n)
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


def spearman_score_r(trades: pd.DataFrame) -> float | None:
    filled = trades[trades["filled"]]
    if len(filled) < 10:
        return None
    return float(filled["score"].corr(filled["r_net"], method="spearman"))


def random_baseline_percentile(
    strategy_r: list[float],
    rng: random.Random,
    *,
    n_mc: int = 200,
) -> float:
    if not strategy_r:
        return 0.0
    strat = float(np.mean(strategy_r))
    better = 0
    for _ in range(n_mc):
        sample = [rng.gauss(0, 1) for _ in strategy_r]
        if float(np.mean(sample)) < strat:
            better += 1
    return better / n_mc * 100.0


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


def cost_sensitivity(trades: pd.DataFrame, mult: float) -> dict[str, float]:
    """Approximate: scale net R down proportionally to extra fees."""
    filled = trades[trades["filled"]].copy()
    if filled.empty:
        return {"expectancy_r": 0.0, "profit_factor": 0.0}
    fee_drag = (mult - 1.0) * 0.05
    adj = filled["r_net"] - fee_drag
    return {
        "expectancy_r": float(adj.mean()),
        "profit_factor": core_metrics(filled.assign(r_net=adj))["profit_factor"],
    }


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