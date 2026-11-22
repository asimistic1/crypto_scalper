"""Loss / fee diagnostics (Phase 3.4) — report only, no strategy changes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from backtest.config import BacktestConfig
from backtest.costs import net_r_from_gross, recompute_net_r_row
from backtest.history import ensure_indicators, load_history
from backtest.history_cache import atr14, get_ohlc
from backtest.metrics import core_metrics
from backtest.simulator import (
    Outcome,
    SimSignal,
    _apply_slippage,
    _same_bar_sl_first_long,
    _same_bar_sl_first_short,
    resolve_fill_index,
)
from core.config import MIN_SL_VS_COSTS, SLIPPAGE, TAKER_FEE
from core.models import Direction, EntryType

PK = ZoneInfo("Asia/Karachi")

DIAG_SYMBOL = "BTCUSDT"
DIAG_TFS = ("5m", "15m", "1h")

_d1_regime_cache: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}


def _d1_regime_arrays(sym: str) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    if sym in _d1_regime_cache:
        return _d1_regime_cache[sym]
    try:
        d1 = ensure_indicators(load_history(sym, "1d"))
    except FileNotFoundError:
        return None
    if "ema_200" not in d1.columns or d1.empty:
        return None
    arr = (
        d1["close_time"].to_numpy(dtype=np.int64),
        d1["close"].to_numpy(dtype=np.float64),
        d1["ema_200"].to_numpy(dtype=np.float64),
    )
    _d1_regime_cache[sym] = arr
    return arr


def regime_at_signal(sym: str, signal_close_ms: int) -> str:
    """BTC 1d close vs EMA200 using last *closed* daily bar strictly before signal time."""
    data = _d1_regime_arrays(sym)
    if data is None:
        return "unknown"
    ct, close, ema = data
    i = int(np.searchsorted(ct, int(signal_close_ms), side="left")) - 1
    if i < 0 or np.isnan(ema[i]):
        return "unknown"
    return "above_ema200" if close[i] > ema[i] else "below_ema200"


def _btc_regime_series(sym: str, close_times: np.ndarray) -> list[str]:
    return [regime_at_signal(sym, int(t)) for t in close_times]


def _sig_val(row: pd.Series, *keys: str, default: float = 0.0) -> float:
    for k in keys:
        if k in row.index and pd.notna(row[k]):
            return float(row[k])
    return default


def _field(row: pd.Series, name: str):
    for k in (name, f"{name}_sig", f"{name}_tr"):
        if k in row.index and pd.notna(row[k]):
            return row[k]
    return row.get(name)


def _merge_trades_signals(trades: pd.DataFrame, signals: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "setup_id",
        "bar_index",
        "strategy",
        "direction",
        "entry_type",
        "entry",
        "stop_loss",
        "tp1",
        "tp2",
        "tp3",
        "close_time",
        "score",
    ]
    sig = signals[[c for c in cols if c in signals.columns]].drop_duplicates("setup_id")
    merged = trades.merge(sig, on="setup_id", how="left", suffixes=("_tr", "_sig"))
    if "entry_sig" in merged.columns:
        merged["entry_level"] = merged["entry_sig"].combine_first(merged.get("entry_level", 0))
    if "close_time_sig" in merged.columns:
        merged["signal_close_time"] = merged["close_time_sig"]
    elif "close_time_tr" in merged.columns:
        merged["signal_close_time"] = merged["close_time_tr"]
    else:
        merged["signal_close_time"] = merged.get("close_time", 0)
    return merged


def _row_for_cost(row: pd.Series) -> pd.Series:
    r = row.copy()
    r["stop_loss"] = _sig_val(row, "stop_loss_sig", "stop_loss")
    r["entry_level"] = _sig_val(row, "entry_sig", "entry_level", "entry")
    r["entry"] = r["entry_level"]
    if "entry_type" not in r.index or pd.isna(r.get("entry_type")):
        r["entry_type"] = str(_field(row, "entry_type"))
    return r


def _fee_floor_risk(entry: float) -> float:
    costs = entry * (TAKER_FEE * 2 + SLIPPAGE * 2)
    return MIN_SL_VS_COSTS * costs


def _walk_path_r(
    df: pd.DataFrame,
    signal: SimSignal,
    cfg: BacktestConfig,
    timeframe: str,
    *,
    tp_r: float | None = None,
    sl_mult: float = 1.0,
    max_hold: int | None = None,
) -> tuple[float, float, bool, int | None, float, float]:
    """Return (gross_r, mfe_peak, tp_hit, bars_held, fill_price, exit_price)."""
    fill = resolve_fill_index(df, signal, cfg)
    if fill is None:
        return 0.0, 0.0, False, None, 0.0, 0.0
    fill_idx, fill_price = fill
    risk = abs(signal.entry - signal.stop_loss)
    if risk <= 0:
        return 0.0, 0.0, False, fill_idx, fill_price, fill_price
    sl = signal.stop_loss
    if sl_mult != 1.0:
        dist = abs(signal.entry - sl) * sl_mult
        if signal.direction == Direction.LONG:
            sl = signal.entry - dist
        else:
            sl = signal.entry + dist
    tp = signal.tp1
    if tp_r is not None:
        if signal.direction == Direction.LONG:
            tp = signal.entry + tp_r * risk
        else:
            tp = signal.entry - tp_r * risk
    hold = max_hold or cfg.max_hold_bars.get(timeframe, 32)
    mfe = 0.0
    mae = 0.0
    reached_tp = 0.0
    for k in range(fill_idx, min(len(df), fill_idx + hold + 1)):
        bar = df.iloc[k]
        h, l = float(bar["high"]), float(bar["low"])
        if signal.direction == Direction.LONG:
            mfe = max(mfe, (h - fill_price) / risk)
            mae = min(mae, (l - fill_price) / risk)
            if float(bar["open"]) < sl:
                ex = _apply_slippage(float(bar["open"]), signal.direction, "exit", cfg.slippage)
                return (ex - fill_price) / risk, mfe, False, k - fill_idx, fill_price, ex
            same = _same_bar_sl_first_long(bar, sl, tp)
            if same == Outcome.SL.value:
                ex = _apply_slippage(sl, signal.direction, "exit", cfg.slippage)
                return (ex - fill_price) / risk, mfe, False, k - fill_idx, fill_price, ex
            if same == Outcome.TP1.value:
                reached_tp = max(reached_tp, (tp - fill_price) / risk)
                ex = _apply_slippage(tp, signal.direction, "exit", cfg.slippage)
                return (ex - fill_price) / risk, mfe, True, k - fill_idx, fill_price, ex
        else:
            mfe = max(mfe, (fill_price - l) / risk)
            mae = min(mae, (fill_price - h) / risk)
            if float(bar["open"]) > sl:
                ex = _apply_slippage(float(bar["open"]), signal.direction, "exit", cfg.slippage)
                return (fill_price - ex) / risk, mfe, False, k - fill_idx, fill_price, ex
            same = _same_bar_sl_first_short(bar, sl, tp)
            if same == Outcome.SL.value:
                ex = _apply_slippage(sl, signal.direction, "exit", cfg.slippage)
                return (fill_price - ex) / risk, mfe, False, k - fill_idx, fill_price, ex
            if same == Outcome.TP1.value:
                reached_tp = max(reached_tp, (fill_price - tp) / risk)
                ex = _apply_slippage(tp, signal.direction, "exit", cfg.slippage)
                return (fill_price - ex) / risk, mfe, True, k - fill_idx, fill_price, ex
    last = df.iloc[min(len(df) - 1, fill_idx + hold)]
    exit_p = _apply_slippage(float(last["close"]), signal.direction, "exit", cfg.slippage)
    if signal.direction == Direction.LONG:
        gross = (exit_p - fill_price) / risk
    else:
        gross = (fill_price - exit_p) / risk
    return gross, mfe, False, min(len(df) - 1, fill_idx + hold) - fill_idx, fill_price, exit_p


def _breakdown_table(filled: pd.DataFrame, group_col: str) -> pd.DataFrame:
    rows = []
    for key, grp in filled.groupby(group_col, dropna=False):
        if len(grp) < 3:
            continue
        m = core_metrics(grp, raw_signals=len(grp))
        rows.append(
            {
                group_col: key,
                "trades": len(grp),
                "win_rate": m["win_rate"],
                "gross_e_r": float(grp["r_gross"].astype(float).mean()),
                "net_e_r": float(grp["r_net"].astype(float).mean()),
            }
        )
    return pd.DataFrame(rows).sort_values("trades", ascending=False) if rows else pd.DataFrame()


def _gross_vs_net(filled: pd.DataFrame) -> dict[str, float]:
    gross = filled["r_gross"].astype(float)
    net = filled["r_net"].astype(float)
    cost_r = gross - net
    return {
        "expectancy_gross_r": float(gross.mean()),
        "expectancy_net_r": float(net.mean()),
        "avg_cost_r_per_trade": float(cost_r.mean()),
        "median_cost_r": float(cost_r.median()),
    }


def _sl_diagnostics(filled: pd.DataFrame, frame) -> dict[str, Any]:
    atr = atr14(frame)
    sl_pct: list[float] = []
    sl_atr: list[float] = []
    widened = 0
    cost_buckets = {"<10%": 0, "10-20%": 0, "20-33%": 0, ">33%": 0}
    n = 0
    for _, row in filled.iterrows():
        entry = float(row.get("entry_sig", row.get("entry_level", 0)))
        sl = _sig_val(row, "stop_loss_sig", "stop_loss")
        if entry <= 0:
            continue
        risk = abs(entry - sl)
        sl_pct.append(100.0 * risk / entry)
        bi = int(row.get("bar_index", 0))
        a = float(atr[bi]) if bi < len(atr) and not np.isnan(atr[bi]) else risk
        sl_atr.append(risk / a if a else 0.0)
        if risk <= _fee_floor_risk(entry) * 1.02:
            widened += 1
        g = float(row["r_gross"])
        c = g - float(row["r_net"])
        if abs(g) > 1e-9:
            share = 100.0 * abs(c) / abs(g)
        else:
            share = 100.0
        if share < 10:
            cost_buckets["<10%"] += 1
        elif share < 20:
            cost_buckets["10-20%"] += 1
        elif share < 33:
            cost_buckets["20-33%"] += 1
        else:
            cost_buckets[">33%"] += 1
        n += 1
    return {
        "sl_pct_median": float(np.median(sl_pct)) if sl_pct else 0.0,
        "sl_atr_median": float(np.median(sl_atr)) if sl_atr else 0.0,
        "sl_widened_fee_floor_share": widened / n if n else 0.0,
        "cost_as_pct_of_gross_r_buckets": cost_buckets,
    }


def _mfe_mae_block(filled: pd.DataFrame, frame, cfg: BacktestConfig) -> dict[str, Any]:
    reach_05 = reach_1 = reach_15 = 0
    losers_mfe: list[float] = []
    fast_sl = 0
    sl_trades = 0
    n = 0
    df = frame.df
    for _, row in filled.iterrows():
        sim = SimSignal(
            direction=Direction(str(_field(row, "direction"))),
            entry_type=EntryType(str(_field(row, "entry_type"))),
            entry=_sig_val(row, "entry_sig", "entry_level", "entry"),
            stop_loss=_sig_val(row, "stop_loss_sig", "stop_loss"),
            tp1=_sig_val(row, "tp1_sig", "tp1"),
            tp2=_sig_val(row, "tp2_sig", "tp2", "tp1_sig", "tp1"),
            tp3=_sig_val(row, "tp3_sig", "tp3", "tp2_sig", "tp2"),
            signal_bar=int(row.get("bar_index", 0)),
        )
        _, mfe, _, _, _, _ = _walk_path_r(df, sim, cfg, frame.timeframe)
        n += 1
        if mfe >= 0.5:
            reach_05 += 1
        if mfe >= 1.0:
            reach_1 += 1
        if mfe >= 1.5:
            reach_15 += 1
        if not row.get("tp1_before_sl") and float(row["r_net"]) < 0:
            losers_mfe.append(mfe)
        if str(row.get("outcome")) == "SL":
            sl_trades += 1
            if int(row.get("bars_held", 99)) <= 2:
                fast_sl += 1
    return {
        "pct_reach_0p5r_before_exit": reach_05 / n if n else 0.0,
        "pct_reach_1r_before_exit": reach_1 / n if n else 0.0,
        "pct_reach_1p5r_before_exit": reach_15 / n if n else 0.0,
        "median_mfe_losing_trades_r": float(np.median(losers_mfe)) if losers_mfe else 0.0,
        "pct_sl_within_2_bars_after_fill": fast_sl / sl_trades if sl_trades else 0.0,
    }


def _whatif_grid(filled: pd.DataFrame, frame, cfg: BacktestConfig, sample: str) -> pd.DataFrame:
    rows: list[dict] = []
    df = frame.df
    for tp_r in (1.0, 1.5, 2.0):
        for sl_m in (1.0, 1.5, 2.0):
            for hold in (8, 16, 32):
                path_rows: list[tuple[float, float, float, float]] = []
                for _, row in filled.iterrows():
                    sim = SimSignal(
                        direction=Direction(str(_field(row, "direction"))),
                        entry_type=EntryType(str(_field(row, "entry_type"))),
                        entry=_sig_val(row, "entry_sig", "entry_level", "entry"),
                        stop_loss=_sig_val(row, "stop_loss_sig", "stop_loss"),
                        tp1=_sig_val(row, "tp1_sig", "tp1"),
                        tp2=_sig_val(row, "tp2_sig", "tp2"),
                        tp3=_sig_val(row, "tp3_sig", "tp3"),
                        signal_bar=int(row["bar_index"]),
                    )
                    base_risk = abs(sim.entry - sim.stop_loss)
                    scenario_risk = base_risk * sl_m if base_risk > 0 else 0.0
                    g, _, _, _, fill_px, exit_px = _walk_path_r(
                        df, sim, cfg, frame.timeframe, tp_r=tp_r, sl_mult=sl_m, max_hold=hold
                    )
                    path_rows.append((g, scenario_risk, fill_px, exit_px))
                if not path_rows:
                    continue
                gross_list = [t[0] for t in path_rows]
                gr = pd.Series(gross_list)
                net_vals: list[float] = []
                for j, (_, row) in enumerate(filled.iterrows()):
                    g, scenario_risk, fill_px, exit_px = path_rows[j]
                    sim_entry = _sig_val(row, "entry_sig", "entry_level", "entry")
                    entry_px = fill_px or float(row.get("entry_price", sim_entry))
                    exit_px = exit_px or entry_px
                    net_vals.append(
                        net_r_from_gross(
                            g,
                            entry_px,
                            exit_px,
                            scenario_risk,
                            str(_field(row, "direction")),
                            str(_field(row, "entry_type")),
                            cfg,
                        )
                    )
                rows.append(
                    {
                        "sample": sample,
                        "tp_r": tp_r,
                        "sl_mult": sl_m,
                        "max_hold": hold,
                        "expectancy_gross_r": float(gr.mean()),
                        "expectancy_net_r": float(np.mean(net_vals)),
                        "note": "IS: for exploration only" if sample == "IS" else "OOS: do not tune on OOS",
                    }
                )
    return pd.DataFrame(rows)


def _fee_scenarios(filled: pd.DataFrame, cfg: BacktestConfig) -> pd.DataFrame:
    scenarios = [
        ("conservative_taker_both", BacktestConfig(fee_model="conservative")),
        (
            "maker_entry_maker_tp",
            BacktestConfig(fee_model="standard", taker_fee=cfg.taker_fee, maker_fee=cfg.maker_fee),
        ),
        (
            "low_fee_exchange",
            BacktestConfig(
                fee_model="standard",
                taker_fee=cfg.low_fee_taker,
                maker_fee=cfg.low_fee_maker,
            ),
        ),
    ]
    rows = []
    for name, scfg in scenarios:
        nets = filled.apply(lambda r, c=scfg: recompute_net_r_row(_row_for_cost(r), c, 1.0), axis=1)
        gross = filled["r_gross"].astype(float)
        rows.append(
            {
                "scenario": name,
                "expectancy_gross_r": float(gross.mean()),
                "expectancy_net_r": float(nets.mean()),
            }
        )
    return pd.DataFrame(rows)


def _diagnose_timeframe(
    tf: str,
    signals: pd.DataFrame,
    trades: pd.DataFrame,
    cfg: BacktestConfig,
    exit_model: str,
) -> tuple[dict[str, Any], list[str]]:
    frame = get_ohlc(DIAG_SYMBOL, tf)
    sub = trades[
        (trades["symbol"] == DIAG_SYMBOL)
        & (trades["timeframe"] == tf)
        & (trades["exit_model"] == exit_model)
        & trades["filled"]
        & (trades.get("skip_reason", "") != "position_busy")
    ]
    sig = signals[(signals["symbol"] == DIAG_SYMBOL) & (signals["timeframe"] == tf)]
    merged = _merge_trades_signals(sub, sig)
    lines: list[str] = [f"\n### BTCUSDT {tf}"]
    payload: dict[str, Any] = {}
    ct_col = "signal_close_time"

    for sample in ("IS", "OOS"):
        blk = merged[merged["sample"] == sample] if "sample" in merged.columns else merged
        if blk.empty:
            continue
        prefix = f"{tf}_{sample}"
        lines.append(f"\n--- {sample} ---")
        gv = _gross_vs_net(blk)
        lines.append(f"Gross vs net: {gv}")
        payload[f"{prefix}_gross_vs_net"] = gv

        sl = _sl_diagnostics(blk, frame)
        lines.append(f"SL / cost buckets: {sl}")
        payload[f"{prefix}_sl"] = sl

        mfe = _mfe_mae_block(blk, frame, cfg)
        lines.append(f"MFE/MAE: {mfe}")
        payload[f"{prefix}_mfe_mae"] = mfe

        blk = blk.copy()
        blk["hour_pkt"] = [
            pd.to_datetime(int(t), unit="ms", utc=True).astimezone(PK).hour for t in blk[ct_col]
        ]
        blk["weekday"] = [
            pd.to_datetime(int(t), unit="ms", utc=True).astimezone(PK).weekday() for t in blk[ct_col]
        ]
        for base in ("strategy", "direction", "entry_type", "score"):
            if base not in blk.columns:
                for suffix in ("_sig", "_tr"):
                    c = f"{base}{suffix}"
                    if c in blk.columns:
                        blk[base] = blk[c]
                        break
        blk["score_bucket"] = pd.cut(blk["score"], bins=[55, 65, 75, 85, 100], right=False)
        ind = ensure_indicators(frame.df)
        bi = blk["bar_index"].astype(int).clip(0, len(ind) - 1)
        blk["atr_pct"] = [100 * float(ind.iloc[i].get("atr_14", 0)) / float(ind.iloc[i]["close"]) for i in bi]
        blk["atr_quintile"] = pd.qcut(blk["atr_pct"].rank(method="first"), 5, duplicates="drop")
        blk["btc_regime"] = _btc_regime_series(DIAG_SYMBOL, blk[ct_col].to_numpy(dtype=np.int64))
        n_unk = int((blk["btc_regime"] == "unknown").sum())
        lines.append(f"btc_regime unknown: {n_unk}/{len(blk)} ({100*n_unk/len(blk):.1f}%)")
        for col in (
            "strategy",
            "direction",
            "entry_type",
            "btc_regime",
            "hour_pkt",
            "weekday",
            "atr_quintile",
            "score_bucket",
        ):
            tbl = _breakdown_table(blk, col)
            if not tbl.empty:
                lines.append(f"\nBreakdown by {col} ({sample}):")
                lines.append(tbl.head(20).to_string(index=False))
                payload[f"{prefix}_breakdown_{col}"] = tbl.to_dict(orient="records")

        wif = _whatif_grid(blk, frame, cfg, sample)
        if not wif.empty:
            lines.append(f"\nWhat-if exits ({sample}):")
            lines.append(wif.to_string(index=False))
            payload[f"{prefix}_whatif"] = wif.to_dict(orient="records")

        fees = _fee_scenarios(blk, cfg)
        lines.append(f"\nFee scenarios ({sample}):")
        lines.append(fees.to_string(index=False))
        payload[f"{prefix}_fees"] = fees.to_dict(orient="records")
    return payload, lines


def run_diagnostics(
    run_dir: Path,
    signals: pd.DataFrame,
    trades: pd.DataFrame,
    cfg: BacktestConfig,
    symbols: list[str],
    timeframes: list[str],
) -> str:
    if DIAG_SYMBOL not in symbols:
        return ""
    _d1_regime_cache.clear()
    exit_model = cfg.exit_models[0]
    payload: dict[str, Any] = {}
    lines: list[str] = ["\n=== Diagnostics (BTCUSDT) ==="]
    for tf in DIAG_TFS:
        if tf not in timeframes:
            continue
        part, part_lines = _diagnose_timeframe(tf, signals, trades, cfg, exit_model)
        payload.update(part)
        lines.extend(part_lines)

    (run_dir / "diagnostics.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    text = "\n".join(lines)
    print(text, flush=True)
    return text