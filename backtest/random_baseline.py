"""Monte-Carlo random-entry baseline with matched trade mix and ATR distances."""

from __future__ import annotations

import logging
import os
import random
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

from backtest.config import BacktestConfig
from backtest.history_cache import OhlcFrame, atr14, get_ohlc
from backtest.position import busy_until_bar, exit_bar_from_close_time
from backtest.simulator import SimSignal, simulate_trade, trade_to_dict
from core.models import Direction, EntryType

logger = logging.getLogger(__name__)


def _atr_multiples(row: pd.Series, atr: float) -> tuple[float, float, float, float]:
    entry = float(row["entry"])
    if atr <= 0 or np.isnan(atr):
        atr = abs(entry - float(row["stop_loss"])) or 1.0
    sl = abs(entry - float(row["stop_loss"])) / atr
    tp1 = abs(float(row["tp1"]) - entry) / atr
    tp2 = abs(float(row["tp2"]) - entry) / atr
    tp3 = abs(float(row["tp3"]) - entry) / atr
    return sl, tp1, tp2, tp3


def _build_random_signal(
    frame: OhlcFrame,
    bar: int,
    direction: str,
    entry_type: str,
    sl_m: float,
    tp1_m: float,
    tp2_m: float,
    tp3_m: float,
    atr_val: float,
    rng: random.Random,
) -> SimSignal:
    entry = float(frame.close[bar])
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
        entry_type=EntryType(entry_type),
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
    entry_types: list[str],
    n_trades: int,
) -> float:
    atr = atr14(frame)
    rng = random.Random(run_seed)
    dir_pool = directions[:]
    et_pool = entry_types[:]
    rng.shuffle(dir_pool)
    rng.shuffle(et_pool)
    pick_bars = [eligible[rng.randrange(len(eligible))] for _ in range(n_trades)]
    pick_bars.sort()
    specs: list[tuple[int, SimSignal]] = []
    for j, bar in enumerate(pick_bars):
        sl_m, tp1_m, tp2_m, tp3_m = mults[rng.randrange(len(mults))]
        d = dir_pool[j % len(dir_pool)]
        et = et_pool[j % len(et_pool)]
        atr_v = (
            float(atr[bar])
            if bar < len(atr) and not np.isnan(atr[bar])
            else float(frame.close[bar]) * 0.01
        )
        sig = _build_random_signal(frame, bar, d, et, sl_m, tp1_m, tp2_m, tp3_m, atr_v, rng)
        specs.append((int(frame.close_time[bar]), sig))
    mc_rows = _simulate_mc_portfolio(frame, specs, cfg, exit_model)
    if not mc_rows:
        return -999.0
    return float(np.mean([float(r["r_net"]) for r in mc_rows]))


def _one_mc_expectancy(task: tuple) -> float:
    symbol, tf, exit_model, cfg_dict, run_seed, eligible, mults, directions, entry_types, n_trades = task
    frame = get_ohlc(symbol, tf)
    return _mc_expectancy_for_frame(
        frame,
        exit_model,
        BacktestConfig(**cfg_dict),
        run_seed,
        eligible,
        mults,
        directions,
        entry_types,
        n_trades,
    )


def random_baseline_percentile(
    frame: OhlcFrame,
    signals: pd.DataFrame,
    trades: pd.DataFrame,
    cfg: BacktestConfig,
    exit_model: str,
    *,
    sample: str = "ALL",
    n_mc: int = 200,
) -> float:
    if "sample" in trades.columns and sample != "ALL":
        trades = trades[trades["sample"] == sample]
        sig_ids = set(trades["setup_id"].astype(str))
        signals = signals[signals["setup_id"].astype(str).isin(sig_ids)]
    filled = trades[trades["filled"]]
    if filled.empty:
        return 50.0
    strat_exp = float(filled["r_net"].astype(float).mean())
    merged = filled.merge(
        signals[
            [
                "setup_id",
                "bar_index",
                "close_time",
                "direction",
                "entry_type",
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
    entry_types: list[str] = []
    for _, row in merged.iterrows():
        bi = int(row["bar_index"])
        directions.append(str(row["direction"]))
        entry_types.append(str(row["entry_type"]))
        mults.append(_atr_multiples(row, float(atr[bi]) if bi < len(atr) else 1.0))
    n_trades = len(directions)
    if n_trades == 0:
        return 50.0
    t_min = int(merged["close_time"].min())
    t_max = int(merged["close_time"].max())
    eligible = [
        i
        for i in range(20, len(frame.close) - 5)
        if t_min <= int(frame.close_time[i]) <= t_max
    ]
    if not eligible:
        return 50.0
    base_seed = cfg.random_seed + hash((frame.symbol, frame.timeframe, exit_model, sample)) % (2**31)
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
            entry_types,
            n_trades,
        )
        for i in range(n_mc)
    ]
    exps: list[float] = []
    if n_mc <= 16:
        for i in range(n_mc):
            exps.append(
                _mc_expectancy_for_frame(
                    frame,
                    exit_model,
                    cfg,
                    base_seed + i,
                    eligible,
                    mults,
                    directions,
                    entry_types,
                    n_trades,
                )
            )
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
    below = sum(1 for exp in exps if exp < strat_exp)
    return below / n_mc * 100.0