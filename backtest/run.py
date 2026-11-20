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
from backtest.history import ensure_indicators, load_history
from backtest.metrics import (
    core_metrics,
    cost_sensitivity,
    monte_carlo_max_dd,
    random_baseline_percentile,
    score_calibration,
    spearman_score_r,
    too_good_alarm,
)
from backtest.paths import DATASET_PATH, RUNS_DIR
from backtest.signals import generate_signals
from backtest.simulator import SimSignal, simulate_trade, trade_to_dict
from core.models import Direction, EntryType

logger = logging.getLogger(__name__)


def _git_hash() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return ""


def _signals_to_sim(signals: pd.DataFrame) -> list[tuple[str, str, SimSignal]]:
    out: list[tuple[str, str, SimSignal]] = []
    for _, r in signals.iterrows():
        out.append(
            (
                str(r["symbol"]),
                str(r["timeframe"]),
                SimSignal(
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
                ),
            )
        )
    return out


def run_backtest(
    symbols: list[str],
    timeframes: list[str],
    cfg: BacktestConfig,
    *,
    skip_signals: bool = False,
) -> Path:
    run_id = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "config.json").write_text(
        json.dumps({**cfg.to_json(), "git_commit": _git_hash()}, indent=2),
        encoding="utf-8",
    )
    t0 = time.perf_counter()
    all_signals: list[pd.DataFrame] = []
    for sym in symbols:
        for tf in timeframes:
            if skip_signals and Path(f"data/backtest/signals/{sym}_{tf}.parquet").exists():
                sig = pd.read_parquet(f"data/backtest/signals/{sym}_{tf}.parquet")
            else:
                sig = generate_signals(sym, tf)
            all_signals.append(sig)
    signals = pd.concat(all_signals, ignore_index=True) if all_signals else pd.DataFrame()

    trade_rows: list[dict] = []
    for exit_model in cfg.exit_models:
        for sym, tf, sim in _signals_to_sim(signals):
            df = ensure_indicators(load_history(sym, tf))
            trade = simulate_trade(df, sim, cfg, exit_model=exit_model, symbol=sym, timeframe=tf)
            trade_rows.append(trade_to_dict(trade))

    trades = pd.DataFrame(trade_rows)
    trades.to_parquet(run_dir / "trades.parquet", index=False)
    signals.to_parquet(run_dir / "signals.parquet", index=False)

    dataset = build_dataset(signals, trades[trades["filled"]])
    if not dataset.empty:
        DATASET_PATH.parent.mkdir(parents=True, exist_ok=True)
        dataset.to_parquet(DATASET_PATH, index=False)

    summary: dict = {"runtime_sec": time.perf_counter() - t0, "by_slice": {}}
    import random

    rng = random.Random(cfg.random_seed)
    for exit_model in cfg.exit_models:
        sub = trades[trades["exit_model"] == exit_model]
        for (sym, tf), grp in sub.groupby(["symbol", "timeframe"]):
            m = core_metrics(grp)
            m["random_baseline_pct"] = random_baseline_percentile(
                grp[grp["filled"]]["r_net"].astype(float).tolist(), rng
            )
            m["mc_dd_95"] = monte_carlo_max_dd(grp)
            m["spearman_score_r"] = spearman_score_r(grp)
            cal = score_calibration(grp)
            cal.to_csv(run_dir / f"score_cal_{sym}_{tf}_{exit_model}.csv", index=False)
            summary["by_slice"][f"{sym}|{tf}|{exit_model}"] = m
            for line in too_good_alarm(m, f"{sym} {tf}"):
                logger.warning(line)

    sens = {
        "cost_x1.5": cost_sensitivity(trades[trades["filled"]], 1.5),
        "cost_x2.0": cost_sensitivity(trades[trades["filled"]], 2.0),
    }
    (run_dir / "cost_sensitivity.json").write_text(json.dumps(sens, indent=2), encoding="utf-8")
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    _print_console(summary, run_dir)
    return run_dir


def _print_console(summary: dict, run_dir: Path) -> None:
    print(f"\nBacktest complete — {run_dir}")
    print(f"Runtime: {summary.get('runtime_sec', 0):.1f}s")
    for key, m in summary.get("by_slice", {}).items():
        print(
            f"  {key}: trades={m.get('trades')} "
            f"WR={m.get('win_rate', 0):.1%} "
            f"E[R]={m.get('expectancy_r', 0):.3f} "
            f"PF={m.get('profit_factor', 0):.2f} "
            f"DD={m.get('max_dd_r', 0):.2f} "
            f"rand%ile={m.get('random_baseline_pct', 0):.0f}"
        )


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    p = argparse.ArgumentParser()
    p.add_argument("--symbols", default="BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,DOGEUSDT")
    p.add_argument("--tfs", default="5m,15m,1h")
    p.add_argument("--months", type=int, default=24)
    p.add_argument("--exit-models", default="tp1_full,partial_be")
    p.add_argument("--intrabar", default="conservative", choices=("conservative", "1m"))
    args = p.parse_args()
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    tfs = [s.strip() for s in args.tfs.split(",") if s.strip()]
    cfg = BacktestConfig(
        exit_models=tuple(s.strip() for s in args.exit_models.split(",") if s.strip()),
        intrabar_resolution=args.intrabar,
    )
    run_backtest(symbols, tfs, cfg)


if __name__ == "__main__":
    main()