"""Test-my-idea — compile rules and reuse backtest cost/split patterns."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import pandas as pd

from backtest.config import BacktestConfig
from backtest.costs import net_r_from_gross
from backtest.history import ensure_indicators, load_history
from backtest.split import filter_sample, tag_sample


@dataclass
class RuleSpec:
    symbol: str
    timeframe: str
    direction: str
    conditions: list[dict[str, Any]]
    sl_atr: float
    tp_r: float
    max_hold: int
    low_fee: bool


def rule_hash(spec: RuleSpec) -> str:
    payload = json.dumps(spec.__dict__, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _eval_condition(df: pd.DataFrame, cond: dict) -> pd.Series:
    left = cond.get("left", "rsi_14")
    op = cond.get("op", "<")
    right = cond.get("right")
    if left not in df.columns:
        return pd.Series(False, index=df.index)
    a = df[left]
    b = df[right] if isinstance(right, str) and right in df.columns else float(right)
    if op == "<":
        return a < b
    if op == ">":
        return a > b
    if op == "<=":
        return a <= b
    if op == ">=":
        return a >= b
    return a == b


def build_mask(df: pd.DataFrame, conditions: list[dict]) -> pd.Series:
    mask = pd.Series(True, index=df.index)
    for c in conditions[:4]:
        mask &= _eval_condition(df, c)
    return mask


def _simulate(df: pd.DataFrame, spec: RuleSpec, cfg: BacktestConfig) -> pd.DataFrame:
    mask = build_mask(df, spec.conditions)
    rows: list[dict] = []
    busy = -1
    for i in range(len(df) - 1):
        if i <= busy or not bool(mask.iloc[i]):
            continue
        atr = float(df["atr_14"].iloc[i])
        entry = float(df["open"].iloc[i + 1])
        if spec.direction == "SHORT":
            sl = entry + spec.sl_atr * atr
            tp = entry - spec.tp_r * spec.sl_atr * atr
        else:
            sl = entry - spec.sl_atr * atr
            tp = entry + spec.tp_r * spec.sl_atr * atr
        outcome = "TIMEOUT"
        exit_p = float(df["close"].iloc[min(i + spec.max_hold, len(df) - 1)])
        for j in range(i + 1, min(i + 1 + spec.max_hold, len(df))):
            hi = float(df["high"].iloc[j])
            lo = float(df["low"].iloc[j])
            if spec.direction == "SHORT":
                if hi >= sl:
                    exit_p, outcome = sl, "SL"
                    break
                if lo <= tp:
                    exit_p, outcome = tp, "TP"
                    break
            else:
                if lo <= sl:
                    exit_p, outcome = sl, "SL"
                    break
                if hi >= tp:
                    exit_p, outcome = tp, "TP"
                    break
            exit_p = float(df["close"].iloc[j])
        risk = abs(entry - sl)
        if spec.direction == "SHORT":
            g = (entry - exit_p) / risk if risk else 0.0
        else:
            g = (exit_p - entry) / risk if risk else 0.0
        net = net_r_from_gross(g, entry, exit_p, risk, spec.direction, "market", cfg)
        rows.append(
            {
                "close_time": int(df["close_time"].iloc[i]),
                "r_net": net,
                "filled": True,
                "outcome": outcome,
            }
        )
        busy = i + spec.max_hold
    return pd.DataFrame(rows)


def run_idea_test(spec: RuleSpec, cfg: BacktestConfig | None = None) -> dict[str, Any]:
    cfg = cfg or BacktestConfig()
    if spec.low_fee:
        cfg = BacktestConfig(
            fee_model="standard",
            taker_fee=cfg.low_fee_taker,
            maker_fee=cfg.low_fee_maker,
            slippage=cfg.slippage,
        )
    df = ensure_indicators(load_history(spec.symbol.upper(), spec.timeframe))
    df = tag_sample(df, cfg)
    trades = _simulate(df, spec, cfg)
    out: dict[str, Any] = {"hash": rule_hash(spec), "trades": len(trades)}
    for label in ("IS", "OOS"):
        part = filter_sample(df, label)
        sub = trades[trades["close_time"].isin(part["close_time"])]
        if sub.empty:
            out[label] = {"trades": 0}
            continue
        r = sub["r_net"].astype(float)
        out[label] = {
            "trades": len(sub),
            "win_rate": float((r > 0).mean()),
            "expectancy_r": float(r.mean()),
            "profit_factor": float(r[r > 0].sum() / abs(r[r < 0].sum())) if (r < 0).any() else float("inf"),
            "max_dd_r": float(r.cumsum().min()),
        }
    oos = out.get("OOS", {})
    if oos.get("trades", 0) < 30:
        out["verdict"] = "Too few OOS trades to judge — relax conditions or extend history."
    elif oos.get("expectancy_r", 0) > 0:
        out["verdict"] = "OOS net R positive — review manually; still not a live signal."
    else:
        out["verdict"] = "No OOS edge after fees."
    return out