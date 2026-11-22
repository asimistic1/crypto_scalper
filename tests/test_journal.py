import tempfile
from pathlib import Path

import pytest

from core import journal as J


@pytest.fixture()
def journal_db(tmp_path, monkeypatch):
    p = tmp_path / "journal.db"
    monkeypatch.setattr(J, "JOURNAL_PATH", p)
    J.init_journal_db()
    return p


def test_journal_crud(journal_db):
    e = J.JournalEntry(
        id=None,
        symbol="BTCUSDT",
        timeframe="15m",
        direction="LONG",
        planned_entry=1.0,
        planned_sl=0.9,
        planned_tp1=1.1,
        planned_tp2=None,
        planned_tp3=None,
        size_coins=0.01,
        risk_pct=0.5,
        reason="test",
        checklist="trend",
        created_at="2026-01-01T00:00:00+00:00",
    )
    tid = J.insert_trade(e)
    J.update_trade(tid, outcome_r=1.2, emotion="calm")
    rows = J.list_trades()
    assert rows[0]["id"] == tid
    assert rows[0]["outcome_r"] == 1.2
    assert J.stats_summary()["count"] == 1