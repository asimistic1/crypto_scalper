import pytest

from core import alerts as A


@pytest.fixture()
def alerts_db(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "ALERTS_PATH", tmp_path / "alerts.db")
    return tmp_path


def test_alert_evaluate(alerts_db):
    aid = A.create_alert("BTCUSDT", "cross_above", 100.0)
    assert aid > 0
    assert not A.evaluate_alerts("BTCUSDT", 99.0)
    fired = A.evaluate_alerts("BTCUSDT", 101.0)
    assert fired
    assert A.active_count() == 0


def test_alert_limit(alerts_db):
    for i in range(A.MAX_ALERTS):
        A.create_alert("ETHUSDT", "cross_below", float(i + 1))
    with pytest.raises(ValueError):
        A.create_alert("ETHUSDT", "cross_below", 999.0)