"""Single backtest runner lock (avoids duplicate long signal scans)."""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

LOCK_PATH = Path(__file__).resolve().parents[1] / "data" / "backtest" / "run.lock"


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


@contextmanager
def acquire_run_lock():
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    if LOCK_PATH.exists():
        try:
            old_pid = int(LOCK_PATH.read_text(encoding="utf-8").strip())
        except ValueError:
            old_pid = 0
        if _pid_alive(old_pid):
            raise RuntimeError(
                f"Another backtest is already running (PID {old_pid}). "
                f"Delete {LOCK_PATH} only if that process is gone."
            )
        LOCK_PATH.unlink(missing_ok=True)
    LOCK_PATH.write_text(str(os.getpid()), encoding="utf-8")
    try:
        yield
    finally:
        try:
            if LOCK_PATH.exists() and LOCK_PATH.read_text(encoding="utf-8").strip() == str(os.getpid()):
                LOCK_PATH.unlink(missing_ok=True)
        except OSError:
            pass