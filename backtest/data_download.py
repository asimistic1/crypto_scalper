"""
Download Binance USDⓈ-M futures history from data.binance.vision (+ REST gap fill).

CLI: python -m backtest.data_download --symbols BTCUSDT --intervals 5m,15m --months 24
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

from backtest.csv_klines import parse_kline_csv
from backtest.paths import (
    FUNDING_DIR,
    HISTORY_DIR,
    download_gaps_path,
    funding_parquet,
    history_parquet,
    symbol_aux_parquet,
)
from backtest.secure_io import (
    http_get_bytes,
    safe_extract_csv,
    sha256_bytes,
    verify_checksum,
)
from core.candle_store import _period_ms
from core.http_client import fapi_get

logger = logging.getLogger(__name__)

VISION_BASE = "https://data.binance.vision/data/futures/um"
SPOT_VISION_BASE = "https://data.binance.vision/data/spot"
DEFAULT_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT")
DEFAULT_INTERVALS = ("5m", "15m", "1h", "4h", "1d")
OPTIONAL_INTERVALS = ("1m",)


@dataclass(frozen=True)
class MonthSpec:
    year: int
    month: int

    def label(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"

    def prev(self) -> MonthSpec:
        if self.month == 1:
            return MonthSpec(self.year - 1, 12)
        return MonthSpec(self.year, self.month - 1)


def month_range(end: datetime, months: int) -> list[MonthSpec]:
    """Last `months` full calendar months plus current month."""
    cur = MonthSpec(end.year, end.month)
    out = [cur]
    m = cur
    for _ in range(months):
        m = m.prev()
        out.append(m)
    return list(reversed(out))


def _monthly_kline_url(symbol: str, interval: str, spec: MonthSpec) -> tuple[str, str]:
    fname = f"{symbol}-{interval}-{spec.label()}.zip"
    base = f"{VISION_BASE}/monthly/klines/{symbol}/{interval}"
    return f"{base}/{fname}", f"{base}/{fname}.CHECKSUM"


def _daily_kline_url(symbol: str, interval: str, day: datetime) -> tuple[str, str]:
    d = day.strftime("%Y-%m-%d")
    fname = f"{symbol}-{interval}-{d}.zip"
    base = f"{VISION_BASE}/daily/klines/{symbol}/{interval}"
    return f"{base}/{fname}", f"{base}/{fname}.CHECKSUM"


def _monthly_funding_url(symbol: str, spec: MonthSpec) -> tuple[str, str]:
    fname = f"{symbol}-fundingRate-{spec.label()}.zip"
    base = f"{VISION_BASE}/monthly/fundingRate/{symbol}"
    return f"{base}/{fname}", f"{base}/{fname}.CHECKSUM"


def _manifest_path(symbol: str, interval: str) -> Path:
    return HISTORY_DIR / symbol.upper() / f"{interval}.manifest.json"


def _aux_manifest_path(symbol: str, kind: str) -> Path:
    return HISTORY_DIR / symbol.upper() / f"{kind}.manifest.json"


def _load_manifest(symbol: str, interval: str) -> dict:
    path = _manifest_path(symbol, interval)
    if not path.exists():
        return {"verified_shards": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def _save_manifest(symbol: str, interval: str, data: dict) -> None:
    path = _manifest_path(symbol, interval)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def download_verified_zip(url: str, checksum_url: str, expected_member: str) -> bytes:
    zip_bytes = http_get_bytes(url)
    checksum_text = http_get_bytes(checksum_url).decode("utf-8", errors="replace")
    verify_checksum(zip_bytes, checksum_text)
    return safe_extract_csv(zip_bytes, expected_member)


def fetch_month_klines(symbol: str, interval: str, spec: MonthSpec, manifest: dict) -> pd.DataFrame | None:
    key = f"monthly:{spec.label()}"
    if manifest.get("verified_shards", {}).get(key):
        return None
    url, csum = _monthly_kline_url(symbol, interval, spec)
    expected = f"{symbol}-{interval}-{spec.label()}.csv"
    try:
        csv = download_verified_zip(url, csum, expected)
        manifest.setdefault("verified_shards", {})[key] = sha256_bytes(csv)
        return parse_kline_csv(csv)
    except Exception as exc:  # noqa: BLE001 — log and skip missing months
        logger.warning("month %s %s %s: %s", symbol, interval, spec.label(), exc)
        return None


def fetch_daily_range(symbol: str, interval: str, start: datetime, end: datetime, manifest: dict) -> list[pd.DataFrame]:
    frames: list[pd.DataFrame] = []
    day = start
    while day.date() <= end.date():
        key = f"daily:{day.strftime('%Y-%m-%d')}"
        if manifest.get("verified_shards", {}).get(key):
            day += timedelta(days=1)
            continue
        url, csum = _daily_kline_url(symbol, interval, day)
        expected = f"{symbol}-{interval}-{day.strftime('%Y-%m-%d')}.csv"
        try:
            csv = download_verified_zip(url, csum, expected)
            manifest.setdefault("verified_shards", {})[key] = sha256_bytes(csv)
            frames.append(parse_kline_csv(csv))
        except Exception as exc:  # noqa: BLE001
            logger.debug("daily %s %s %s: %s", symbol, interval, day.date(), exc)
        day += timedelta(days=1)
    return frames


def integrity_report(df: pd.DataFrame, interval: str) -> list[str]:
    warnings: list[str] = []
    if df.empty:
        return ["empty frame"]
    if df["time"].duplicated().any():
        warnings.append("duplicate open times")
        df = df.drop_duplicates(subset=["time"], keep="last")
    if not df["time"].is_monotonic_increasing:
        warnings.append("unsorted times")
        df = df.sort_values("time")
    period = pd.Timedelta(milliseconds=_period_ms(interval))
    gaps = df["time"].diff().dropna()
    big = gaps[gaps > period]
    for idx in big.index:
        prev_t = df["time"].iloc[idx - 1]
        cur_t = df["time"].iloc[idx]
        warnings.append(f"gap {prev_t} -> {cur_t} ({interval})")
    return warnings


def merge_frames(frames: list[pd.DataFrame]) -> pd.DataFrame:
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    df = df.drop_duplicates(subset=["close_time"], keep="last")
    return df.sort_values("time").reset_index(drop=True)


def rest_gap_fill(symbol: str, interval: str, df: pd.DataFrame) -> pd.DataFrame:
    """Fill from last close_time to now via REST (uses core http_client budget)."""
    if df.empty:
        return df
    last_ms = int(df["close_time"].iloc[-1])
    period = _period_ms(interval)
    now_ms = int(datetime.now(tz=UTC).timestamp() * 1000)
    if now_ms - last_ms <= period:
        return df
    start_ms = last_ms + 1
    out_rows: list = []
    while start_ms < now_ms:
        resp = fapi_get(
            "/fapi/v1/klines",
            {"symbol": symbol, "interval": interval, "startTime": start_ms, "limit": 1000},
        )
        batch = resp.json()
        if not batch:
            break
        out_rows.extend(batch)
        start_ms = int(batch[-1][6]) + 1
        if len(batch) < 1000:
            break
    if not out_rows:
        return df
    from core.candle_store import _klines_to_df

    extra = _klines_to_df(out_rows)
    merged = merge_frames([df, extra])
    return merged


def download_symbol_interval(
    symbol: str,
    interval: str,
    *,
    months: int,
    use_daily_current_month: bool = True,
) -> pd.DataFrame:
    manifest = _load_manifest(symbol, interval)
    end = datetime.now(tz=UTC)
    specs = month_range(end, months)
    frames: list[pd.DataFrame] = []
    for spec in specs[:-1]:
        part = fetch_month_klines(symbol, interval, spec, manifest)
        if part is not None and not part.empty:
            frames.append(part)
    # Current month: daily files
    if use_daily_current_month:
        first_day = datetime(end.year, end.month, 1, tzinfo=UTC)
        frames.extend(fetch_daily_range(symbol, interval, first_day, end, manifest))
    elif specs:
        part = fetch_month_klines(symbol, interval, specs[-1], manifest)
        if part is not None and not part.empty:
            frames.append(part)
    df = merge_frames(frames)
    warnings = integrity_report(df, interval)
    for w in warnings:
        logger.warning("%s %s integrity: %s", symbol, interval, w)
    df = rest_gap_fill(symbol, interval, df)
    _save_manifest(symbol, interval, manifest)
    return df


def save_history(df: pd.DataFrame, symbol: str, interval: str) -> Path:
    path = history_parquet(symbol, interval)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return path


def _parse_funding_csv(raw: bytes) -> pd.DataFrame:
    import io as _io

    text = raw.decode("utf-8")
    first = text.splitlines()[0].split(",")[0]
    has_header = not first.strip().isdigit()
    df = pd.read_csv(_io.StringIO(text), header=0 if has_header else None)
    if not has_header:
        df.columns = ["calc_time", "funding_interval", "last_funding_rate"]
    df["calc_time"] = pd.to_datetime(pd.to_numeric(df["calc_time"], errors="coerce"), unit="ms", utc=True)
    df["last_funding_rate"] = pd.to_numeric(df["last_funding_rate"], errors="coerce")
    return df.dropna(subset=["calc_time"]).sort_values("calc_time")


def _daily_metrics_url(symbol: str, day: datetime) -> tuple[str, str]:
    d = day.strftime("%Y-%m-%d")
    fname = f"{symbol}-metrics-{d}.zip"
    base = f"{VISION_BASE}/daily/metrics/{symbol}"
    return f"{base}/{fname}", f"{base}/{fname}.CHECKSUM"


def _parse_metrics_csv(raw: bytes) -> pd.DataFrame:
    import io as _io

    text = raw.decode("utf-8")
    df = pd.read_csv(_io.StringIO(text))
    if "create_time" in df.columns:
        df["time"] = pd.to_datetime(df["create_time"], utc=True)
        df["close_time"] = (df["time"].astype("int64") // 10**6) + 300_000 - 1
    df = df.rename(
        columns={
            "sum_open_interest": "open_interest",
            "sum_open_interest_value": "open_interest_value",
            "sum_toptrader_long_short_ratio": "top_trader_ls_ratio",
            "count_toptrader_long_short_ratio": "top_trader_ls_ratio_count",
            "count_long_short_ratio": "global_ls_ratio",
            "sum_taker_long_short_vol_ratio": "taker_ls_vol_ratio",
        }
    )
    for c in ("open_interest", "open_interest_value", "top_trader_ls_ratio", "global_ls_ratio", "taker_ls_vol_ratio"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    keep = [c for c in df.columns if c not in ("create_time",)]
    return df[keep].dropna(subset=["time"]).sort_values("time")


def fetch_daily_metrics(symbol: str, day: datetime, manifest: dict) -> pd.DataFrame | None:
    key = f"metrics:{day.strftime('%Y-%m-%d')}"
    if manifest.get("verified_shards", {}).get(key):
        return None
    url, csum = _daily_metrics_url(symbol, day)
    expected = f"{symbol}-metrics-{day.strftime('%Y-%m-%d')}.csv"
    try:
        csv = download_verified_zip(url, csum, expected)
        manifest.setdefault("verified_shards", {})[key] = sha256_bytes(csv)
        return _parse_metrics_csv(csv)
    except Exception as exc:  # noqa: BLE001
        manifest.setdefault("gaps", []).append({"kind": "metrics", "day": day.strftime("%Y-%m-%d"), "error": str(exc)})
        logger.debug("metrics %s %s: %s", symbol, day.date(), exc)
        return None


def download_metrics(symbol: str, months: int) -> Path | None:
    """5m futures metrics (OI, L/S ratios, taker ratio) from daily Vision archives."""
    manifest_path = _aux_manifest_path(symbol, "metrics_5m")
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"verified_shards": {}, "gaps": []}
    end = datetime.now(tz=UTC)
    start = end - timedelta(days=months * 31)
    frames: list[pd.DataFrame] = []
    day = start
    while day.date() <= end.date():
        part = fetch_daily_metrics(symbol, day, manifest)
        if part is not None and not part.empty:
            frames.append(part)
        day += timedelta(days=1)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    path = symbol_aux_parquet(symbol, "metrics_5m")
    if not frames:
        return path if path.exists() else None
    df = pd.concat(frames, ignore_index=True).drop_duplicates(subset=["close_time"], keep="last")
    df = df.sort_values("time").reset_index(drop=True)
    warnings = integrity_report(df, "5m")
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    gaps_path = download_gaps_path(symbol)
    gaps = {"metrics": manifest.get("gaps", []), "updated": datetime.now(tz=UTC).isoformat()}
    gaps_path.write_text(json.dumps(gaps, indent=2), encoding="utf-8")
    for w in warnings:
        logger.warning("%s metrics: %s", symbol, w)
    logger.info("saved %s metrics rows -> %s", len(df), path)
    return path


def _premium_kline_url(symbol: str, interval: str, spec: MonthSpec) -> tuple[str, str]:
    fname = f"{symbol}-{interval}-{spec.label()}.zip"
    base = f"{VISION_BASE}/monthly/premiumIndexKlines/{symbol}/{interval}"
    return f"{base}/{fname}", f"{base}/{fname}.CHECKSUM"


def fetch_month_premium(symbol: str, interval: str, spec: MonthSpec, manifest: dict) -> pd.DataFrame | None:
    key = f"premium:{spec.label()}"
    if manifest.get("verified_shards", {}).get(key):
        return None
    url, csum = _premium_kline_url(symbol, interval, spec)
    expected = f"{symbol}-{interval}-{spec.label()}.csv"
    try:
        csv = download_verified_zip(url, csum, expected)
        manifest.setdefault("verified_shards", {})[key] = sha256_bytes(csv)
        return parse_kline_csv(csv)
    except Exception as exc:  # noqa: BLE001
        manifest.setdefault("gaps", []).append({"kind": "premium", "month": spec.label(), "error": str(exc)})
        logger.warning("premium %s %s: %s", symbol, spec.label(), exc)
        return None


def download_premium_index(symbol: str, interval: str, months: int) -> Path | None:
    manifest_path = _aux_manifest_path(symbol, f"premium_{interval}")
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"verified_shards": {}, "gaps": []}
    end = datetime.now(tz=UTC)
    specs = month_range(end, months)
    frames: list[pd.DataFrame] = []
    for spec in specs:
        part = fetch_month_premium(symbol, interval, spec, manifest)
        if part is not None and not part.empty:
            frames.append(part)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    path = symbol_aux_parquet(symbol, f"premium_{interval}")
    if not frames:
        return path if path.exists() else None
    df = merge_frames(frames)
    warnings = integrity_report(df, interval)
    df.to_parquet(path, index=False)
    for w in warnings:
        logger.warning("%s premium %s: %s", symbol, interval, w)
    logger.info("saved %s premium rows -> %s", len(df), path)
    return path


def _spot_kline_url(symbol: str, interval: str, spec: MonthSpec) -> tuple[str, str]:
    fname = f"{symbol}-{interval}-{spec.label()}.zip"
    base = f"{SPOT_VISION_BASE}/monthly/klines/{symbol}/{interval}"
    return f"{base}/{fname}", f"{base}/{fname}.CHECKSUM"


def fetch_month_spot(symbol: str, interval: str, spec: MonthSpec, manifest: dict) -> pd.DataFrame | None:
    key = f"spot:{spec.label()}"
    if manifest.get("verified_shards", {}).get(key):
        return None
    url, csum = _spot_kline_url(symbol, interval, spec)
    expected = f"{symbol}-{interval}-{spec.label()}.csv"
    try:
        csv = download_verified_zip(url, csum, expected)
        manifest.setdefault("verified_shards", {})[key] = sha256_bytes(csv)
        return parse_kline_csv(csv)
    except Exception as exc:  # noqa: BLE001
        manifest.setdefault("gaps", []).append({"kind": "spot", "month": spec.label(), "error": str(exc)})
        logger.warning("spot %s %s: %s", symbol, spec.label(), exc)
        return None


def download_spot_klines(symbol: str, interval: str, months: int) -> Path | None:
    manifest_path = _aux_manifest_path(symbol, f"spot_{interval}")
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"verified_shards": {}, "gaps": []}
    end = datetime.now(tz=UTC)
    specs = month_range(end, months)
    frames: list[pd.DataFrame] = []
    for spec in specs:
        part = fetch_month_spot(symbol, interval, spec, manifest)
        if part is not None and not part.empty:
            frames.append(part)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    path = symbol_aux_parquet(symbol, f"spot_{interval}")
    if not frames:
        return path if path.exists() else None
    df = merge_frames(frames)
    warnings = integrity_report(df, interval)
    df.to_parquet(path, index=False)
    for w in warnings:
        logger.warning("%s spot %s: %s", symbol, interval, w)
    logger.info("saved %s spot rows -> %s", len(df), path)
    return path


def download_funding_to_symbol(symbol: str, months: int) -> Path | None:
    """Funding rate parquet under data/history/{SYMBOL}/funding.parquet."""
    legacy = download_funding(symbol, months)
    if legacy is None or not legacy.exists():
        return None
    df = pd.read_parquet(legacy)
    path = symbol_aux_parquet(symbol, "funding")
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return path


def run_research_download(symbols: list[str], months: int = 24) -> None:
    """Funding + metrics + premium 1h + spot 1h for edge research."""
    for sym in symbols:
        sym = sym.upper()
        logger.info("research bundle %s (%s months)…", sym, months)
        download_funding_to_symbol(sym, months)
        download_metrics(sym, months)
        download_premium_index(sym, "1h", months)
        download_spot_klines(sym, "1h", months)
        gaps_path = download_gaps_path(sym)
        if gaps_path.exists():
            logger.info("gaps logged -> %s", gaps_path)


def download_funding(symbol: str, months: int) -> Path | None:
    manifest_path = FUNDING_DIR / f"{symbol}.manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"verified_shards": {}}
    end = datetime.now(tz=UTC)
    frames: list[pd.DataFrame] = []
    for spec in month_range(end, months):
        key = f"funding:{spec.label()}"
        if manifest.get("verified_shards", {}).get(key):
            continue
        url, csum = _monthly_funding_url(symbol, spec)
        expected = f"{symbol}-fundingRate-{spec.label()}.csv"
        try:
            csv = download_verified_zip(url, csum, expected)
            manifest.setdefault("verified_shards", {})[key] = sha256_bytes(csv)
            raw = _parse_funding_csv(csv)
            if not raw.empty:
                frames.append(raw)
        except Exception as exc:  # noqa: BLE001
            logger.debug("funding %s %s: %s", symbol, spec.label(), exc)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    if not frames:
        return None
    df = pd.concat(frames, ignore_index=True)
    path = funding_parquet(symbol)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return path


def run_download(
    symbols: list[str],
    intervals: list[str],
    *,
    months: int,
    include_funding: bool = True,
) -> None:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    for sym in symbols:
        sym = sym.upper()
        for iv in intervals:
            logger.info("downloading %s %s …", sym, iv)
            df = download_symbol_interval(sym, iv, months=months)
            if df.empty:
                logger.warning("no data for %s %s", sym, iv)
                continue
            path = save_history(df, sym, iv)
            logger.info("saved %s rows -> %s", len(df), path)
        if include_funding:
            download_funding(sym, months)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(description="Download Binance futures history for backtest")
    p.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    p.add_argument("--intervals", default=",".join(DEFAULT_INTERVALS))
    p.add_argument("--months", type=int, default=24)
    p.add_argument("--no-funding", action="store_true")
    p.add_argument(
        "--research",
        action="store_true",
        help="Download edge-research bundle (funding, metrics, premium 1h, spot 1h)",
    )
    args = p.parse_args()
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    if args.research:
        run_research_download(symbols, months=args.months)
        return
    intervals = [s.strip() for s in args.intervals.split(",") if s.strip()]
    run_download(symbols, intervals, months=args.months, include_funding=not args.no_funding)


if __name__ == "__main__":
    main()