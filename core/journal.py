"""Trade journal — SQLite WAL, validated CRUD."""

from __future__ import annotations

import csv
import io
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

JOURNAL_PATH = Path(__file__).resolve().parents[1] / "data" / "journal.db"
MAX_TEXT = 1000


@dataclass
class JournalEntry:
    id: int | None
    symbol: str
    timeframe: str
    direction: str
    planned_entry: float
    planned_sl: float
    planned_tp1: float | None
    planned_tp2: float | None
    planned_tp3: float | None
    size_coins: float
    risk_pct: float
    reason: str
    checklist: str
    created_at: str
    actual_entry: float | None = None
    exit_price: float | None = None
    exit_time: str | None = None
    fees_paid: float | None = None
    outcome_r: float | None = None
    notes: str = ""
    emotion: str = ""
    followed_plan: int | None = None


def _connect() -> sqlite3.Connection:
    JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(JOURNAL_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_journal_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                direction TEXT NOT NULL,
                planned_entry REAL NOT NULL,
                planned_sl REAL NOT NULL,
                planned_tp1 REAL,
                planned_tp2 REAL,
                planned_tp3 REAL,
                size_coins REAL NOT NULL,
                risk_pct REAL NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                checklist TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                actual_entry REAL,
                exit_price REAL,
                exit_time TEXT,
                fees_paid REAL,
                outcome_r REAL,
                notes TEXT NOT NULL DEFAULT '',
                emotion TEXT NOT NULL DEFAULT '',
                followed_plan INTEGER
            )
            """
        )


def _clip(text: str, limit: int = MAX_TEXT) -> str:
    return (text or "")[:limit]


def insert_trade(entry: JournalEntry) -> int:
    init_journal_db()
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO trades (
              symbol, timeframe, direction, planned_entry, planned_sl,
              planned_tp1, planned_tp2, planned_tp3, size_coins, risk_pct,
              reason, checklist, created_at, notes, emotion
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                entry.symbol[:20],
                entry.timeframe[:8],
                entry.direction[:10],
                entry.planned_entry,
                entry.planned_sl,
                entry.planned_tp1,
                entry.planned_tp2,
                entry.planned_tp3,
                entry.size_coins,
                entry.risk_pct,
                _clip(entry.reason),
                _clip(entry.checklist, 500),
                entry.created_at,
                _clip(entry.notes),
                _clip(entry.emotion, 32),
            ),
        )
        return int(cur.lastrowid)


def update_trade(trade_id: int, **fields: Any) -> None:
    allowed = {
        "actual_entry",
        "exit_price",
        "exit_time",
        "fees_paid",
        "outcome_r",
        "notes",
        "emotion",
        "followed_plan",
    }
    parts = []
    vals: list[Any] = []
    for k, v in fields.items():
        if k not in allowed:
            continue
        if k in ("notes",):
            v = _clip(str(v))
        parts.append(f"{k}=?")
        vals.append(v)
    if not parts:
        return
    vals.append(trade_id)
    with _connect() as conn:
        conn.execute(f"UPDATE trades SET {', '.join(parts)} WHERE id=?", vals)


def list_trades(limit: int = 500) -> list[dict]:
    init_journal_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM trades ORDER BY id DESC LIMIT ?",
            (min(limit, 5000),),
        ).fetchall()
    return [dict(r) for r in rows]


def stats_summary() -> dict[str, float]:
    trades = [t for t in list_trades() if t.get("outcome_r") is not None]
    if not trades:
        return {"count": 0}
    rs = [float(t["outcome_r"]) for t in trades]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for r in rs:
        equity += r
        peak = max(peak, equity)
        max_dd = min(max_dd, equity - peak)
    gross_w = sum(wins)
    gross_l = abs(sum(losses)) or 1e-9
    return {
        "count": len(rs),
        "win_rate": len(wins) / len(rs),
        "avg_r": sum(rs) / len(rs),
        "profit_factor": gross_w / gross_l,
        "max_dd_r": max_dd,
    }


def export_csv() -> str:
    buf = io.StringIO()
    rows = list_trades()
    if not rows:
        return ""
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def import_csv(text: str) -> int:
    reader = csv.DictReader(io.StringIO(text))
    n = 0
    for row in reader:
        try:
            insert_trade(
                JournalEntry(
                    id=None,
                    symbol=row["symbol"],
                    timeframe=row["timeframe"],
                    direction=row["direction"],
                    planned_entry=float(row["planned_entry"]),
                    planned_sl=float(row["planned_sl"]),
                    planned_tp1=float(row["planned_tp1"]) if row.get("planned_tp1") else None,
                    planned_tp2=float(row["planned_tp2"]) if row.get("planned_tp2") else None,
                    planned_tp3=float(row["planned_tp3"]) if row.get("planned_tp3") else None,
                    size_coins=float(row["size_coins"]),
                    risk_pct=float(row["risk_pct"]),
                    reason=row.get("reason", ""),
                    checklist=row.get("checklist", ""),
                    created_at=row.get("created_at") or datetime.now(UTC).isoformat(),
                )
            )
            n += 1
        except (KeyError, ValueError):
            continue
    return n