"""Test-my-idea — IS/OOS split, lag-safe features, corrected simulation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd

from backtest.config import BacktestConfig
from backtest.costs import net_r_from_gross
from backtest.history_cache import atr14, get_ohlc
from backtest.paths import REPO_ROOT, history_parquet
from backtest.random_baseline import random_baseline_stats
from backtest.split import filter_sample, tag_sample
from core.idea_features import IDEA_FEATURE_NAMES, load_idea_feature_frame

CACHE_DIR = REPO_ROOT / "data" / "idea_cache"
Phase = Literal["IS", "OOS"]


@dataclass
class RuleSpec:
    symbol: str
    timeframe: str
    long_conditions: list[dict[str, Any]] = field(default_factory=list)
    short_conditions: list[dict[str, Any]] = field(default_factory=list)
    sl_atr: float = 1.5
    tp_r: float = 1.0
    max_hold: int = 32
    low_fee: bool = True

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RuleSpec:
        data = dict(d)
        legacy_conds = data.pop("conditions", None)
        legacy_dir = data.pop("direction", None)
        if legacy_conds and legacy_dir:
            if str(legacy_dir).upper() == "SHORT":
                data.setdefault("short_conditions", legacy_conds)
            else:
                data.setdefault("long_conditions", legacy_conds)
        from dataclasses import fields

        allowed = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in allowed})


def rule_hash(spec: RuleSpec) -> str:
    payload = json.dumps(asdict(spec), sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def feature_options() -> tuple[str, ...]:
    return IDEA_FEATURE_NAMES


def _eval_condition(df: pd.DataFrame, cond: dict) -> pd.Series:
    left = cond.get("left", "rsi_14")
    op = cond.get("op", "<")
    right = cond.get("right")
    if left not in df.columns:
        return pd.Series(False, index=df.index)
    a = df[left]
    try:
        b = df[right] if isinstance(right, str) and right in df.columns else float(right)
    except (TypeError, ValueError):
        return pd.Series(False, index=df.index)
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
    if not conditions:
        return pd.Series(False, index=df.index)
    mask = pd.Series(True, index=df.index)
    for c in conditions[:4]:
        mask &= _eval_condition(df, c)
    return mask


def max_drawdown_r(r: pd.Series) -> float:
    """Largest peak-to-trough drop of cumulative R."""
    if r.empty:
        return 0.0
    eq = r.astype(float).cumsum()
    peak = eq.cummax()
    return float((eq - peak).min())


def wilson_ci(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return (0.0, 0.0)
    p = wins / n
    denom = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denom
    margin = z * np.sqrt((p * (1 - p) + z**2 / (4 * n)) / n) / denom
    return (float(max(0.0, centre - margin)), float(min(1.0, centre + margin)))


def bootstrap_ci(values: np.ndarray, *, n_boot: int = 400, seed: int = 42) -> tuple[float, float]:
    if len(values) < 2:
        m = float(values.mean()) if len(values) else 0.0
        return (m, m)
    rng = np.random.default_rng(seed)
    stats = np.array([rng.choice(values, size=len(values), replace=True).mean() for _ in range(n_boot)])
    return (float(np.percentile(stats, 2.5)), float(np.percentile(stats, 97.5)))


def _fee_cfg(base: BacktestConfig, low_fee: bool) -> BacktestConfig:
    if not low_fee:
        return base
    return BacktestConfig(
        fee_model="standard",
        taker_fee=base.low_fee_taker,
        maker_fee=base.low_fee_maker,
        slippage=base.slippage,
        low_fee_taker=base.low_fee_taker,
        low_fee_maker=base.low_fee_maker,
    )


def _exit_bar(
    df: pd.DataFrame,
    entry_i: int,
    direction: str,
    entry: float,
    sl: float,
    tp: float,
    max_hold: int,
) -> tuple[float, str, int]:
    """Gap-aware exit; same-bar SL before TP; returns (exit_price, outcome, exit_bar_index)."""
    last_j = min(entry_i + max_hold, len(df) - 1)
    exit_p = float(df["close"].iloc[last_j])
    outcome = "TIMEOUT"
    exit_j = last_j
    for j in range(entry_i, min(entry_i + max_hold, len(df))):
        o = float(df["open"].iloc[j])
        hi = float(df["high"].iloc[j])
        lo = float(df["low"].iloc[j])
        if direction == "SHORT":
            if o >= sl:
                return o, "SL", j
            if o <= tp:
                return o, "TP", j
            if hi >= sl:
                return sl, "SL", j
            if lo <= tp:
                return tp, "TP", j
        else:
            if o <= sl:
                return o, "SL", j
            if o >= tp:
                return o, "TP", j
            if lo <= sl:
                return sl, "SL", j
            if hi >= tp:
                return tp, "TP", j
        exit_p = float(df["close"].iloc[j])
        exit_j = j
    return exit_p, outcome, exit_j


def _simulate(df: pd.DataFrame, spec: RuleSpec, cfg: BacktestConfig) -> pd.DataFrame:
    long_m = build_mask(df, spec.long_conditions)
    short_m = build_mask(df, spec.short_conditions)
    rows: list[dict] = []
    busy = -1
    for i in range(len(df) - 2):
        if i <= busy:
            continue
        direction = None
        if bool(long_m.iloc[i]) and not bool(short_m.iloc[i]):
            direction = "LONG"
        elif bool(short_m.iloc[i]) and not bool(long_m.iloc[i]):
            direction = "SHORT"
        else:
            continue
        atr = float(df["atr_14"].iloc[i])
        if not np.isfinite(atr) or atr <= 0:
            continue
        entry_i = i + 1
        entry = float(df["open"].iloc[entry_i])
        if direction == "SHORT":
            sl = entry + spec.sl_atr * atr
            tp = entry - spec.tp_r * spec.sl_atr * atr
        else:
            sl = entry - spec.sl_atr * atr
            tp = entry + spec.tp_r * spec.sl_atr * atr
        exit_p, outcome, exit_j = _exit_bar(df, entry_i, direction, entry, sl, tp, spec.max_hold)
        risk = abs(entry - sl)
        g = (entry - exit_p) / risk if direction == "SHORT" else (exit_p - entry) / risk
        net = net_r_from_gross(g, entry, exit_p, risk, direction, "market", cfg)
        rows.append(
            {
                "close_time": int(df["close_time"].iloc[i]),
                "direction": direction,
                "r_net": net,
                "filled": True,
                "outcome": outcome,
                "setup_id": f"idea_{i}",
                "bar_index": i,
            }
        )
        busy = exit_j
    return pd.DataFrame(rows)


def _metrics_block(trades: pd.DataFrame, df: pd.DataFrame, spec: RuleSpec, cfg: BacktestConfig, phase: str) -> dict:
    if trades.empty:
        return {"trades": 0, "sample": phase}
    r = trades["r_net"].astype(float)
    wins = int((r > 0).sum())
    n = len(r)
    wr_lo, wr_hi = wilson_ci(wins, n)
    exp_lo, exp_hi = bootstrap_ci(r.to_numpy())
    months = max(1, len(filter_sample(df, phase)) / max(1, _bars_per_month(spec.timeframe)))
    block = {
        "sample": phase,
        "trades": n,
        "win_rate": float(wins / n),
        "win_rate_ci95": [wr_lo, wr_hi],
        "expectancy_r": float(r.mean()),
        "expectancy_ci95": [exp_lo, exp_hi],
        "profit_factor": float(r[r > 0].sum() / abs(r[r < 0].sum())) if (r < 0).any() else float("inf"),
        "max_dd_r": max_drawdown_r(r),
        "trades_per_month": float(n / months),
    }
    block["random_baseline"] = _random_baseline_pct(trades, df, spec, cfg, phase)
    return block


def _bars_per_month(tf: str) -> float:
    return {"5m": 8640, "15m": 2880, "1h": 720}.get(tf, 720)


def _random_baseline_pct(trades: pd.DataFrame, df: pd.DataFrame, spec: RuleSpec, cfg: BacktestConfig, sample: str) -> dict:
    if trades.empty:
        return {"percentile": None}
    try:
        frame = get_ohlc(spec.symbol, spec.timeframe)
        atr = atr14(frame)
        sigs = []
        for _, row in trades.iterrows():
            bi = int(row["bar_index"])
            entry = float(frame.open[bi + 1]) if bi + 1 < len(frame.open) else float(frame.close[bi])
            d = row["direction"]
            av = float(atr[bi]) if bi < len(atr) and np.isfinite(atr[bi]) else entry * 0.01
            if d == "SHORT":
                sl = entry + spec.sl_atr * av
                tp1 = entry - spec.tp_r * spec.sl_atr * av
            else:
                sl = entry - spec.sl_atr * av
                tp1 = entry + spec.tp_r * spec.sl_atr * av
            sigs.append(
                {
                    "setup_id": row["setup_id"],
                    "bar_index": bi,
                    "close_time": int(row["close_time"]),
                    "direction": d,
                    "entry": entry,
                    "stop_loss": sl,
                    "tp1": tp1,
                    "tp2": tp1,
                    "tp3": tp1,
                }
            )
        signals = pd.DataFrame(sigs)
        tr = trades.copy()
        tr["sample"] = sample
        stats = random_baseline_stats(frame, signals, tr, cfg, "tp1_full", sample=sample, n_mc=25)
        return {"percentile": stats.get("percentile"), "mu": stats.get("mu")}
    except Exception:
        return {"percentile": None}


def _data_mtime(symbol: str, tf: str) -> float:
    p = history_parquet(symbol, tf)
    return p.stat().st_mtime if p.exists() else 0.0


def cache_path(spec: RuleSpec, phase: Phase) -> Path:
    key = f"{rule_hash(spec)}_{phase}_{_data_mtime(spec.symbol, spec.timeframe):.0f}"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{key}.json"


def load_cached(spec: RuleSpec, phase: Phase) -> dict[str, Any] | None:
    p = cache_path(spec, phase)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def save_cached(spec: RuleSpec, phase: Phase, result: dict[str, Any]) -> None:
    cache_path(spec, phase).write_text(json.dumps(result, indent=2), encoding="utf-8")


def run_idea_test(spec: RuleSpec, *, phase: Phase, cfg: BacktestConfig | None = None, use_cache: bool = True) -> dict[str, Any]:
    if use_cache:
        hit = load_cached(spec, phase)
        if hit is not None:
            return hit
    cfg = _fee_cfg(cfg or BacktestConfig(), spec.low_fee)
    df = tag_sample(load_idea_feature_frame(spec.symbol, spec.timeframe), cfg)
    all_trades = _simulate(df, spec, cfg)
    part = filter_sample(df, phase)
    trades = all_trades[all_trades["close_time"].isin(part["close_time"].astype(int))]
    out: dict[str, Any] = {
        "hash": rule_hash(spec),
        "phase": phase,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    out[phase] = _metrics_block(trades, df, spec, cfg, phase)
    if phase == "OOS":
        oos = out["OOS"]
        if oos.get("trades", 0) < 30:
            out["verdict"] = "Too few OOS trades to judge."
        elif oos.get("expectancy_r", 0) > 0:
            out["verdict"] = "OOS net R positive — review manually; not a live signal."
        else:
            out["verdict"] = "No OOS edge after fees."
    save_cached(spec, phase, out)
    return out


def locked_rules_count() -> int:
    p = REPO_ROOT / "data" / "idea_rules.json"
    if not p.exists():
        return 0
    try:
        return len(json.loads(p.read_text(encoding="utf-8")))
    except json.JSONDecodeError:
        return 0