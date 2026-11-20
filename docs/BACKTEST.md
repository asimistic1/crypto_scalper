# Phase 3 — Honest backtesting

## Download history

```bash
python -m backtest.data_download --symbols BTCUSDT,ETHUSDT --intervals 5m,15m,1h,4h,1d --months 24
```

- Source: [data.binance.vision](https://data.binance.vision) (checksum verified).
- Gap fill after the latest daily file uses REST `/fapi/v1/klines` (weight budget + cooldown).
- Output: `data/history/{SYMBOL}/{interval}.parquet`

## Run backtest

```bash
python -m backtest.run --symbols BTCUSDT,ETHUSDT,SOLUSDT --tfs 5m,15m,1h --exit-models tp1_full,partial_be
```

Outputs under `data/backtest/runs/{run_id}/`: `trades.parquet`, `summary.json`, score calibration CSVs.

Signals are cached in `data/backtest/signals/` (hash of data + git commit).

## Assumptions (conservative by default)

| Topic | Rule |
|--------|------|
| Signals | `core.setup_builder.build_setup` only (no duplicated logic) |
| Entry | MARKET → next bar open ± slippage; LIMIT → trade through level, expire in `SETUP_EXPIRY_CANDLES` |
| Same-bar SL vs TP | SL first unless `--intrabar 1m` (Step 4 optional data) |
| Gaps | Exit at open if beyond SL |
| Fees | `fee_model=conservative` → taker + slippage everywhere |
| Look-ahead | Slices at `as_of = close_time` of signal bar only |

## Dashboard

Streamlit multipage: **Backtest** (`pages/2_Backtest.py`) — reads Parquet only, no network.

## Honesty checks

- Random-entry Monte Carlo baseline (OOS percentile)
- Score bucket win rate + Wilson CI + Spearman vs net R
- Cost sensitivity ×1.5 and ×2.0
- Monte Carlo max drawdown (95th percentile)
- “Too good” alarm if OOS win rate > 75% or PF > 3 (≥100 trades)