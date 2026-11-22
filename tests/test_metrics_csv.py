"""Metrics CSV parsing from Binance Vision layout."""

from backtest.data_download import _parse_metrics_csv

SAMPLE = (
    b"create_time,symbol,sum_open_interest,sum_open_interest_value,"
    b"count_toptrader_long_short_ratio,sum_toptrader_long_short_ratio,"
    b"count_long_short_ratio,sum_taker_long_short_vol_ratio\n"
    b"2024-11-01 00:00:00,BTCUSDT,1.0,100.0,1.1,1.2,0.9,1.0\n"
)


def test_parse_metrics_columns():
    df = _parse_metrics_csv(SAMPLE)
    assert "open_interest" in df.columns
    assert "taker_ls_vol_ratio" in df.columns
    assert len(df) == 1