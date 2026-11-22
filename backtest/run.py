"""
Backtest runner CLI.

python -m backtest.run --symbols BTCUSDT --tfs 15m --months 24
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from backtest.config import BacktestConfig
from backtest.dataset import build_dataset
from backtest.diagnostics import run_diagnostics
from backtest.history_cache import clear_ohlc_cache, get_ohlc
from backtest.metrics import core_metrics, monte_carlo_max_dd, score_calibration, spearman_score_r
from backtest.paths import DATASET_PATH, REPO_ROOT, RUNS_DIR
from backtest.position import _sort_signals, busy_until_bar, exit_bar_from_close_time
from backtest.random_baseline import random_baseline_stats
from backtest.reporting import collect_alarms, print_slice_table, write_summary
from backtest.reports_export import export_reports
from backtest.run_lock import acquire_run_lock
from backtest.signals import generate_signals, signal_meta_path
from backtest.simulator import SimSignal, simulate_trade, tp1_before_sl_on_path, trade_to_dict
from backtest.split import tag_sample
from core.models import Direction, EntryType

logger = logging.getLogger(__name__)


def _git_hash() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return ""


def _row_to_sim(r: pd.Series) -> SimSignal:
    return SimSignal(
        direction=Direction(str(r["direction"])),
        entry_type=EntryType(str(r["entry_type"])),
        entry=float(r["entry"]),
        stop_loss=float(r["stop_loss"]),
        tp1=float(r["tp1"]),
        tp2=float(r["tp2"]),
        tp3=float(r["tp3"]),
        signal_bar=int(r["bar_index"]),
        strategy=str(r["strategy"]),
        score=float(r["score"]),
        setup_id=str(r["setup_id"]),
    )


def _skipped_trade_row(r: pd.Series, exit_model: str) -> dict:
    return {
        "symbol": str(r["symbol"]),
        "timeframe": str(r["timeframe"]),
        "exit_model": exit_model,
        "direction": str(r["direction"]),
        "strategy": str(r["strategy"]),
        "score": float(r["score"]),
        "entry_type": str(r["entry_type"]),
        "signal_time": pd.to_datetime(int(r["close_time"]), unit="ms", utc=True).to_pydatetime(),
        "fill_time": None,
        "exit_time": None,
        "entry_price": 0.0,
        "exit_price": 0.0,
        "outcome": "SKIPPED",
        "r_gross": 0.0,
        "r_net": 0.0,
        "fees_paid": 0.0,
        "funding_paid": 0.0,
        "bars_held": 0,
        "mae_r": 0.0,
        "mfe_r": 0.0,
        "filled": False,
        "tp1_before_sl": False,
        "exit_bar": None,
        "fill_bar": None,
        "setup_id": str(r["setup_id"]),
        "close_time": int(r["close_time"]),
        "stop_loss": float(r["stop_loss"]),
        "entry_level": float(r["entry"]),
        "skip_reason": "position_busy",
    }


def _trade_exit_bar(trade, frame, signal_bar: int) -> int | None:
    if trade.exit_bar is not None:
        return trade.exit_bar
    if trade.exit_time is not None:
        ms = int(pd.Timestamp(trade.exit_time).timestamp() * 1000)
        return exit_bar_from_close_time(frame.close_time, ms)
    return None


def simulate_slice(
    signals: pd.DataFrame,
    cfg: BacktestConfig,
    exit_model: str,
    tp1_cache: dict[str, bool] | None = None,
) -> pd.DataFrame:
    trade_rows: list[dict] = []
    for (_sym, _tf), grp in _sort_signals(signals).groupby(["symbol", "timeframe"], sort=False):
        frame = get_ohlc(str(_sym), str(_tf))
        busy_until = -1
        for _, r in grp.iterrows():
            bi = int(r["bar_index"])
            if cfg.one_position_per_symbol and bi <= busy_until:
                trade_rows.append(_skipped_trade_row(r, exit_model))
                continue
            sim = _row_to_sim(r)
            trade = simulate_trade(
                frame.df,
                sim,
                cfg,
                exit_model=exit_model,
                symbol=str(_sym),
                timeframe=str(_tf),
            )
            d = trade_to_dict(trade)
            d["setup_id"] = str(r["setup_id"])
            d["close_time"] = int(r["close_time"])
            d["stop_loss"] = float(r["stop_loss"])
            d["entry_level"] = float(r["entry"])
            d["skip_reason"] = ""
            if trade.filled and tp1_cache is not None:
                sid = str(r["setup_id"])
                if sid not in tp1_cache:
                    tp1_cache[sid] = tp1_before_sl_on_path(
                        frame.df, sim, cfg, timeframe=str(_tf)
                    )
                d["tp1_before_sl"] = tp1_cache[sid]
            exit_bar = _trade_exit_bar(trade, frame, bi)
            if exit_bar is not None:
                d["exit_bar"] = exit_bar
            trade_rows.append(d)
            if cfg.one_position_per_symbol:
                busy_until = busy_until_bar(
                    bi,
                    filled=trade.filled,
                    fill_bar=trade.fill_bar,
                    exit_bar=exit_bar,
                    outcome=trade.outcome,
                )
    if not trade_rows:
        return pd.DataFrame()
    out = pd.DataFrame(trade_rows)
    return tag_sample(out, cfg, time_col="close_time")


def run_backtest(
    symbols: list[str],
    timeframes: list[str],
    cfg: BacktestConfig,
    *,
    reuse_signals: bool = False,
) -> Path:
    with acquire_run_lock():
        return _run_backtest_body(symbols, timeframes, cfg, reuse_signals=reuse_signals)


def _run_backtest_body(
    symbols: list[str],
    timeframes: list[str],
    cfg: BacktestConfig,
    *,
    reuse_signals: bool = False,
) -> Path:
    run_id = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "config.json").write_text(
        json.dumps({**cfg.to_json(), "git_commit": _git_hash()}, indent=2),
        encoding="utf-8",
    )
    t0 = time.perf_counter()
    sig_t0 = time.perf_counter()
    all_signals: list[pd.DataFrame] = []
    for sym in symbols:
        for tf in timeframes:
            path = Path(f"data/backtest/signals/{sym}_{tf}.parquet")
            meta = signal_meta_path(sym, tf)
            if reuse_signals and path.exists():
                meta_info = json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else {}
                logger.warning("Reusing cached signals %s: %s", path.name, meta_info)
                sig = pd.read_parquet(path)
            else:
                sig = generate_signals(sym, tf)
            sig["symbol"] = sym
            sig["timeframe"] = tf
            all_signals.append(sig)
    signals = pd.concat(all_signals, ignore_index=True) if all_signals else pd.DataFrame()
    signal_sec = time.perf_counter() - sig_t0

    clear_ohlc_cache()
    sim_t0 = time.perf_counter()
    tp1_cache: dict[str, bool] = {}
    trade_parts: list[pd.DataFrame] = []
    for exit_model in cfg.exit_models:
        part = simulate_slice(signals, cfg, exit_model, tp1_cache=tp1_cache)
        if not part.empty:
            part["exit_model"] = exit_model
            trade_parts.append(part)
    trades = pd.concat(trade_parts, ignore_index=True) if trade_parts else pd.DataFrame()
    sim_sec = time.perf_counter() - sim_t0
    print(f"Simulation finished in {sim_sec:.1f}s ({len(trades)} rows)", flush=True)

    trades.to_parquet(run_dir / "trades.parquet", index=False)
    signals.to_parquet(run_dir / "signals.parquet", index=False)

    ds_trades = trades[
        trades["filled"]
        & (trades.get("skip_reason", "") != "position_busy")
        & (trades["exit_model"] == cfg.exit_models[0])
    ]
    dataset = build_dataset(signals, ds_trades)
    if not dataset.empty:
        DATASET_PATH.parent.mkdir(parents=True, exist_ok=True)
        dataset.to_parquet(DATASET_PATH, index=False)

    summary: dict = {
        "runtime_sec": time.perf_counter() - t0,
        "signal_load_sec": signal_sec,
        "simulation_sec": sim_sec,
        "by_slice": {},
    }
    cal_oos_by_model: dict[str, pd.DataFrame] = {}
    for exit_model in cfg.exit_models:
        sub = trades[trades["exit_model"] == exit_model] if not trades.empty else pd.DataFrame()
        for (sym, tf), grp in sub.groupby(["symbol", "timeframe"]):
            frame = get_ohlc(str(sym), str(tf))
            slice_key = f"{sym}|{tf}|{exit_model}"
            summary["by_slice"][slice_key] = {}
            raw_n = len(signals[(signals["symbol"] == sym) & (signals["timeframe"] == tf)])
            sym_sigs = signals[(signals["symbol"] == sym) & (signals["timeframe"] == tf)]
            for sample in ("IS", "OOS", "ALL"):
                if sample == "ALL":
                    g = grp
                else:
                    g = grp[grp["sample"] == sample] if "sample" in grp.columns else grp
                m = core_metrics(g, raw_signals=raw_n, cfg=cfg)
                m["spearman_score_r"] = spearman_score_r(g)
                m["mc_dd_95"] = monte_carlo_max_dd(g)
                if sample == "ALL":
                    is_m = summary["by_slice"][slice_key].get("IS", {})
                    oos_m = summary["by_slice"][slice_key].get("OOS", {})
                    is_n = max(1, int(is_m.get("trades", 0)))
                    oos_n = max(1, int(oos_m.get("trades", 0)))
                    is_pct = float(is_m.get("random_baseline_pct", 50.0))
                    oos_pct = float(oos_m.get("random_baseline_pct", 50.0))
                    m["random_baseline_pct"] = (is_pct * is_n + oos_pct * oos_n) / (is_n + oos_n)
                    rb_is = is_m.get("random_baseline", {})
                    rb_oos = oos_m.get("random_baseline", {})
                    if rb_is or rb_oos:
                        m["random_baseline"] = {
                            "weighted_pct": m["random_baseline_pct"],
                            "is": rb_is,
                            "oos": rb_oos,
                        }
                else:
                    print(f"  MC baseline {slice_key} {sample}…", flush=True)
                    rb = random_baseline_stats(
                        frame,
                        sym_sigs,
                        g,
                        cfg,
                        exit_model,
                        sample=sample,
                    )
                    m["random_baseline_pct"] = rb["percentile"]
                    m["random_baseline"] = rb
                summary["by_slice"][slice_key][sample] = m
            oos = grp[(grp["filled"]) & (grp["sample"] == "OOS")] if "sample" in grp.columns else grp.iloc[0:0]
            cal = score_calibration(oos)
            cal.to_csv(run_dir / f"score_cal_{sym}_{tf}_{exit_model}.csv", index=False)
            if not cal.empty:
                cal_oos_by_model[f"{sym}|{tf}|{exit_model}"] = cal

    collect_alarms(summary)
    diag_text = run_diagnostics(run_dir, signals, trades, cfg, symbols, timeframes)
    text = print_slice_table(summary, cal_oos_by_model) + "\n" + diag_text
    write_summary(run_dir, summary, text)
    console_out = run_dir / "run_console.txt"
    console_out.write_text(text, encoding="utf-8")
    legacy = REPO_ROOT / "data" / "backtest" / "phase34_run_console.txt"
    legacy.write_text(text, encoding="utf-8")
    export_reports(run_dir, console_out)
    print(f"\nSimulation: {sim_sec:.1f}s | Signal load/scan: {signal_sec:.1f}s")
    print(f"Backtest complete — {run_dir}")
    return run_dir


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    p = argparse.ArgumentParser()
    p.add_argument("--symbols", default="BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,DOGEUSDT")
    p.add_argument("--tfs", default="5m,15m,1h")
    p.add_argument("--months", type=int, default=24)
    p.add_argument("--exit-models", default="tp1_full,partial_be")
    p.add_argument("--intrabar", default="conservative", choices=("conservative", "1m"))
    p.add_argument("--reuse-signals", action="store_true", help="Load cached signal parquet; skip scanning")
    args = p.parse_args()
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    tfs = [s.strip() for s in args.tfs.split(",") if s.strip()]
    cfg = BacktestConfig(
        exit_models=tuple(s.strip() for s in args.exit_models.split(",") if s.strip()),
        intrabar_resolution=args.intrabar,
    )
    run_backtest(symbols, tfs, cfg, reuse_signals=args.reuse_signals)


if __name__ == "__main__":
    main()