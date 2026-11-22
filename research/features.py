"""Lag-safe feature table for edge research (1h primary, 15m taker flow)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.config import BacktestConfig
from backtest.history import ensure_indicators, load_history
from backtest.paths import SIGNALS_DIR, symbol_aux_parquet
from research.aux_data import load_funding, load_metrics_5m, merge_asof_features

DERIVATIVES_FEATURES = frozenset(
    {
        "open_interest",
        "open_interest_value",
        "oi_chg_1h",
        "oi_chg_4h",
        "oi_chg_24h",
        "top_trader_ls_ratio",
        "global_ls_ratio",
        "taker_ls_vol_ratio",
        "top_trader_ls_ratio_z72",
        "global_ls_ratio_z72",
        "taker_ls_vol_ratio_z72",
        "funding_rate",
        "funding_z_30d",
        "basis_pct",
        "basis_z72",
        "spot_fut_basis_pct",
        "spot_fut_basis_z72",
    }
)


def _zscore(s: pd.Series, window: int) -> pd.Series:
    m = s.rolling(window, min_periods=max(5, window // 4)).mean()
    sd = s.rolling(window, min_periods=max(5, window // 4)).std()
    return (s - m) / sd.replace(0, np.nan)


def _load_signals_1h(symbol: str) -> pd.DataFrame:
    path = SIGNALS_DIR / f"{symbol.upper()}_1h.parquet"
    if not path.exists():
        return pd.DataFrame()
    sig = pd.read_parquet(path)
    sig = sig.sort_values("close_time")
    grp = sig.groupby("close_time", as_index=False).agg(
        setup_score=("score", "max"),
        has_breakout=("strategy", lambda s: int((s == "breakout_retest").any())),
        has_pullback=("strategy", lambda s: int((s == "trend_pullback").any())),
    )
    return grp


def _asof_numeric(left: pd.DataFrame, right: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    merged = merge_asof_features(left, right, cols)
    return merged.sort_values("close_time").reset_index(drop=True)


def build_feature_table(
    symbol: str,
    *,
    cfg: BacktestConfig | None = None,
) -> pd.DataFrame:
    """One row per 1h bar (futures); features known at bar close."""
    cfg = cfg or BacktestConfig()
    sym = symbol.upper()
    h1 = ensure_indicators(load_history(sym, "1h"))
    h4 = ensure_indicators(load_history(sym, "4h"))
    m15 = ensure_indicators(load_history(sym, "15m"))

    base = h1[
        ["time", "close_time", "open", "high", "low", "close", "volume", "quote_volume", "taker_buy_quote_volume"]
    ].copy()
    qv = base["quote_volume"].replace(0, np.nan)
    base["taker_buy_ratio"] = base["taker_buy_quote_volume"] / qv
    base["taker_buy_ratio_z24"] = _zscore(base["taker_buy_ratio"], 24)
    base["taker_buy_ratio_z72"] = _zscore(base["taker_buy_ratio"], 72)
    base["taker_delta_4h"] = base["taker_buy_quote_volume"].rolling(4).sum() - (
        base["quote_volume"].rolling(4).sum() - base["taker_buy_quote_volume"].rolling(4).sum()
    )
    base["taker_delta_12h"] = base["taker_buy_quote_volume"].rolling(12).sum() - (
        base["quote_volume"].rolling(12).sum() - base["taker_buy_quote_volume"].rolling(12).sum()
    )
    base["taker_delta_24h"] = base["taker_buy_quote_volume"].rolling(24).sum() - (
        base["quote_volume"].rolling(24).sum() - base["taker_buy_quote_volume"].rolling(24).sum()
    )

    # 15m taker flow merged to 1h (last 15m bar in each hour)
    m15 = m15.sort_values("close_time")
    m15["taker_buy_ratio_15m"] = m15["taker_buy_quote_volume"] / m15["quote_volume"].replace(0, np.nan)
    m15["hour_bucket"] = (m15["close_time"] // 3_600_000) * 3_600_000 + 3_599_999
    m15_h = m15.groupby("hour_bucket", as_index=False).last()[["hour_bucket", "taker_buy_ratio_15m"]]
    m15_h = m15_h.rename(columns={"hour_bucket": "close_time"})
    base = base.merge(m15_h, on="close_time", how="left")
    base["taker_buy_ratio_15m_z24"] = _zscore(base["taker_buy_ratio_15m"], 24)

    close = base["close"].to_numpy(dtype=float)
    base["ema50_1h"] = h1["ema_50"].to_numpy() if "ema_50" in h1.columns else np.nan
    base["ema200_1h"] = h1["ema_200"].to_numpy()
    base["above_ema50_1h"] = (close > base["ema50_1h"]).astype(float)
    base["above_ema200_1h"] = (close > base["ema200_1h"]).astype(float)
    h4 = h4[["close_time", "close", "ema_50", "ema_200"]].rename(
        columns={"close": "close_4h", "ema_50": "ema50_4h", "ema_200": "ema200_4h"}
    )
    base = _asof_numeric(base, h4, ["close_4h", "ema50_4h", "ema200_4h"])
    base["above_ema50_4h"] = (base["close_4h"] > base["ema50_4h"]).astype(float)
    base["above_ema200_4h"] = (base["close_4h"] > base["ema200_4h"]).astype(float)

    if "atr_14" in h1.columns:
        base["atr_pct"] = 100.0 * h1["atr_14"].to_numpy() / close
    base["realized_vol_24h"] = base["close"].pct_change().rolling(24).std() * np.sqrt(24)

    ts = pd.to_datetime(base["close_time"], unit="ms", utc=True)
    base["hour_utc"] = ts.dt.hour
    base["weekday"] = ts.dt.weekday

    fund = load_funding(sym)
    if not fund.empty:
        from research.aux_data import METRICS_TOLERANCE_MS

        base = merge_asof_features(
            base, fund, ["funding_rate"], tolerance_ms=max(METRICS_TOLERANCE_MS, 8 * 3600 * 1000)
        )
        if base["funding_rate"].notna().any():
            base["funding_z_30d"] = _zscore(base["funding_rate"], 24 * 30)
            base["funding_extreme_hi"] = (
                base["funding_rate"] >= base["funding_rate"].rolling(720, min_periods=100).quantile(0.95)
            ).astype(float)
            base["funding_extreme_lo"] = (
                base["funding_rate"] <= base["funding_rate"].rolling(720, min_periods=100).quantile(0.05)
            ).astype(float)
        else:
            base["funding_z_30d"] = float("nan")
            base["funding_extreme_hi"] = float("nan")
            base["funding_extreme_lo"] = float("nan")

    met = load_metrics_5m(sym)
    if not met.empty:
        cols = [
            c
            for c in (
                "open_interest",
                "open_interest_value",
                "top_trader_ls_ratio",
                "global_ls_ratio",
                "taker_ls_vol_ratio",
            )
            if c in met.columns
        ]
        base = _asof_numeric(base, met, cols)
        oi = base["open_interest"].astype(float)
        px = base["close"].astype(float)
        base["oi_chg_1h"] = oi.pct_change(1)
        base["oi_chg_4h"] = oi.pct_change(4)
        base["oi_chg_24h"] = oi.pct_change(24)
        px_chg = px.pct_change(1)
        base["price_up_oi_up"] = ((px_chg > 0) & (base["oi_chg_1h"] > 0)).astype(float)
        base["price_up_oi_down"] = ((px_chg > 0) & (base["oi_chg_1h"] < 0)).astype(float)
        base["price_down_oi_up"] = ((px_chg < 0) & (base["oi_chg_1h"] > 0)).astype(float)
        base["price_down_oi_down"] = ((px_chg < 0) & (base["oi_chg_1h"] < 0)).astype(float)
        for c in ("top_trader_ls_ratio", "global_ls_ratio", "taker_ls_vol_ratio"):
            if c in base.columns:
                base[f"{c}_z72"] = _zscore(base[c], 72)

    prem = symbol_aux_parquet(sym, "premium_1h")
    if prem.exists():
        pr = pd.read_parquet(prem)[["close_time", "close"]].rename(columns={"close": "premium_index"})
        base = _asof_numeric(base, pr, ["premium_index"])
        base["basis_pct"] = 100.0 * (base["premium_index"] / base["close"] - 1.0)
        base["basis_z72"] = _zscore(base["basis_pct"], 72)

    spot = symbol_aux_parquet(sym, "spot_1h")
    if spot.exists():
        sp = pd.read_parquet(spot)[["close_time", "close"]].rename(columns={"close": "spot_close"})
        base = _asof_numeric(base, sp, ["spot_close"])
        base["spot_fut_basis_pct"] = 100.0 * (base["close"] / base["spot_close"] - 1.0)
        base["spot_fut_basis_z72"] = _zscore(base["spot_fut_basis_pct"], 72)

    sig = _load_signals_1h(sym)
    if not sig.empty:
        base = base.merge(sig, on="close_time", how="left")
        base["setup_score"] = base["setup_score"].fillna(0.0)
        base["has_breakout"] = base["has_breakout"].fillna(0).astype(int)
        base["has_pullback"] = base["has_pullback"].fillna(0).astype(int)
    else:
        base["setup_score"] = 0.0
        base["has_breakout"] = 0
        base["has_pullback"] = 0

    from backtest.split import tag_sample

    base = tag_sample(base, cfg, time_col="close_time")
    return base.sort_values("close_time").reset_index(drop=True)


def feature_columns(df: pd.DataFrame) -> list[str]:
    skip = {
        "time",
        "close_time",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "quote_volume",
        "taker_buy_quote_volume",
        "sample",
        "close_4h",
        "ema50_4h",
        "ema200_4h",
        "spot_close",
        "premium_index",
    }
    skip |= {c for c in df.columns if c.startswith("fwd_")}
    skip |= {"ema50_1h", "ema200_1h", "ema50_4h", "ema200_4h", "hour_utc"}
    return [c for c in df.columns if c not in skip and pd.api.types.is_numeric_dtype(df[c])]