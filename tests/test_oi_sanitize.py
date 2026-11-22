"""open_interest sanitization and safe oi_chg_* (no inf / bogus -1 from div-by-zero)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from research.features import _safe_pct_change_n, _sanitize_oi_levels


def test_sanitize_oi_zero_and_missing_to_nan():
    met = pd.DataFrame(
        {
            "open_interest": [100.0, 0.0, np.nan, 50.0],
            "open_interest_value": [1e6, -1.0, 0.0, 2e6],
        }
    )
    out = _sanitize_oi_levels(met)
    assert out.loc[0, "open_interest"] == 100.0
    assert np.isnan(out.loc[1, "open_interest"])
    assert np.isnan(out.loc[2, "open_interest"])
    assert out.loc[3, "open_interest_value"] == 2e6
    assert np.isnan(out.loc[1, "open_interest_value"])
    assert np.isnan(out.loc[2, "open_interest_value"])


def test_safe_pct_change_no_inf_or_minus_one_from_zero():
    oi = pd.Series([np.nan, 0.0, 100.0, 100.0, 200.0, 50.0])
    chg = _safe_pct_change_n(oi, 1)
    assert chg.isna().all() or chg.dropna().apply(np.isfinite).all()
    assert not np.isinf(chg.fillna(0)).any()
    assert chg.iloc[4] == 1.0  # 200 vs 100
    assert chg.iloc[5] == -0.75  # 50 vs prior 200
    assert chg.iloc[3] == 0.0  # 100 vs 100