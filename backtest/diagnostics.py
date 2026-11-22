"""Loss / fee diagnostics (Phase 3.4) — report only, no strategy changes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from backtest.config import BacktestConfig
from backtest.costs import recompute_net_r_row
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
DIAG_TF = "15m"


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
        "close_time",
        "score",
    ]
    sig = signals[cols].drop_duplicates("setup_id")
    return trades.merge(sig, on="setup_id", how="left", suffixes=("", "_sig"))


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
) -> tuple[float, float, bool, int | None]:
    """Return (gross_r, reached_tp before sl, sl_hit, bars_held)."""
    fill = resolve_fill_index(df, signal, cfg)
    if fill is None:
        return 0.0, 0.0, False, None
    fill_idx, fill_price = fill
    risk = abs(signal.entry - signal.stop_loss)
    if risk <= 0:
        return 0.0, 0.0, False, fill_idx
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
                return (float(bar["open"]) - fill_price) / risk, mfe, False, k - fill_idx
            same = _same_bar_sl_first_long(bar, sl, tp)
            if same == Outcome.SL.value:
                return (sl - fill_price) / risk, mfe, False, k - fill_idx
            if same == Outcome.TP1.value:
                reached_tp = max(reached_tp, (tp - fill_price) / risk)
                return (tp - fill_price) / risk, mfe, True, k - fill_idx
        else:
            mfe = max(mfe, (fill_price - l) / risk)
            mae = min(mae, (fill_price - h) / risk)
            if float(bar["open"]) > sl:
                return (fill_price - float(bar["open"])) / risk, mfe, False, k - fill_idx
            same = _same_bar_sl_first_short(bar, sl, tp)
            if same == Outcome.SL.value:
                return (fill_price - sl) / risk, mfe, False, k - fill_idx
            if same == Outcome.TP1.value:
                reached_tp = max(reached_tp, (fill_price - tp) / risk)
                return (fill_price - tp) / risk, mfe, True, k - fill_idx
    last = df.iloc[min(len(df) - 1, fill_idx + hold)]
    exit_p = _apply_slippage(float(last["close"]), signal.direction, "exit", cfg.slippage)
    if signal.direction == Direction.LONG:
        gross = (exit_p - fill_price) / risk
    else:
        gross = (fill_price - exit_p) / risk
    return gross, mfe, False, min(len(df) - 1, fill_idx + hold) - fill_idx


def _btc_regime_series(sym: str, close_times: np.ndarray) -> list[str]:
    path = Path(f"data/history/{sym}/1d.parquet")
    if not path.exists():
        return ["unknown"] * len(close_times)
    d1 = ensure_indicators(load_history(sym, "1d"))
    if "ema_200" not in d1.columns:
        return ["unknown"] * len(close_times)
    ct = d1["close_time"].to_numpy(dtype=np.int64)
    close = d1["close"].to_numpy(dtype=np.float64)
    ema = d1["ema_200"].to_numpy(dtype=np.float64)
    out: list[str] = []
    for t in close_times:
        i = int(np.searchsorted(ct, int(t), side="right")) - 1
        if i < 0 or np.isnan(ema[i]):
            out.append("unknown")
        else:
            out.append("above_ema200" if close[i] > ema[i] else "below_ema200")
    return out


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
        sl = float(row["stop_loss"])
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
            direction=Direction(str(row["direction"])),
            entry_type=EntryType(str(row["entry_type"])),
            entry=float(row.get("entry_sig", row["entry_level"])),
            stop_loss=float(row["stop_loss"]),
            tp1=float(row.get("tp1", row["entry_level"])),
            tp2=float(row.get("tp2", row["entry_level"])),
            tp3=float(row.get("tp3", row["entry_level"])),
            signal_bar=int(row.get("bar_index", 0)),
        )
        _, mfe, _, _ = _walk_path_r(df, sim, cfg, frame.timeframe)
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
                gross_list: list[float] = []
                for _, row in filled.iterrows():
                    sim = SimSignal(
                        direction=Direction(str(row["direction"])),
                        entry_type=EntryType(str(row["entry_type"])),
                        entry=float(row.get("entry_sig", row["entry_level"])),
                        stop_loss=float(row["stop_loss"]),
                        tp1=float(row["tp1"]),
                        tp2=float(row["tp2"]),
                        tp3=float(row["tp3"]),
                        signal_bar=int(row["bar_index"]),
                    )
                    g, _, _, _ = _walk_path_r(
                        df, sim, cfg, frame.timeframe, tp_r=tp_r, sl_mult=sl_m, max_hold=hold
                    )
                    gross_list.append(g)
                if not gross_list:
                    continue
                gr = pd.Series(gross_list)
                net_vals: list[float] = []
                for j, (_, row) in enumerate(filled.iterrows()):
                    r = row.copy()
                    r["r_gross"] = gross_list[j]
                    r["entry_level"] = float(row.get("entry_sig", row.get("entry_level", 0)))
                    r["entry_price"] = float(row.get("entry_price", r["entry_level"]))
                    r["exit_price"] = float(row.get("exit_price", r["entry_level"]))
                    r["filled"] = True
                    net_vals.append(recompute_net_r_row(r, cfg, 1.0))
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
        nets = filled.apply(lambda r, c=scfg: recompute_net_r_row(r, c, 1.0), axis=1)
        gross = filled["r_gross"].astype(float)
        rows.append(
            {
                "scenario": name,
                "expectancy_gross_r": float(gross.mean()),
                "expectancy_net_r": float(nets.mean()),
            }
        )
    return pd.DataFrame(rows)


def run_diagnostics(
    run_dir: Path,
    signals: pd.DataFrame,
    trades: pd.DataFrame,
    cfg: BacktestConfig,
    symbols: list[str],
    timeframes: list[str],
) -> str:
    if DIAG_SYMBOL not in symbols or DIAG_TF not in timeframes:
        return ""
    frame = get_ohlc(DIAG_SYMBOL, DIAG_TF)
    exit_model = cfg.exit_models[0]
    sub = trades[
        (trades["symbol"] == DIAG_SYMBOL)
        & (trades["timeframe"] == DIAG_TF)
        & (trades["exit_model"] == exit_model)
        & trades["filled"]
        & (trades.get("skip_reason", "") != "position_busy")
    ]
    sig = signals[(signals["symbol"] == DIAG_SYMBOL) & (signals["timeframe"] == DIAG_TF)]
    merged = _merge_trades_signals(sub, sig)
    lines: list[str] = ["\n=== Diagnostics (BTCUSDT 15m) ==="]
    payload: dict[str, Any] = {}

    for sample in ("IS", "OOS"):
        blk = merged[merged["sample"] == sample] if "sample" in merged.columns else merged
        if blk.empty:
            continue
        lines.append(f"\n--- {sample} ---")
        gv = _gross_vs_net(blk)
        lines.append(f"Gross vs net: {gv}")
        payload[f"{sample}_gross_vs_net"] = gv

        sl = _sl_diagnostics(blk, frame)
        lines.append(f"SL / cost buckets: {sl}")
        payload[f"{sample}_sl"] = sl

        mfe = _mfe_mae_block(blk, frame, cfg)
        lines.append(f"MFE/MAE: {mfe}")
        payload[f"{sample}_mfe_mae"] = mfe

        blk = blk.copy()
        blk["hour_pkt"] = [
            pd.to_datetime(int(t), unit="ms", utc=True).astimezone(PK).hour for t in blk["close_time"]
        ]
        blk["weekday"] = [
            pd.to_datetime(int(t), unit="ms", utc=True).astimezone(PK).weekday() for t in blk["close_time"]
        ]
        blk["score_bucket"] = pd.cut(blk["score"], bins=[55, 65, 75, 85, 100], right=False)
        ind = ensure_indicators(frame.df)
        bi = blk["bar_index"].astype(int).clip(0, len(ind) - 1)
        blk["atr_pct"] = [100 * float(ind.iloc[i].get("atr_14", 0)) / float(ind.iloc[i]["close"]) for i in bi]
        blk["atr_quintile"] = pd.qcut(blk["atr_pct"].rank(method="first"), 5, duplicates="drop")
        blk["btc_regime"] = _btc_regime_series(DIAG_SYMBOL, blk["close_time"].to_numpy())
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
                payload[f"{sample}_breakdown_{col}"] = tbl.to_dict(orient="records")

        wif = _whatif_grid(blk, frame, cfg, sample)
        if not wif.empty:
            lines.append(f"\nWhat-if exits ({sample}):")
            lines.append(wif.to_string(index=False))
            payload[f"{sample}_whatif"] = wif.to_dict(orient="records")

        fees = _fee_scenarios(blk, cfg)
        lines.append(f"\nFee scenarios ({sample}):")
        lines.append(fees.to_string(index=False))
        payload[f"{sample}_fees"] = fees.to_dict(orient="records")

    (run_dir / "diagnostics.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    text = "\n".join(lines)
    print(text, flush=True)
    return text