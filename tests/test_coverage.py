"""Coverage FAIL on constant features."""

from research.coverage import coverage_rows, MIN_UNIQUE, MIN_NON_NULL
import pandas as pd
import pytest


def test_constant_feature_fails_is():
    df = pd.DataFrame(
        {
            "close_time": range(100),
            "sample": ["IS"] * 100,
            "open_interest": [1.0] * 100,
        }
    )
    rows, fails = coverage_rows("BTCUSDT", df, ["open_interest"], "IS")
    assert rows[0]["status"] == "FAIL"
    assert fails
    assert rows[0]["n_unique"] < MIN_UNIQUE


def test_good_feature_passes():
    df = pd.DataFrame(
        {
            "close_time": range(100),
            "sample": ["IS"] * 100,
            "open_interest": list(range(100)),
        }
    )
    rows, fails = coverage_rows("BTCUSDT", df, ["open_interest"], "IS")
    assert rows[0]["status"] == "PASS"
    assert rows[0]["non_null_pct"] >= MIN_NON_NULL