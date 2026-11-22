# Phase 3.5c IS selection — SOLUSDT

timestamp: 2026-11-22T18:59:48.794876+00:00
commit: `4ab78204ea3b998440b0f49fa3e42b2dcbacbd91`

## Feature eligibility (Phase 3.5c+)

**Excluded from selection** (levels / raw OI / raw positioning ratios):
`open_interest`, `open_interest_value`, `top_trader_ls_ratio`, `global_ls_ratio`, `taker_ls_vol_ratio`.

**Eligible**: percent changes (`oi_chg_*`), z-scores (`*_z24`, `*_z72`, `funding_z_30d`),
bounded ratios (`taker_buy_ratio*`, `basis_pct`, `spot_fut_basis_pct`), flags (`above_ema*`, `price_*_oi_*`),
flow deltas, setup score flags, ATR/vol features.

## NO FEATURE QUALIFIES
