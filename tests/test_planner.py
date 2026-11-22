from core.planner import FeeConfig, PlannerInput, build_plan, loss_per_coin_at_sl, position_size, snap_price


def test_snap_and_fee_inclusive_size():
    inp = PlannerInput(
        direction="LONG",
        entry=100.0,
        stop_loss=98.0,
        balance_usdt=1000,
        risk_pct=1.0,
        leverage=10,
        step_size=0.001,
        tick_size=0.1,
        fees=FeeConfig(),
    )
    loss_pc = loss_per_coin_at_sl(inp)
    assert loss_pc > 2.0
    pos = position_size(inp)
    assert pos["coins"] > 0
    assert abs(pos["loss_if_sl_usdt"] - pos["risk_usd"]) < pos["risk_usd"] * 0.15
    assert snap_price(100.23, 0.1, toward="down") == 100.2


def test_margin_and_leverage_warnings():
    inp = PlannerInput(
        direction="LONG",
        entry=100,
        stop_loss=99,
        balance_usdt=50,
        risk_pct=2.0,
        leverage=50,
        tp1=101,
        fees=FeeConfig(),
        maint_margin_rate=0.004,
        atr=2.0,
    )
    plan = build_plan(inp)
    joined = " ".join(plan["warnings"])
    assert "margin" in joined.lower() or "Leverage" in joined


def test_liquidation_warning_vs_sl():
    inp = PlannerInput(
        direction="LONG",
        entry=100,
        stop_loss=95,
        balance_usdt=5000,
        risk_pct=0.5,
        leverage=50,
        fees=FeeConfig(),
        maint_margin_rate=0.004,
        atr=2.0,
    )
    plan = build_plan(inp)
    assert any("1.5" in w for w in plan["warnings"])