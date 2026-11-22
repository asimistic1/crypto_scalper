"""Load historical pattern / strategy stats from reports/ (no hard-coded performance)."""

from __future__ import annotations

import json
import re
from functools import lru_cache

from backtest.paths import REPO_ROOT

REPORTS = REPO_ROOT / "reports"
SUMMARY_GLOB = "phase34_*_summary.txt"
DIAG_GLOB = "phase34_*_diagnostics.json"

_STRATEGY_KEY = {
    "trend_pullback": "trend_pullback",
    "breakout_retest": "breakout_retest",
}


@lru_cache(maxsize=32)
def _load_diagnostics(symbol_rest: str) -> dict | None:
    path = REPORTS / f"phase34_{symbol_rest.replace('USDT', '').lower()}_diagnostics.json"
    if not path.exists():
        for p in REPORTS.glob(DIAG_GLOB):
            if symbol_rest.replace("USDT", "").upper() in p.name.upper():
                path = p
                break
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


@lru_cache(maxsize=8)
def _summary_rows() -> list[tuple[str, str, float, float]]:
    """(symbol_rest, tf, tp1_win_rate_pct, net_e_r) from OOS tp1_full lines."""
    rows: list[tuple[str, str, float, float]] = []
    for path in REPORTS.glob(SUMMARY_GLOB):
        text = path.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            if "| OOS |" not in line or "tp1_full" not in line:
                continue
            m = re.match(
                r"^([A-Z]+USDT)\|(\w+)\|tp1_full\s+\|\s+OOS\s+\|\s+\d+\s+\|\s+\d+\s+\|\s+[\d.]+%\s+\|\s+([\d.]+)%",
                line.strip(),
            )
            if not m:
                continue
            sym, tf, wr = m.group(1), m.group(2), float(m.group(3))
            em = re.search(r"\|\s+(-?[\d.]+)\[", line)
            net_r = float(em.group(1)) if em else float("nan")
            rows.append((sym, tf, wr, net_r))
    return rows


def aggregate_warning(symbol_rest: str, timeframe: str) -> str | None:
    sym = symbol_rest.upper()
    for s, tf, wr, net_r in _summary_rows():
        if s == sym and tf == timeframe:
            return f"Not a tested edge — historically TP1 hit {wr:.1f}%, avg {net_r:+.2f}R after fees ({sym[:-4]} {tf}, Phase 3.4)"
    return None


def strategy_warning(symbol_rest: str, timeframe: str, strategy: str) -> str:
    key = _STRATEGY_KEY.get(strategy, strategy)
    diag = _load_diagnostics(symbol_rest)
    if diag is None:
        agg = aggregate_warning(symbol_rest, timeframe)
        return agg or "Untested"
    block_key = f"{timeframe}_OOS_breakdown_strategy"
    block = diag.get(block_key) or diag.get(f"{timeframe}_IS_breakdown_strategy")
    if not isinstance(block, list):
        agg = aggregate_warning(symbol_rest, timeframe)
        return agg or "Untested"
    for row in block:
        if row.get("strategy") == key:
            wr = float(row.get("win_rate", 0)) * 100.0
            net_r = float(row.get("net_e_r", 0))
            sym = symbol_rest.upper()
            label = sym.replace("USDT", "")
            return (
                f"Not a tested edge — historically TP1 hit {wr:.1f}%, avg {net_r:+.2f}R after fees "
                f"({label} {timeframe} {strategy}, Phase 3.4 OOS breakdown)"
            )
    agg = aggregate_warning(symbol_rest, timeframe)
    return agg or "Untested"