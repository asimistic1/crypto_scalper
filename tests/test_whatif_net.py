"""What-if net R uses scenario SL distance for fee denominator."""

from backtest.config import BacktestConfig
from backtest.costs import net_r_from_gross


def test_wider_sl_lowers_fee_in_r():
    cfg = BacktestConfig()
    gross = 0.5
    entry = 100_000.0
    exit_p = 100_500.0
    narrow = 200.0
    wide = 400.0
    net_narrow = net_r_from_gross(gross, entry, exit_p, narrow, "LONG", "MARKET", cfg)
    net_wide = net_r_from_gross(gross, entry, exit_p, wide, "LONG", "MARKET", cfg)
    assert net_wide > net_narrow