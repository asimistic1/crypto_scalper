import numpy as np
import pandas as pd
import pytest

from backtest.paths import history_parquet
from core.idea_tester import (
    RuleSpec,
    _exit_bar,
    build_mask,
    max_drawdown_r,
    run_idea_test,
    rule_hash,
)


def test_rule_hash_stable():
    spec = RuleSpec("BTCUSDT", "15m", [{"left": "rsi_14", "op": "<", "right": "30"}], [], 1.5, 1.0, 8, True)
    assert rule_hash(spec) == rule_hash(spec)


def test_build_mask_empty_conditions():
    df = pd.DataFrame({"rsi_14": [25, 45]})
    assert not build_mask(df, []).any()


def test_max_drawdown_peak_trough():
    r = pd.Series([1.0, 1.0, -3.0, 0.5])
    assert max_drawdown_r(r) == -3.0


def test_exit_bar_gap_sl_before_tp():
    df = pd.DataFrame(
        {
            "open": [100.0, 98.0, 99.0],
            "high": [101.0, 100.0, 100.0],
            "low": [99.0, 97.0, 98.0],
            "close": [100.0, 98.0, 99.0],
        }
    )
    px, out, j = _exit_bar(df, 1, "LONG", 98.0, 99.0, 102.0, 2)
    assert out == "SL"
    assert px == 98.0


@pytest.mark.slow
@pytest.mark.skipif(
    not history_parquet("BTCUSDT", "15m").exists(),
    reason="missing BTCUSDT 15m parquet",
)
def test_is_result_has_no_oos_keys():
    spec = RuleSpec(
        "BTCUSDT",
        "15m",
        [{"left": "rsi_14", "op": "<", "right": "99"}],
        [],
        1.5,
        1.0,
        8,
        True,
    )
    res = run_idea_test(spec, phase="IS", use_cache=False)
    assert "OOS" not in res
    assert "verdict" not in res
    assert "IS" in res