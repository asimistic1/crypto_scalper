from core.idea_tester import RuleSpec, build_mask, rule_hash


def test_rule_hash_stable():
    spec = RuleSpec("BTCUSDT", "15m", "LONG", [{"left": "rsi_14", "op": "<", "right": "30"}], 1.5, 1.0, 8, True)
    assert rule_hash(spec) == rule_hash(spec)


def test_build_mask_empty_conditions():
    import pandas as pd

    df = pd.DataFrame({"rsi_14": [25, 45]})
    mask = build_mask(df, [])
    assert mask.all()