"""Monte-Carlo random-entry baseline with matched trade mix and ATR distances."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import random
from concurrent.futures import ProcessPoolExecutor
from typing import Any

import numpy as np
import pandas as pd

from backtest.config import BacktestConfig
from backtest.history_cache import OhlcFrame, atr14, get_ohlc
from backtest.position import busy_until_bar, exit_bar_from_close_time
from backtest.simulator import SimSignal, simulate_trade, trade_to_dict
from core.models import Direction, EntryType

logger = logging.getLogger(__name__)


def _deterministic_seed(*parts: Any) -> int:
    payload = hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()
    return int(payload[:12], 16)


def _atr_multiples(row: pd.Series, atr: float) -> tuple[float, float, float, float]:
    entry = float(row["entry"])
    if atr <= 0 or np.isnan(atr):
        atr = abs(entry - float(row["stop_loss"])) or 1.0
    sl = abs(entry - float(row["stop_loss"])) / atr
    tp1 = abs(float(row["tp1"]) - entry) / atr
    tp2 = abs(float(row["tp2"]) - entry) / atr
    tp3 = abs(float(row["tp3"]) - entry) / atr
    return sl, tp1, tp2, tp3


def _build_random_signal_market(
    frame: OhlcFrame,
    bar: int,
    direction: str,
    sl_m: float,
    tp1_m: float,
    tp2_m: float,
    tp3_m: float,
    atr_val: float,
    rng: random.Random,
) -> SimSignal | None:
    if bar + 1 >= len(frame.close):
        return None
    entry = float(frame.open[bar + 1])
    atr_val = atr_val if atr_val > 0 else max(entry * 0.001, 1.0)
    if direction == Direction.LONG.value:
        sl = entry - sl_m * atr_val
        tp1 = entry + tp1_m * atr_val
        tp2 = entry + tp2_m * atr_val
        tp3 = entry + tp3_m * atr_val
    else:
        sl = entry + sl_m * atr_val
        tp1 = entry - tp1_m * atr_val
        tp2 = entry - tp2_m * atr_val
        tp3 = entry - tp3_m * atr_val
    return SimSignal(
        direction=Direction(direction),
        entry_type=EntryType.MARKET,
        entry=entry,
        stop_loss=sl,
        tp1=tp1,
        tp2=tp2,
        tp3=tp3,
        signal_bar=bar,
        strategy="random_mc",
        score=60.0,
        setup_id=f"mc_{bar}_{rng.randint(0, 1_000_000)}",
    )


def _simulate_mc_portfolio(
    frame: OhlcFrame,
    specs: list[tuple[int, SimSignal]],
    cfg: BacktestConfig,
    exit_model: str,
) -> list[dict]:
    specs = sorted(specs, key=lambda x: (x[1].signal_bar, x[0]))
    rows: list[dict] = []
    busy_until = -1
    for _ct, sig in specs:
        if sig.signal_bar <= busy_until:
            continue
        trade = simulate_trade(
            frame.df,
            sig,
            cfg,
            exit_model=exit_model,
            symbol=frame.symbol,
            timeframe=frame.timeframe,
        )
        exit_bar = trade.exit_bar
        if exit_bar is None and trade.exit_time is not None:
            ms = int(pd.Timestamp(trade.exit_time).timestamp() * 1000)
            exit_bar = exit_bar_from_close_time(frame.close_time, ms)
        busy_until = busy_until_bar(
            sig.signal_bar,
            filled=trade.filled,
            fill_bar=trade.fill_bar,
            exit_bar=exit_bar,
            outcome=trade.outcome,
        )
        if trade.filled:
            rows.append(trade_to_dict(trade))
    return rows


def _mc_expectancy_for_frame(
    frame: OhlcFrame,
    exit_model: str,
    cfg: BacktestConfig,
    run_seed: int,
    eligible: list[int],
    mults: list[tuple[float, float, float, float]],
    directions: list[str],
    n_trades: int,
) -> float | None:
    atr = atr14(frame)
    rng = random.Random(run_seed)
    dir_pool = directions[:]
    rng.shuffle(dir_pool)
    pick_bars = [eligible[rng.randrange(len(eligible))] for _ in range(n_trades)]
    pick_bars.sort()
    specs: list[tuple[int, SimSignal]] = []
    for j, bar in enumerate(pick_bars):
        sl_m, tp1_m, tp2_m, tp3_m = mults[rng.randrange(len(mults))]
        d = dir_pool[j % len(dir_pool)]
        atr_v = (
            float(atr[bar])
            if bar < len(atr) and not np.isnan(atr[bar])
            else float(frame.close[bar]) * 0.01
        )
        sig = _build_random_signal_market(frame, bar, d, sl_m, tp1_m, tp2_m, tp3_m, atr_v, rng)
        if sig is None:
            continue
        specs.append((int(frame.close_time[bar]), sig))
    mc_rows = _simulate_mc_portfolio(frame, specs, cfg, exit_model)
    if not mc_rows:
        return None
    return float(np.mean([float(r["r_net"]) for r in mc_rows]))


def _one_mc_expectancy(task: tuple) -> float | None:
    symbol, tf, exit_model, cfg_dict, run_seed, eligible, mults, directions, n_trades = task
    frame = get_ohlc(symbol, tf)
    return _mc_expectancy_for_frame(
        frame,
        exit_model,
        BacktestConfig(**cfg_dict),
        run_seed,
        eligible,
        mults,
        directions,
        n_trades,
    )


def _summarize_exps(exps: list[float | None], strat_exp: float) -> dict[str, Any]:
    valid = [e for e in exps if e is not None]
    if not valid:
        return {
            "percentile": 50.0,
            "mean": 0.0,
            "std": 0.0,
            "p5": 0.0,
            "p50": 0.0,
            "p95": 0.0,
            "mc_valid_runs": 0,
            "mc_total_runs": len(exps),
        }
    arr = np.array(valid, dtype=np.float64)
    below = int((arr < strat_exp).sum())
    pct = below / len(valid) * 100.0
    return {
        "percentile": pct,
        "mean": float(arr.mean()),
        "std": float(arr.std(ddof=0)),
        "p5": float(np.percentile(arr, 5)),
        "p50": float(np.percentile(arr, 50)),
        "p95": float(np.percentile(arr, 95)),
        "mc_valid_runs": len(valid),
        "mc_total_runs": len(exps),
        "strategy_expectancy": strat_exp,
    }


def random_baseline_stats(
    frame: OhlcFrame,
    signals: pd.DataFrame,
    trades: pd.DataFrame,
    cfg: BacktestConfig,
    exit_model: str,
    *,
    sample: str = "ALL",
    n_mc: int = 200,
) -> dict[str, Any]:
    if "sample" in trades.columns and sample != "ALL":
        trades = trades[trades["sample"] == sample]
        sig_ids = set(trades["setup_id"].astype(str))
        signals = signals[signals["setup_id"].astype(str).isin(sig_ids)]
    filled = trades[trades["filled"]]
    if filled.empty:
        return _summarize_exps([], 0.0)
    strat_exp = float(filled["r_net"].astype(float).mean())
    merged = filled.merge(
        signals[
            [
                "setup_id",
                "bar_index",
                "close_time",
                "direction",
                "entry",
                "stop_loss",
                "tp1",
                "tp2",
                "tp3",
            ]
        ],
        on="setup_id",
        how="left",
        suffixes=("_t", ""),
    )
    atr = atr14(frame)
    mults: list[tuple[float, float, float, float]] = []
    directions: list[str] = []
    for _, row in merged.iterrows():
        bi = int(row["bar_index"])
        directions.append(str(row["direction"]))
        mults.append(_atr_multiples(row, float(atr[bi]) if bi < len(atr) else 1.0))
    n_trades = len(directions)
    if n_trades == 0:
        return _summarize_exps([], strat_exp)
    t_min = int(merged["close_time"].min())
    t_max = int(merged["close_time"].max())
    eligible = [
        i
        for i in range(20, len(frame.close) - 5)
        if t_min <= int(frame.close_time[i]) <= t_max
    ]
    if not eligible:
        return _summarize_exps([], strat_exp)
    base_seed = _deterministic_seed(cfg.random_seed, frame.symbol, frame.timeframe, exit_model, sample)
    cfg_dict = cfg.to_json()
    tasks = [
        (
            frame.symbol,
            frame.timeframe,
            exit_model,
            cfg_dict,
            base_seed + i,
            eligible,
            mults,
            directions,
            n_trades,
        )
        for i in range(n_mc)
    ]
    exps: list[float | None]
    if n_mc <= 16:
        exps = [
            _mc_expectancy_for_frame(
                frame,
                exit_model,
                cfg,
                base_seed + i,
                eligible,
                mults,
                directions,
                n_trades,
            )
            for i in range(n_mc)
        ]
    else:
        workers = max(1, (os.cpu_count() or 2) - 1)
        logger.info(
            "random baseline %s %s %s (%s): %d MC × %d trades, %d workers",
            frame.symbol,
            frame.timeframe,
            exit_model,
            sample,
            n_mc,
            n_trades,
            workers,
        )
        with ProcessPoolExecutor(max_workers=workers) as pool:
            exps = list(pool.map(_one_mc_expectancy, tasks, chunksize=2))
    return _summarize_exps(exps, strat_exp)


def random_baseline_percentile(*args, **kwargs) -> float:
    return float(random_baseline_stats(*args, **kwargs)["percentile"])