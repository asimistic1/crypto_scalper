"""User settings — SQLite validated storage."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

SETTINGS_PATH = Path(__file__).resolve().parents[1] / "data" / "settings.db"

DEFAULTS = {
    "fee_maker": 0.0001,
    "fee_taker": 0.0004,
    "default_risk_pct": 0.5,
    "account_balance": 1000.0,
    "maint_margin_rate": 0.004,
    "timezone": "Asia/Karachi",
    "watchlist": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"],
}


def _connect() -> sqlite3.Connection:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(SETTINGS_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    return conn


def load_settings() -> dict:
    with _connect() as conn:
        rows = conn.execute("SELECT key, value FROM kv").fetchall()
    out = dict(DEFAULTS)
    for k, v in rows:
        try:
            out[k] = json.loads(v)
        except json.JSONDecodeError:
            out[k] = v
    return out


def save_settings(updates: dict) -> None:
    with _connect() as conn:
        for k, v in updates.items():
            if k not in DEFAULTS and k != "watchlist":
                continue
            conn.execute(
                "INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (k, json.dumps(v)),
            )