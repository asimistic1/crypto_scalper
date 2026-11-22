"""Price alerts — SQLite, max 50 active."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

ALERTS_PATH = Path(__file__).resolve().parents[1] / "data" / "alerts.db"
MAX_ALERTS = 50


@dataclass
class Alert:
    id: int | None
    symbol: str
    alert_type: str
    price: float
    zone_low: float | None
    zone_high: float | None
    active: int
    created_at: str
    triggered_at: str | None = None


def _conn() -> sqlite3.Connection:
    ALERTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(ALERTS_PATH)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            alert_type TEXT NOT NULL,
            price REAL NOT NULL,
            zone_low REAL,
            zone_high REAL,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            triggered_at TEXT
        )
        """
    )
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS alert_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_id INTEGER,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    return c


def active_count() -> int:
    with _conn() as conn:
        return int(conn.execute("SELECT COUNT(*) FROM alerts WHERE active=1").fetchone()[0])


def create_alert(symbol: str, alert_type: str, price: float, **zone) -> int:
    if active_count() >= MAX_ALERTS:
        raise ValueError("Maximum 50 active alerts")
    if price <= 0:
        raise ValueError("Invalid price")
    with _conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO alerts(symbol, alert_type, price, zone_low, zone_high, active, created_at)
            VALUES (?,?,?,?,?,1,?)
            """,
            (
                symbol[:20],
                alert_type[:32],
                float(price),
                zone.get("zone_low"),
                zone.get("zone_high"),
                datetime.now(UTC).isoformat(),
            ),
        )
        return int(cur.lastrowid)


def list_active(symbol: str | None = None) -> list[dict]:
    with _conn() as conn:
        if symbol:
            rows = conn.execute(
                "SELECT * FROM alerts WHERE active=1 AND symbol=? ORDER BY id DESC",
                (symbol,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM alerts WHERE active=1 ORDER BY id DESC").fetchall()
    cols = ["id", "symbol", "alert_type", "price", "zone_low", "zone_high", "active", "created_at", "triggered_at"]
    return [dict(zip(cols, r, strict=False)) for r in rows]


def evaluate_alerts(symbol: str, price: float) -> list[str]:
    """Return messages for alerts that fire; deactivates one-shot crosses."""
    fired: list[str] = []
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, alert_type, price, zone_low, zone_high FROM alerts WHERE active=1 AND symbol=?",
            (symbol,),
        ).fetchall()
        for aid, atype, level, zlo, zhi in rows:
            hit = False
            if atype == "cross_above" and price >= level:
                hit = True
            elif atype == "cross_below" and price <= level:
                hit = True
            elif atype == "in_zone" and zlo is not None and zhi is not None:
                hit = zlo <= price <= zhi
            if hit:
                msg = f"{symbol} alert {atype} @ {price:.4g} (target {level})"
                fired.append(msg)
                conn.execute(
                    "UPDATE alerts SET active=0, triggered_at=? WHERE id=?",
                    (datetime.now(UTC).isoformat(), aid),
                )
                conn.execute(
                    "INSERT INTO alert_history(alert_id, message, created_at) VALUES (?,?,?)",
                    (aid, msg, datetime.now(UTC).isoformat()),
                )
    return fired