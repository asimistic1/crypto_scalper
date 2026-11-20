"""
SQLite signal log for trade setups (local file under data/).

One connection per thread, WAL mode, parameterized SQL only.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.models import Direction, Setup

# Default path — data/ is in .gitignore (secrets + user history stay local)
DEFAULT_DB_PATH = Path(__file__).resolve().parents[1] / "data" / "signals.db"

_local = threading.local()
_schema_ready: set[str] = set()
_schema_lock = threading.Lock()


def _now_utc() -> str:
    return datetime.now(UTC).isoformat()


def get_db_path() -> Path:
    """Override in tests via STORAGE_DB_PATH env if needed."""
    import os

    override = os.environ.get("STORAGE_DB_PATH")
    if override:
        return Path(override)
    return DEFAULT_DB_PATH


def _connect(db_path: Path) -> sqlite3.Connection:
    """
    Open (or reuse) a SQLite connection for the current thread.
    check_same_thread=False is safe because each thread keeps its own handle.
    """
    key = str(db_path.resolve())
    conn: sqlite3.Connection | None = getattr(_local, "conn", None)
    path_key: str | None = getattr(_local, "conn_path", None)
    if conn is None or path_key != key:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(key, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        _local.conn = conn
        _local.conn_path = key
    return conn


def init_db(db_path: Path | None = None) -> None:
    """Create the signals table if it does not exist."""
    path = db_path or get_db_path()
    key = str(path.resolve())
    with _schema_lock:
        if key in _schema_ready:
            return
    conn = _connect(path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS signals (
            setup_id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            direction TEXT NOT NULL,
            strategy TEXT NOT NULL,
            entry REAL NOT NULL,
            entry_type TEXT NOT NULL,
            sl REAL NOT NULL,
            tp1 REAL NOT NULL,
            tp2 REAL NOT NULL,
            tp3 REAL NOT NULL,
            net_rr_tp1 REAL NOT NULL,
            score REAL NOT NULL,
            breakdown_json TEXT NOT NULL,
            reasons_json TEXT NOT NULL,
            status TEXT NOT NULL,
            status_updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    with _schema_lock:
        _schema_ready.add(key)


def _breakdown_dict(setup: Setup) -> dict[str, Any]:
    b = setup.breakdown
    return {
        "htf": b.htf,
        "level_quality": b.level_quality,
        "momentum": b.momentum,
        "volume": b.volume,
        "candle_confirmation": b.candle_confirmation,
        "net_rr": b.net_rr,
        "volatility": b.volatility,
        "penalties": b.penalties,
        "total": b.total,
    }


def save_setup(setup: Setup, *, db_path: Path | None = None) -> bool:
    """
    Persist a trade setup once. Returns True if a new row was inserted.

    NO_TRADE setups are never written. Duplicate setup_id uses INSERT OR IGNORE.
    """
    if setup.direction == Direction.NO_TRADE:
        return False

    path = db_path or get_db_path()
    init_db(path)
    conn = _connect(path)

    created = _now_utc()
    status_updated = created
    params = (
        setup.setup_id,
        created,
        setup.symbol,
        setup.timeframe,
        setup.direction.value,
        setup.strategy,
        setup.entry,
        setup.entry_type.value,
        setup.stop_loss,
        setup.tp1,
        setup.tp2,
        setup.tp3,
        setup.net_rr[0],
        setup.score,
        json.dumps(_breakdown_dict(setup), separators=(",", ":")),
        json.dumps(list(setup.reasons), separators=(",", ":")),
        setup.status.value,
        status_updated,
    )

    cur = conn.execute(
        """
        INSERT OR IGNORE INTO signals (
            setup_id, created_at, symbol, timeframe, direction, strategy,
            entry, entry_type, sl, tp1, tp2, tp3, net_rr_tp1, score,
            breakdown_json, reasons_json, status, status_updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        params,
    )
    conn.commit()
    return cur.rowcount == 1


def reset_thread_connection_for_tests() -> None:
    """Close the current thread's connection (unit tests only)."""
    conn: sqlite3.Connection | None = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
    _local.conn = None
    _local.conn_path = None


def reset_schema_cache_for_tests() -> None:
    with _schema_lock:
        _schema_ready.clear()


def update_signal_status(setup_id: str, status: str, *, db_path: Path | None = None) -> bool:
    """Update lifecycle status from chart events."""
    if not setup_id or not status:
        return False
    path = db_path or get_db_path()
    init_db(path)
    conn = _connect(path)
    updated = _now_utc()
    cur = conn.execute(
        """
        UPDATE signals
        SET status = ?, status_updated_at = ?
        WHERE setup_id = ?
        """,
        (status, updated, setup_id),
    )
    conn.commit()
    return cur.rowcount > 0