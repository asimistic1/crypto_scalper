from core.pattern_stats import aggregate_warning, strategy_warning


def test_btc_15m_aggregate_from_reports():
    msg = aggregate_warning("BTCUSDT", "15m")
    assert msg is not None
    assert "TP1 hit" in msg
    assert "Phase 3.4" in msg


def test_strategy_warning_or_untested():
    w = strategy_warning("BTCUSDT", "15m", "trend_pullback")
    assert "Not a tested edge" in w or w == "Untested"
    assert strategy_warning("FOOUSDT", "15m", "trend_pullback") == "Untested"