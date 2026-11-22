"""Which features may enter IS rule selection (stationarity policy)."""

from __future__ import annotations

# Non-stationary levels / raw price-linked scales — IC on these is not actionable.
NON_STATIONARY_FOR_SELECTION = frozenset(
    {
        "open_interest",
        "open_interest_value",
        "top_trader_ls_ratio",
        "global_ls_ratio",
        "taker_ls_vol_ratio",
    }
)

SELECTION_RULE_MD = """
## Feature eligibility (Phase 3.5c+)

**Excluded from selection** (levels / raw OI / raw positioning ratios):
`open_interest`, `open_interest_value`, `top_trader_ls_ratio`, `global_ls_ratio`, `taker_ls_vol_ratio`.

**Eligible**: percent changes (`oi_chg_*`), z-scores (`*_z24`, `*_z72`, `funding_z_30d`),
bounded ratios (`taker_buy_ratio*`, `basis_pct`, `spot_fut_basis_pct`), flags (`above_ema*`, `price_*_oi_*`),
flow deltas, setup score flags, ATR/vol features.
""".strip()


def is_selection_eligible(feature: str) -> bool:
    if feature in NON_STATIONARY_FOR_SELECTION:
        return False
    return True