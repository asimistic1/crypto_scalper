"""Phase 4 training dataset rows (features at signal only — no labels from future)."""

from __future__ import annotations

from datetime import UTC
from zoneinfo import ZoneInfo

import pandas as pd

from backtest.history import as_of_from_close_ms, ensure_indicators, quote_volume_24h_at
from backtest.history_cache import get_ohlc

PK = ZoneInfo("Asia/Karachi")


def feature_row(
    symbol: str,
    tf: str,
    bar_index: int,
    signal_row: pd.Series,
    labels: dict,
    htf_summary: dict[str, str] | None = None,
) -> dict:
    t = signal_row["time"]
    if hasattr(t, "to_pydatetime"):
        t = t.to_pydatetime()
    if t.tzinfo is None:
        t = t.replace(tzinfo=UTC)
    pk = t.astimezone(PK)
    atr = float(signal_row.get("atr_14") or 0)
    close = float(signal_row["close"])
    atr_pct = 100.0 * atr / close if close else 0.0
    htf_summary = htf_summary or {}
    return {
        "symbol": symbol,
        "timeframe": tf,
        "bar_index": bar_index,
        "close_time": int(signal_row["close_time"]),
        "direction": labels.get("direction"),
        "strategy": labels.get("strategy"),
        "score": float(labels.get("score") or 0),
        "rsi_14": float(signal_row.get("rsi_14") or 0),
        "volume_ratio": float(signal_row.get("volume_ratio") or 0),
        "atr_pct": atr_pct,
        "ema21_dist_atr": (
            (close - float(signal_row["ema_21"])) / atr if atr and pd.notna(signal_row.get("ema_21")) else 0.0
        ),
        "hour_pkt": pk.hour,
        "weekday": pk.weekday(),
        **{f"htf_{k}": v for k, v in htf_summary.items()},
        "filled": bool(labels.get("filled")),
        "outcome": labels.get("outcome"),
        "tp1_before_sl": bool(labels.get("tp1_before_sl"))
        if labels.get("tp1_before_sl") is not None
        else labels.get("outcome") in ("TP1", "TP2", "TP3"),
        "net_r": float(labels.get("r_net") or 0),
    }


def build_dataset(signals: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
    if signals.empty:
        return pd.DataFrame()
    rows: list[dict] = []
    trade_map = trades.set_index("setup_id").to_dict("index") if not trades.empty else {}
    ind_cache: dict[tuple[str, str], pd.DataFrame] = {}
    for _, sig in signals.iterrows():
        sym = str(sig["symbol"])
        tf = str(sig["timeframe"])
        key = (sym, tf)
        if key not in ind_cache:
            ind_cache[key] = ensure_indicators(get_ohlc(sym, tf).df)
        df = ind_cache[key]
        bi = int(sig["bar_index"])
        bar = df.iloc[bi]
        as_of = as_of_from_close_ms(int(bar["close_time"]))
        labels = dict(sig)
        tid = str(sig.get("setup_id", ""))
        if tid in trade_map:
            labels.update(trade_map[tid])
        row = feature_row(sym, tf, bi, bar, labels)
        row["quote_volume_24h"] = quote_volume_24h_at(df, as_of)
        rows.append(row)
    return pd.DataFrame(rows)