"""
Deterministic trade simulator (conservative fills, no look-ahead).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum

import pandas as pd

from backtest.config import BacktestConfig
from core.config import SETUP_EXPIRY_CANDLES
from core.models import Direction, EntryType


class Outcome(str, Enum):
    TP1 = "TP1"
    TP2 = "TP2"
    TP3 = "TP3"
    SL = "SL"
    BE = "BE"
    TIMEOUT = "TIMEOUT"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"
    NO_FILL = "NO_FILL"


@dataclass
class SimSignal:
    direction: Direction
    entry_type: EntryType
    entry: float
    stop_loss: float
    tp1: float
    tp2: float
    tp3: float
    signal_bar: int
    strategy: str = ""
    score: float = 0.0
    setup_id: str = ""


@dataclass
class SimTrade:
    symbol: str
    timeframe: str
    exit_model: str
    direction: str
    strategy: str
    score: float
    entry_type: str
    signal_time: datetime
    fill_time: datetime | None
    exit_time: datetime | None
    entry_price: float
    exit_price: float
    outcome: str
    r_gross: float
    r_net: float
    fees_paid: float
    funding_paid: float
    bars_held: int
    mae_r: float
    mfe_r: float
    filled: bool


def _fee_rates(cfg: BacktestConfig, *, is_maker: bool) -> float:
    if cfg.fee_model == "conservative":
        return cfg.taker_fee + cfg.slippage
    fee = cfg.maker_fee if is_maker else cfg.taker_fee
    return fee + cfg.slippage


def _risk(signal: SimSignal) -> float:
    return abs(signal.entry - signal.stop_loss)


def _apply_slippage(price: float, direction: Direction, side: str, slip: float) -> float:
    """side: entry|exit — long entry pays more, long exit receives less."""
    if direction == Direction.LONG:
        return price * (1 + slip) if side == "entry" else price * (1 - slip)
    return price * (1 - slip) if side == "entry" else price * (1 + slip)


def _bar_hit_long(bar, level: float, *, above: bool) -> bool:
    if above:
        return float(bar["high"]) > level
    return float(bar["low"]) < level


def _bar_hit_short(bar, level: float, *, above: bool) -> bool:
    if above:
        return float(bar["high"]) > level
    return float(bar["low"]) < level


def _same_bar_sl_first_long(bar, sl: float, tp: float) -> str:
    sl_hit = float(bar["low"]) < sl
    tp_hit = float(bar["high"]) > tp
    if sl_hit:
        return Outcome.SL.value
    if tp_hit:
        return Outcome.TP1.value
    return ""


def _same_bar_sl_first_short(bar, sl: float, tp: float) -> str:
    sl_hit = float(bar["high"]) > sl
    tp_hit = float(bar["low"]) < tp
    if sl_hit:
        return Outcome.SL.value
    if tp_hit:
        return Outcome.TP1.value
    return ""


def simulate_trade(
    df: pd.DataFrame,
    signal: SimSignal,
    cfg: BacktestConfig,
    *,
    exit_model: str,
    symbol: str = "",
    timeframe: str = "15m",
    funding: pd.DataFrame | None = None,
    intrabar_1m: pd.DataFrame | None = None,
) -> SimTrade:
    """Simulate from bars strictly after signal bar."""
    risk = _risk(signal)
    if risk <= 0:
        return _empty_trade(signal, cfg, exit_model, symbol, timeframe)
    i0 = signal.signal_bar
    if i0 >= len(df) - 1:
        return _empty_trade(signal, cfg, exit_model, symbol, timeframe, reason=Outcome.NO_FILL)

    sig_time = pd.Timestamp(df["time"].iloc[i0]).to_pydatetime()
    slip = cfg.slippage
    taker_all = cfg.fee_model == "conservative"

    # Pending limit fill window
    fill_idx = None
    fill_price = signal.entry
    if signal.entry_type == EntryType.MARKET:
        nxt = df.iloc[i0 + 1]
        fill_idx = i0 + 1
        fill_price = _apply_slippage(float(nxt["open"]), signal.direction, "entry", slip)
    else:
        deadline = min(len(df) - 1, i0 + SETUP_EXPIRY_CANDLES)
        for j in range(i0 + 1, deadline + 1):
            bar = df.iloc[j]
            invalidated = False
            if signal.direction == Direction.LONG:
                if _bar_hit_long(bar, signal.stop_loss, above=False):
                    invalidated = True
                if _bar_hit_long(bar, signal.tp1, above=True):
                    invalidated = True
                filled = float(bar["low"]) < signal.entry
            else:
                if _bar_hit_short(bar, signal.stop_loss, above=True):
                    invalidated = True
                if _bar_hit_short(bar, signal.tp1, above=False):
                    invalidated = True
                filled = float(bar["high"]) > signal.entry
            if invalidated:
                return _mk(
                    signal,
                    cfg,
                    exit_model,
                    symbol,
                    timeframe,
                    sig_time,
                    None,
                    None,
                    0.0,
                    0.0,
                    Outcome.INVALIDATED,
                    0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    filled=False,
                )
            if filled:
                fill_idx = j
                maker = not taker_all
                fill_price = signal.entry
                fill_price = _apply_slippage(fill_price, signal.direction, "entry", slip if not maker else 0.0)
                break
        if fill_idx is None:
            return _mk(
                signal,
                cfg,
                exit_model,
                symbol,
                timeframe,
                sig_time,
                None,
                None,
                0.0,
                0.0,
                Outcome.EXPIRED,
                0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                filled=False,
            )
        # fill bar SL check
        bar = df.iloc[fill_idx]
        if signal.direction == Direction.LONG and float(bar["low"]) < signal.stop_loss:
            exit_p = float(bar["open"]) if float(bar["open"]) < signal.stop_loss else signal.stop_loss
            exit_p = _apply_slippage(exit_p, signal.direction, "exit", slip)
            r_g, r_n, fees = _r_multiple(signal, fill_price, exit_p, risk, cfg, legs=1)
            return _mk(
                signal,
                cfg,
                exit_model,
                symbol,
                timeframe,
                sig_time,
                pd.Timestamp(bar["time"]).to_pydatetime(),
                pd.Timestamp(bar["time"]).to_pydatetime(),
                fill_price,
                exit_p,
                Outcome.SL,
                fill_idx - i0,
                r_g,
                r_n,
                fees,
                0.0,
                -abs(r_g),
                0.0,
                filled=True,
            )

    assert fill_idx is not None
    if exit_model == "partial_be":
        return _simulate_partial_be(
            df,
            signal,
            cfg,
            fill_idx,
            fill_price,
            i0,
            sig_time,
            symbol,
            timeframe,
            slip,
            taker_all,
            risk,
        )

    sl = signal.stop_loss
    tp1 = signal.tp1
    max_hold = cfg.max_hold_bars.get(timeframe, 32)
    remaining = 1.0
    fees_paid = _leg_fee(fill_price, cfg, taker=True)
    funding_paid = 0.0
    mae = 0.0
    mfe = 0.0

    for k in range(fill_idx, min(len(df), fill_idx + max_hold + 1)):
        bar = df.iloc[k]
        # gap through SL
        if signal.direction == Direction.LONG:
            if float(bar["open"]) < sl:
                exit_p = _apply_slippage(float(bar["open"]), signal.direction, "exit", slip)
                r_g, r_n, f = _r_multiple(signal, fill_price, exit_p, risk, cfg, legs=remaining)
                fees_paid += f
                return _mk(
                    signal,
                    cfg,
                    exit_model,
                    symbol,
                    timeframe,
                    sig_time,
                    pd.Timestamp(df["time"].iloc[fill_idx]).to_pydatetime(),
                    pd.Timestamp(bar["time"]).to_pydatetime(),
                    fill_price,
                    exit_p,
                    Outcome.SL,
                    k - fill_idx,
                    r_g,
                    r_n,
                    fees_paid,
                    funding_paid,
                    mae,
                    mfe,
                    filled=True,
                )
            same = _same_bar_sl_first_long(bar, sl, tp1)
            if same == Outcome.SL.value:
                exit_p = _apply_slippage(sl, signal.direction, "exit", slip)
                r_g, r_n, f = _r_multiple(signal, fill_price, exit_p, risk, cfg, legs=remaining)
                fees_paid += f
                return _mk(
                    signal,
                    cfg,
                    exit_model,
                    symbol,
                    timeframe,
                    sig_time,
                    pd.Timestamp(df["time"].iloc[fill_idx]).to_pydatetime(),
                    pd.Timestamp(bar["time"]).to_pydatetime(),
                    fill_price,
                    exit_p,
                    Outcome.SL,
                    k - fill_idx,
                    r_g,
                    r_n,
                    fees_paid,
                    funding_paid,
                    mae,
                    mfe,
                    filled=True,
                )
            if same == Outcome.TP1.value and exit_model == "tp1_full":
                exit_p = _apply_slippage(tp1, signal.direction, "exit", slip if taker_all else 0)
                r_g, r_n, f = _r_multiple(signal, fill_price, exit_p, risk, cfg, legs=remaining)
                fees_paid += f
                return _mk(
                    signal,
                    cfg,
                    exit_model,
                    symbol,
                    timeframe,
                    sig_time,
                    pd.Timestamp(df["time"].iloc[fill_idx]).to_pydatetime(),
                    pd.Timestamp(bar["time"]).to_pydatetime(),
                    fill_price,
                    exit_p,
                    Outcome.TP1,
                    k - fill_idx,
                    r_g,
                    r_n,
                    fees_paid,
                    funding_paid,
                    mae,
                    mfe,
                    filled=True,
                )
        else:
            # mirror SHORT — abbreviated for brevity; use symmetric checks
            if float(bar["open"]) > sl:
                exit_p = _apply_slippage(float(bar["open"]), signal.direction, "exit", slip)
                r_g, r_n, f = _r_multiple(signal, fill_price, exit_p, risk, cfg, legs=remaining)
                fees_paid += f
                return _mk(
                    signal,
                    cfg,
                    exit_model,
                    symbol,
                    timeframe,
                    sig_time,
                    pd.Timestamp(df["time"].iloc[fill_idx]).to_pydatetime(),
                    pd.Timestamp(bar["time"]).to_pydatetime(),
                    fill_price,
                    exit_p,
                    Outcome.SL,
                    k - fill_idx,
                    r_g,
                    r_n,
                    fees_paid,
                    funding_paid,
                    mae,
                    mfe,
                    filled=True,
                )
            same = _same_bar_sl_first_short(bar, sl, tp1)
            if same == Outcome.SL.value:
                exit_p = _apply_slippage(sl, signal.direction, "exit", slip)
                r_g, r_n, f = _r_multiple(signal, fill_price, exit_p, risk, cfg, legs=remaining)
                fees_paid += f
                return _mk(
                    signal,
                    cfg,
                    exit_model,
                    symbol,
                    timeframe,
                    sig_time,
                    pd.Timestamp(df["time"].iloc[fill_idx]).to_pydatetime(),
                    pd.Timestamp(bar["time"]).to_pydatetime(),
                    fill_price,
                    exit_p,
                    Outcome.SL,
                    k - fill_idx,
                    r_g,
                    r_n,
                    fees_paid,
                    funding_paid,
                    mae,
                    mfe,
                    filled=True,
                )
            if same == Outcome.TP1.value and exit_model == "tp1_full":
                exit_p = _apply_slippage(tp1, signal.direction, "exit", slip if taker_all else 0)
                r_g, r_n, f = _r_multiple(signal, fill_price, exit_p, risk, cfg, legs=remaining)
                fees_paid += f
                return _mk(
                    signal,
                    cfg,
                    exit_model,
                    symbol,
                    timeframe,
                    sig_time,
                    pd.Timestamp(df["time"].iloc[fill_idx]).to_pydatetime(),
                    pd.Timestamp(bar["time"]).to_pydatetime(),
                    fill_price,
                    exit_p,
                    Outcome.TP1,
                    k - fill_idx,
                    r_g,
                    r_n,
                    fees_paid,
                    funding_paid,
                    mae,
                    mfe,
                    filled=True,
                )

    # timeout
    last = df.iloc[min(len(df) - 1, fill_idx + max_hold)]
    exit_p = _apply_slippage(float(last["close"]), signal.direction, "exit", slip)
    r_g, r_n, f = _r_multiple(signal, fill_price, exit_p, risk, cfg, legs=remaining)
    fees_paid += f
    return _mk(
        signal,
        cfg,
        exit_model,
        symbol,
        timeframe,
        sig_time,
        pd.Timestamp(df["time"].iloc[fill_idx]).to_pydatetime(),
        pd.Timestamp(last["time"]).to_pydatetime(),
        fill_price,
        exit_p,
        Outcome.TIMEOUT,
        min(len(df) - 1, fill_idx + max_hold) - fill_idx,
        r_g,
        r_n,
        fees_paid,
        funding_paid,
        mae,
        mfe,
        filled=True,
    )


PARTIAL_LEG_FRACS = (0.5, 0.3, 0.2)


def _breakeven_stop(fill_price: float, cfg: BacktestConfig, direction: Direction) -> float:
    """Stop level after TP1 that nets ~zero after round-trip costs."""
    if cfg.fee_model == "conservative":
        rt = (cfg.taker_fee + cfg.slippage) * 2
    else:
        rt = cfg.taker_fee * 2 + cfg.slippage * 2
    if direction == Direction.LONG:
        return fill_price * (1 + rt)
    return fill_price * (1 - rt)


def _simulate_partial_be(
    df: pd.DataFrame,
    signal: SimSignal,
    cfg: BacktestConfig,
    fill_idx: int,
    fill_price: float,
    signal_bar: int,
    sig_time: datetime,
    symbol: str,
    timeframe: str,
    slip: float,
    taker_all: bool,
    risk: float,
) -> SimTrade:
    max_hold = cfg.max_hold_bars.get(timeframe, 32)
    sl = signal.stop_loss
    tp1, tp2, tp3 = signal.tp1, signal.tp2, signal.tp3
    remain = 1.0
    leg_i = 0
    tp1_done = False
    fees_paid = _leg_fee(fill_price, cfg, taker=True)
    r_gross = 0.0
    r_net = 0.0
    mae = 0.0
    mfe = 0.0
    exit_px_acc = 0.0
    exit_frac_acc = 0.0
    final_outcome = Outcome.TIMEOUT.value
    exit_time = None

    def _take(exit_raw: float, frac: float, outcome: str, *, maker: bool = False) -> None:
        nonlocal remain, fees_paid, r_gross, r_net, exit_px_acc, exit_frac_acc, final_outcome, exit_time
        if frac <= 0:
            return
        exit_p = _apply_slippage(exit_raw, signal.direction, "exit", slip if (taker_all or not maker) else 0.0)
        g, n, f = _r_multiple(signal, fill_price, exit_p, risk, cfg, legs=frac)
        r_gross += g
        r_net += n
        fees_paid += f
        remain -= frac
        exit_px_acc += exit_p * frac
        exit_frac_acc += frac
        final_outcome = outcome
        exit_time = None

    def _finish(bar, outcome: str, exit_raw: float, bars_held: int) -> SimTrade:
        nonlocal exit_time
        if remain > 0:
            _take(exit_raw, remain, outcome)
        exit_time = pd.Timestamp(bar["time"]).to_pydatetime()
        avg_exit = exit_px_acc / exit_frac_acc if exit_frac_acc > 0 else float(bar["close"])
        return _mk(
            signal,
            cfg,
            "partial_be",
            symbol,
            timeframe,
            sig_time,
            pd.Timestamp(df["time"].iloc[fill_idx]).to_pydatetime(),
            exit_time,
            fill_price,
            avg_exit,
            final_outcome,
            bars_held,
            r_gross,
            r_net,
            fees_paid,
            0.0,
            mae,
            mfe,
            filled=True,
        )

    for k in range(fill_idx, min(len(df), fill_idx + max_hold + 1)):
        bar = df.iloc[k]
        o, h, l = float(bar["open"]), float(bar["high"]), float(bar["low"])
        if signal.direction == Direction.LONG:
            adverse = (fill_price - l) / risk if risk else 0.0
            favorable = (h - fill_price) / risk if risk else 0.0
        else:
            adverse = (h - fill_price) / risk if risk else 0.0
            favorable = (fill_price - l) / risk if risk else 0.0
        mae = min(mae, -abs(adverse))
        mfe = max(mfe, favorable)

        if signal.direction == Direction.LONG:
            if not tp1_done:
                if o < sl:
                    return _finish(bar, Outcome.SL.value, o, k - fill_idx)
                same = _same_bar_sl_first_long(bar, sl, tp1)
                if same == Outcome.SL.value:
                    return _finish(bar, Outcome.SL.value, sl, k - fill_idx)
                if same != Outcome.TP1.value:
                    continue
                _take(tp1, PARTIAL_LEG_FRACS[0], Outcome.TP1.value, maker=not taker_all)
                tp1_done = True
                remain = PARTIAL_LEG_FRACS[1] + PARTIAL_LEG_FRACS[2]
                leg_i = 1
                sl = _breakeven_stop(fill_price, cfg, signal.direction)
                if l < sl:
                    return _finish(bar, Outcome.BE.value, sl, k - fill_idx)
                if h > tp2:
                    _take(tp2, PARTIAL_LEG_FRACS[1], Outcome.TP2.value, maker=not taker_all)
                    leg_i = 2
                    remain = PARTIAL_LEG_FRACS[2]
                    if l < sl:
                        return _finish(bar, Outcome.BE.value, sl, k - fill_idx)
                    if h > tp3:
                        return _finish(bar, Outcome.TP3.value, tp3, k - fill_idx)
                continue

            if o < sl:
                return _finish(bar, Outcome.BE.value if sl >= fill_price else Outcome.SL.value, o, k - fill_idx)
            if l < sl:
                return _finish(bar, Outcome.BE.value, sl, k - fill_idx)
            if leg_i == 1 and h > tp2:
                _take(tp2, PARTIAL_LEG_FRACS[1], Outcome.TP2.value, maker=not taker_all)
                leg_i = 2
                remain = PARTIAL_LEG_FRACS[2]
                if l < sl:
                    return _finish(bar, Outcome.BE.value, sl, k - fill_idx)
            if leg_i == 2 and h > tp3:
                return _finish(bar, Outcome.TP3.value, tp3, k - fill_idx)
        else:
            if not tp1_done:
                if o > sl:
                    return _finish(bar, Outcome.SL.value, o, k - fill_idx)
                same = _same_bar_sl_first_short(bar, sl, tp1)
                if same == Outcome.SL.value:
                    return _finish(bar, Outcome.SL.value, sl, k - fill_idx)
                if same != Outcome.TP1.value:
                    continue
                _take(tp1, PARTIAL_LEG_FRACS[0], Outcome.TP1.value, maker=not taker_all)
                tp1_done = True
                remain = PARTIAL_LEG_FRACS[1] + PARTIAL_LEG_FRACS[2]
                leg_i = 1
                sl = _breakeven_stop(fill_price, cfg, signal.direction)
                if h > sl:
                    return _finish(bar, Outcome.BE.value, sl, k - fill_idx)
                if l < tp2:
                    _take(tp2, PARTIAL_LEG_FRACS[1], Outcome.TP2.value, maker=not taker_all)
                    leg_i = 2
                    remain = PARTIAL_LEG_FRACS[2]
                    if h > sl:
                        return _finish(bar, Outcome.BE.value, sl, k - fill_idx)
                    if l < tp3:
                        return _finish(bar, Outcome.TP3.value, tp3, k - fill_idx)
                continue

            if o > sl:
                return _finish(bar, Outcome.BE.value if sl <= fill_price else Outcome.SL.value, o, k - fill_idx)
            if h > sl:
                return _finish(bar, Outcome.BE.value, sl, k - fill_idx)
            if leg_i == 1 and l < tp2:
                _take(tp2, PARTIAL_LEG_FRACS[1], Outcome.TP2.value, maker=not taker_all)
                leg_i = 2
                remain = PARTIAL_LEG_FRACS[2]
                if h > sl:
                    return _finish(bar, Outcome.BE.value, sl, k - fill_idx)
            if leg_i == 2 and l < tp3:
                return _finish(bar, Outcome.TP3.value, tp3, k - fill_idx)

    last = df.iloc[min(len(df) - 1, fill_idx + max_hold)]
    exit_p = _apply_slippage(float(last["close"]), signal.direction, "exit", slip)
    if remain > 0:
        g, n, f = _r_multiple(signal, fill_price, exit_p, risk, cfg, legs=remain)
        r_gross += g
        r_net += n
        fees_paid += f
        exit_px_acc += exit_p * remain
        exit_frac_acc += remain
    avg_exit = exit_px_acc / exit_frac_acc if exit_frac_acc > 0 else exit_p
    return _mk(
        signal,
        cfg,
        "partial_be",
        symbol,
        timeframe,
        sig_time,
        pd.Timestamp(df["time"].iloc[fill_idx]).to_pydatetime(),
        pd.Timestamp(last["time"]).to_pydatetime(),
        fill_price,
        avg_exit,
        final_outcome if remain <= 0 else Outcome.TIMEOUT.value,
        min(len(df) - 1, fill_idx + max_hold) - fill_idx,
        r_gross,
        r_net,
        fees_paid,
        0.0,
        mae,
        mfe,
        filled=True,
    )


def _leg_fee(price: float, cfg: BacktestConfig, *, taker: bool) -> float:
    rate = _fee_rates(cfg, is_maker=not taker)
    return price * rate


def _r_multiple(
    signal: SimSignal,
    entry: float,
    exit_p: float,
    risk: float,
    cfg: BacktestConfig,
    *,
    legs: float,
) -> tuple[float, float, float]:
    if risk <= 0:
        return 0.0, 0.0, 0.0
    if signal.direction == Direction.LONG:
        gross = (exit_p - entry) / risk * legs
    else:
        gross = (entry - exit_p) / risk * legs
    fees = _leg_fee(entry, cfg, taker=True) + _leg_fee(exit_p, cfg, taker=cfg.fee_model == "conservative")
    fee_r = fees / risk if risk else 0.0
    return gross, gross - fee_r, fees


def _empty_trade(signal, cfg, exit_model, symbol, timeframe, reason=Outcome.NO_FILL):
    return _mk(
        signal,
        cfg,
        exit_model,
        symbol,
        timeframe,
        datetime.now().astimezone(),
        None,
        None,
        0.0,
        0.0,
        reason.value,
        0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        filled=False,
    )


def _mk(
    signal,
    cfg,
    exit_model,
    symbol,
    timeframe,
    sig_time,
    fill_time,
    exit_time,
    entry_price,
    exit_price,
    outcome,
    bars_held,
    r_gross,
    r_net,
    fees_paid,
    funding_paid,
    mae,
    mfe,
    *,
    filled: bool,
) -> SimTrade:
    return SimTrade(
        symbol=symbol,
        timeframe=timeframe,
        exit_model=exit_model,
        direction=signal.direction.value,
        strategy=signal.strategy,
        score=signal.score,
        entry_type=signal.entry_type.value,
        signal_time=sig_time,
        fill_time=fill_time,
        exit_time=exit_time,
        entry_price=entry_price,
        exit_price=exit_price,
        outcome=outcome,
        r_gross=r_gross,
        r_net=r_net,
        fees_paid=fees_paid,
        funding_paid=funding_paid,
        bars_held=bars_held,
        mae_r=mae,
        mfe_r=mfe,
        filled=filled,
    )


def trade_to_dict(t: SimTrade) -> dict:
    return asdict(t)