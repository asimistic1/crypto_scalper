"""Simple frozen-quintile rule backtest (hold N bars, catastrophic SL only)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from backtest.config import BacktestConfig
from backtest.costs import net_r_from_gross
from backtest.history import ensure_indicators, load_history
from core.models import Direction

SL_ATR_MULT = 1.5


@dataclass(frozen=True)
class QuintileThresholds:
    q20: float
    q40: float
    q60: float
    q80: float

    def bucket(self, value: float) -> int | None:
        if not np.isfinite(value):
            return None
        if value <= self.q20:
            return 1
        if value <= self.q40:
            return 2
        if value <= self.q60:
            return 3
        if value <= self.q80:
            return 4
        return 5


def thresholds_from_is(series: pd.Series) -> QuintileThresholds | None:
    s = series.dropna()
    if len(s) < 50:
        return None
    q = s.quantile([0.2, 0.4, 0.6, 0.8])
    return QuintileThresholds(float(q[0.2]), float(q[0.4]), float(q[0.6]), float(q[0.8]))


def _fee_cfg(low_fee: bool, base: BacktestConfig) -> BacktestConfig:
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


def run_rule_backtest(
    df: pd.DataFrame,
    feature: str,
    horizon: int,
    symbol: str,
    *,
    thresholds: QuintileThresholds,
    ic_mean: float,
    cfg: BacktestConfig,
    low_fee: bool = True,
) -> pd.DataFrame:
    """Long/short extreme quintiles; IS thresholds; direction from IC sign."""
    if feature not in df.columns or horizon <= 0:
        return pd.DataFrame()
    ind = ensure_indicators(load_history(symbol, "1h"))
    atr = ind["atr_14"].to_numpy(dtype=float)
    ct = ind["close_time"].to_numpy(dtype=np.int64)
    o = ind["open"].to_numpy(dtype=float)
    h = ind["high"].to_numpy(dtype=float)
    low = ind["low"].to_numpy(dtype=float)
    c = ind["close"].to_numpy(dtype=float)
    fee_cfg = _fee_cfg(low_fee, cfg)
    pos_is_long_top = ic_mean >= 0
    rows: list[dict] = []
    busy_until = -1
    for i in range(len(df)):
        if i <= busy_until:
            continue
        feat_val = float(df[feature].iloc[i])
        bucket = thresholds.bucket(feat_val)
        if bucket is None:
            continue
        go_long = (bucket == 5 and pos_is_long_top) or (bucket == 1 and not pos_is_long_top)
        go_short = (bucket == 1 and pos_is_long_top) or (bucket == 5 and not pos_is_long_top)
        if not go_long and not go_short:
            continue
        sig_ct = int(df["close_time"].iloc[i])
        bar_i = int(np.searchsorted(ct, sig_ct, side="right")) - 1
        if bar_i < 0 or bar_i + 1 >= len(ind):
            continue
        entry_i = bar_i + 1
        if entry_i + horizon >= len(ind):
            continue
        entry = float(o[entry_i])
        atrv = float(atr[bar_i])
        if atrv <= 0 or entry <= 0:
            continue
        stop_dist = SL_ATR_MULT * atrv
        direction = Direction.LONG if go_long else Direction.SHORT
        sl = entry - stop_dist if go_long else entry + stop_dist
        exit_i = min(entry_i + horizon, len(ind) - 1)
        exit_raw = float(c[exit_i])
        hit_sl = False
        for k in range(entry_i + 1, exit_i + 1):
            if go_long:
                if float(low[k]) <= sl:
                    exit_raw = sl
                    exit_i = k
                    hit_sl = True
                    break
            elif float(h[k]) >= sl:
                exit_raw = sl
                exit_i = k
                hit_sl = True
                break
        risk = stop_dist
        if go_long:
            gross_r = (exit_raw - entry) / risk
        else:
            gross_r = (entry - exit_raw) / risk
        gross_pct = gross_r * (risk / entry) * 100.0
        net_r = net_r_from_gross(gross_r, entry, exit_raw, risk, direction.value, "MARKET", fee_cfg)
        net_pct = net_r * (risk / entry) * 100.0
        win = (exit_raw > entry and go_long) or (exit_raw < entry and go_short)
        after_cost = net_pct > 0
        rows.append(
            {
                "symbol": symbol,
                "feature": feature,
                "horizon": horizon,
                "entry_time": int(ct[entry_i]),
                "exit_time": int(ct[exit_i]),
                "direction": direction.value,
                "entry_price": entry,
                "exit_price": exit_raw,
                "gross_pct": gross_pct,
                "net_pct": net_pct,
                "r_gross": gross_r,
                "r_net": net_r,
                "filled": True,
                "hit_sl": hit_sl,
                "win_price": win,
                "win_after_cost": after_cost,
                "close_time": sig_ct,
            }
        )
        busy_until = exit_i
    return pd.DataFrame(rows)


def rule_summary(trades: pd.DataFrame) -> dict[str, float]:
    if trades.empty:
        return {"trades": 0}
    t = trades
    wins = float(t["win_after_cost"].mean())
    gross_e = float(t["gross_pct"].mean())
    net_e = float(t["net_pct"].mean())
    gw = t.loc[t["net_pct"] > 0, "net_pct"].sum()
    gl = abs(t.loc[t["net_pct"] < 0, "net_pct"].sum())
    pf = float(gw / gl) if gl > 0 else float("inf")
    eq = t["net_pct"].cumsum()
    dd = float((eq - eq.cummax()).min()) if len(eq) else 0.0
    span_ms = max(1, int(t["exit_time"].max() - t["entry_time"].min()))
    months = span_ms / (30.0 * 86_400_000)
    tpm = len(t) / months if months > 0 else 0.0
    return {
        "trades": len(t),
        "win_rate": wins,
        "gross_e_pct": gross_e,
        "net_e_pct": net_e,
        "profit_factor": pf,
        "max_dd_pct": dd,
        "trades_per_month": tpm,
    }