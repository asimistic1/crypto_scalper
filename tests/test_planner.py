from core.planner import FeeConfig, PlannerInput, build_plan, position_size, snap_price


def test_snap_and_position_round_down():
    inp = PlannerInput(
        direction="LONG",
        entry=100.0,
        stop_loss=98.0,
        balance_usdt=1000,
        risk_pct=1.0,
        leverage=10,
        step_size=0.001,
        tick_size=0.1,
    )
    pos = position_size(inp)
    assert pos["coins"] == round(pos["coins"], 3)
    assert pos["risk_usd"] == 10.0
    assert snap_price(100.23, 0.1, toward="down") == 100.2


def test_fees_and_liquidation_warning():
    inp = PlannerInput(
        direction="LONG",
        entry=100,
        stop_loss=99,
        balance_usdt=5000,
        risk_pct=0.5,
        leverage=50,
        tp1=101,
        fees=FeeConfig(),
        maint_margin_rate=0.004,
        atr=2.0,
    )
    plan = build_plan(inp)
    assert plan["fees"]["round_trip_r"] > 0
    assert plan["sl_atr_mult"] == 0.5