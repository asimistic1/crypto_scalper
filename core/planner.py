"""Trade planner — fee-inclusive risk sizing."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import ROUND_DOWN, ROUND_UP, Decimal
from typing import Literal

Direction = Literal["LONG", "SHORT"]
EntryType = Literal["limit", "market"]


@dataclass
class FeeConfig:
    maker: float = 0.0001
    taker: float = 0.0004
    slippage: float = 0.0002


@dataclass
class PlannerInput:
    direction: Direction
    entry: float
    stop_loss: float
    balance_usdt: float
    risk_pct: float
    leverage: float
    entry_type: EntryType = "market"
    tp1: float | None = None
    tp2: float | None = None
    tp3: float | None = None
    tick_size: float = 0.01
    step_size: float = 0.001
    min_notional: float = 5.0
    maint_margin_rate: float = 0.004
    fees: FeeConfig = field(default_factory=FeeConfig)
    atr: float | None = None
    zone_prices: tuple[float, ...] = ()
    tp_entry_type: EntryType = "limit"


def snap_price(price: float, tick: float, *, toward: str = "down") -> float:
    if tick <= 0:
        return price
    q = Decimal(str(price)) / Decimal(str(tick))
    if toward == "down":
        q = q.to_integral_value(rounding=ROUND_DOWN)
    else:
        q = q.to_integral_value(rounding=ROUND_UP)
    return float(q * Decimal(str(tick)))


def _sl_distance(inp: PlannerInput) -> float:
    if inp.direction == "LONG":
        return inp.entry - inp.stop_loss
    return inp.stop_loss - inp.entry


def _rate(inp: PlannerInput, *, is_entry: bool, exit_at_tp: bool) -> float:
    if is_entry:
        return inp.fees.maker if inp.entry_type == "limit" else inp.fees.taker
    return inp.fees.maker if exit_at_tp else inp.fees.taker


def fee_per_coin(price: float, inp: PlannerInput, *, is_entry: bool, exit_at_tp: bool = False) -> float:
    return price * (_rate(inp, is_entry=is_entry, exit_at_tp=exit_at_tp) + inp.fees.slippage)


def loss_per_coin_at_sl(inp: PlannerInput) -> float:
    """Total $ loss per coin if stopped (distance + round-trip fees at SL)."""
    dist = _sl_distance(inp)
    if dist <= 0:
        return float("inf")
    return dist + fee_per_coin(inp.entry, inp, is_entry=True) + fee_per_coin(inp.stop_loss, inp, is_entry=False)


def profit_per_coin_at_tp(inp: PlannerInput, tp: float) -> float:
    if inp.direction == "LONG":
        gross = tp - inp.entry
    else:
        gross = inp.entry - tp
    return gross - fee_per_coin(inp.entry, inp, is_entry=True) - fee_per_coin(tp, inp, is_entry=False, exit_at_tp=True)


def position_size(inp: PlannerInput) -> dict:
    dist = _sl_distance(inp)
    risk_usd = inp.balance_usdt * (inp.risk_pct / 100.0)
    loss_pc = loss_per_coin_at_sl(inp)
    out: dict = {
        "risk_usd": risk_usd,
        "sl_distance": dist,
        "sl_distance_pct": 100.0 * dist / inp.entry if inp.entry else 0.0,
        "loss_per_coin_at_sl": loss_pc,
        "coins": 0.0,
        "notional_usdt": 0.0,
        "loss_if_sl_usdt": 0.0,
        "below_min_notional": False,
        "below_min_qty": False,
    }
    if dist <= 0 or inp.entry <= 0 or not math.isfinite(loss_pc) or loss_pc <= 0:
        out["error"] = "invalid entry/SL"
        return out
    coins = risk_usd / loss_pc
    step = Decimal(str(inp.step_size))
    q = (Decimal(str(coins)) / step).to_integral_value(rounding=ROUND_DOWN)
    coins_r = float(q * step)
    notional = coins_r * inp.entry
    out["coins"] = coins_r
    out["notional_usdt"] = notional
    out["loss_if_sl_usdt"] = coins_r * loss_pc
    out["below_min_notional"] = notional < inp.min_notional and coins_r > 0
    out["below_min_qty"] = coins_r <= 0
    return out


def required_margin(notional: float, leverage: float) -> float:
    if leverage <= 0:
        return float("inf")
    return notional / leverage


def liquidation_approx(inp: PlannerInput) -> float | None:
    lev = inp.leverage
    mm = inp.maint_margin_rate
    if inp.entry <= 0 or lev <= 0:
        return None
    if inp.direction == "LONG":
        return inp.entry * (1.0 - 1.0 / lev + mm)
    return inp.entry * (1.0 + 1.0 / lev - mm)


def fees_in_r(inp: PlannerInput, coins: float) -> dict:
    dist = _sl_distance(inp)
    if dist <= 0 or coins <= 0:
        return {"entry_usdt": 0.0, "exit_usdt": 0.0, "round_trip_usdt": 0.0, "round_trip_r": 0.0}
    entry_fee = fee_per_coin(inp.entry, inp, is_entry=True) * coins
    exit_fee = fee_per_coin(inp.stop_loss, inp, is_entry=False) * coins
    rt = entry_fee + exit_fee
    rt_r = rt / (coins * dist)
    return {
        "entry_usdt": entry_fee,
        "exit_usdt": exit_fee,
        "round_trip_usdt": rt,
        "round_trip_r": rt_r,
    }


def gross_r(inp: PlannerInput, tp: float) -> float:
    dist = _sl_distance(inp)
    if dist <= 0:
        return 0.0
    if inp.direction == "LONG":
        return (tp - inp.entry) / dist
    return (inp.entry - tp) / dist


def tp_analysis(inp: PlannerInput, coins: float) -> list[dict]:
    rows = []
    dist = _sl_distance(inp)
    for label, tp in (("TP1", inp.tp1), ("TP2", inp.tp2), ("TP3", inp.tp3)):
        if tp is None or not math.isfinite(tp):
            continue
        prof = profit_per_coin_at_tp(inp, tp) * coins
        g = gross_r(inp, tp)
        n = prof / (coins * dist) if coins > 0 and dist > 0 else 0.0
        rows.append({"tp": label, "price": tp, "gross_r": g, "net_r": n, "profit_usdt": prof})
    return rows


def sl_atr_multiple(inp: PlannerInput) -> float | None:
    if not inp.atr or inp.atr <= 0:
        return None
    return _sl_distance(inp) / inp.atr


def build_plan(inp: PlannerInput) -> dict:
    pos = position_size(inp)
    coins = float(pos.get("coins", 0))
    margin = required_margin(float(pos.get("notional_usdt", 0)), inp.leverage)
    liq = liquidation_approx(inp)
    fee = fees_in_r(inp, coins)
    tps = tp_analysis(inp, coins)
    sl_atr = sl_atr_multiple(inp)
    sl_dist = _sl_distance(inp)
    warnings: list[str] = []
    if inp.risk_pct > 1.0:
        warnings.append(f"Risk {inp.risk_pct:.2f}% is above 1% — consider sizing down.")
    if inp.risk_pct > 3.0:
        warnings.append("Risk exceeds 3% hard guidance.")
    if fee["round_trip_r"] > 0.20:
        warnings.append("Fees eat >20% of 1R — widen SL or skip.")
    if margin > inp.balance_usdt:
        warnings.append("Required margin exceeds balance — cannot open; reduce size or raise leverage carefully.")
    if inp.leverage > 10:
        warnings.append("Leverage above 10× — high liquidation risk.")
    if liq is not None and sl_dist > 0:
        liq_dist = abs(inp.entry - liq)
        if liq_dist < 1.5 * sl_dist:
            warnings.append("Liquidation nearer than 1.5× SL distance (approx).")
    if sl_atr is not None and sl_atr < 0.6:
        warnings.append(f"SL is {sl_atr:.2f}×ATR — likely noise stop")
    return {
        "position": pos,
        "margin_usdt": margin,
        "liquidation_approx": liq,
        "fees": fee,
        "targets": tps,
        "sl_atr_mult": sl_atr,
        "warnings": warnings,
    }


def format_mexc_plan(symbol_display: str, inp: PlannerInput, plan: dict) -> str:
    pos = plan["position"]
    lines = [
        f"{symbol_display} {inp.direction}",
        f"Entry {inp.entry} ({inp.entry_type})",
        f"SL {inp.stop_loss}",
    ]
    for t in plan["targets"]:
        lines.append(f"{t['tp']} {t['price']:.8g} (net {t['net_r']:.2f}R, ~{t['profit_usdt']:.2f} USDT)")
    lines.append(f"Size {pos['coins']} coins (~{pos['notional_usdt']:.2f} USDT)")
    lines.append(f"Risk budget {inp.risk_pct}% = {pos['risk_usd']:.2f} USDT incl. fees at SL")
    lines.append(f"Loss if SL hit ~{pos['loss_if_sl_usdt']:.2f} USDT")
    lines.append(f"Margin ~{plan['margin_usdt']:.2f} USDT @ {inp.leverage}x")
    return "\n".join(lines)