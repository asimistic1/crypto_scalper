"""
Fetch public market data from Binance USDT-M perpetual futures via ccxt.
No API keys required for candles and ticker data.
"""

from __future__ import annotations

import os

import ccxt
import pandas as pd
from dotenv import load_dotenv
from zoneinfo import ZoneInfo

# Pakistan local time for display in the dashboard
PAKISTAN_TZ = ZoneInfo("Asia/Karachi")

# Single exchange instance (reused for all requests; app may also wrap with @st.cache_resource)
_exchange: ccxt.binanceusdm | None = None
_proxy_url: str | None = None


def load_proxy_from_env() -> str | None:
    """
    Read optional HTTPS proxy from .env / environment (local dev).
    On Streamlit Cloud, the app also copies st.secrets into configure_network().
    Never log the proxy URL (it may contain credentials).
    """
    load_dotenv()
    for key in ("BINANCE_HTTPS_PROXY", "HTTPS_PROXY", "HTTP_PROXY"):
        value = os.getenv(key, "").strip()
        if value:
            return value
    return None


def configure_network(proxy_url: str | None = None) -> None:
    """
    Set or clear the proxy used for Binance requests. Recreates the exchange client.
    Call once at app startup (and after changing secrets).
    """
    global _exchange, _proxy_url
    normalized = proxy_url.strip() if proxy_url else None
    if normalized != _proxy_url:
        _proxy_url = normalized
        _exchange = None


def _is_region_block_error(exc: BaseException) -> bool:
    """Detect HTTP 451 / 403 style blocks from Binance in ccxt error messages."""
    text = str(exc).lower()
    return "451" in text or "403" in text or "restricted location" in text


def region_block_user_message() -> str:
    """Short message shown in the UI when Binance returns 403/451."""
    return (
        "Binance is blocking this server’s region (very common on Streamlit Cloud US "
        "hosts). Running on your PC may still work."
    )


def region_block_help_markdown() -> str:
    """Longer help text for an expander / docs."""
    return """**Why this happens**  
Streamlit Community Cloud runs in US/EU data centers. Binance **USDT-M Futures**
API often refuses those IP addresses (HTTP 451 / 403). That is not a bug in your code.

**What usually works**

1. **Use the app on your PC** — `streamlit run streamlit_app.py` (your home IP is often allowed).
2. **Self-host Streamlit** on a small VPS in Asia/Middle East/Europe (not US), then run the same repo there.
3. **Optional proxy** — In [Streamlit app settings → Secrets](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management),
   add a proxy in an allowed region (paid service; you are responsible for compliance):

```toml
BINANCE_HTTPS_PROXY = "http://USER:PASS@proxy-host:PORT"
```

Reboot the app after saving secrets. Never commit real proxy credentials to GitHub.
"""


def _region_block_message() -> str:
    return region_block_user_message()


def get_exchange() -> ccxt.binanceusdm:
    """
    Return a shared Binance USDT-M futures client with rate limiting enabled.
    Uses BINANCE_HTTPS_PROXY / HTTPS_PROXY when configure_network() set one.
    """
    global _exchange
    if _exchange is None:
        options: dict = {"enableRateLimit": True}
        if _proxy_url:
            options["proxies"] = {"http": _proxy_url, "https": _proxy_url}
        _exchange = ccxt.binanceusdm(options)
    return _exchange


def _timeframe_ms(timeframe: str) -> int:
    """Convert ccxt timeframe string to milliseconds (for candle close detection)."""
    unit = timeframe[-1]
    value = int(timeframe[:-1])
    multipliers = {"m": 60_000, "h": 3_600_000, "d": 86_400_000, "w": 604_800_000}
    if unit not in multipliers:
        raise ValueError(f"Unsupported timeframe: {timeframe}")
    return value * multipliers[unit]


def get_candles(
    symbol: str, timeframe: str, limit: int = 500
) -> tuple[pd.DataFrame | None, str | None]:
    """
    Download OHLCV candles for a USDT perpetual (e.g. BTC/USDT:USDT).

    Returns (dataframe, error_message). On success error_message is None.
    Columns: time, open, high, low, close, volume, is_closed (bool).
    """
    try:
        exchange = get_exchange()
        raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        if not raw:
            return None, "No candle data returned from the exchange."

        df = pd.DataFrame(
            raw, columns=["timestamp", "open", "high", "low", "close", "volume"]
        )

        # Unix ms -> timezone-aware datetime in Pakistan
        df["time"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.tz_convert(
            PAKISTAN_TZ
        )

        for col in ("open", "high", "low", "close", "volume"):
            df[col] = df[col].astype(float)

        # Last row is still forming until the candle period ends
        now_ms = exchange.milliseconds()
        period_ms = _timeframe_ms(timeframe)
        last_open_ms = int(df["timestamp"].iloc[-1])
        df["is_closed"] = True
        df.loc[df.index[-1], "is_closed"] = (now_ms - last_open_ms) >= period_ms

        df = df.drop(columns=["timestamp"])
        return df, None

    except ccxt.NetworkError as e:
        if _is_region_block_error(e):
            return None, _region_block_message()
        return None, f"Network error while fetching candles: {e}"
    except ccxt.ExchangeError as e:
        if _is_region_block_error(e):
            return None, _region_block_message()
        return None, f"Exchange error while fetching candles: {e}"
    except Exception as e:
        if _is_region_block_error(e):
            return None, _region_block_message()
        return None, f"Unexpected error while fetching candles: {e}"


def get_ticker(symbol: str) -> tuple[dict | None, str | None]:
    """
    24h statistics for the symbol.

    Keys: last, change_pct, high_24h, low_24h, quote_volume_24h.
    """
    try:
        exchange = get_exchange()
        t = exchange.fetch_ticker(symbol)
        last = float(t.get("last") or 0)
        pct = t.get("percentage")
        if pct is None and t.get("open") and last:
            open_ = float(t["open"])
            if open_:
                pct = ((last - open_) / open_) * 100.0
        return (
            {
                "last": last,
                "change_pct": float(pct) if pct is not None else 0.0,
                "high_24h": float(t.get("high") or 0),
                "low_24h": float(t.get("low") or 0),
                "quote_volume_24h": float(t.get("quoteVolume") or 0),
            },
            None,
        )
    except ccxt.NetworkError as e:
        if _is_region_block_error(e):
            return None, _region_block_message()
        return None, f"Network error while fetching ticker: {e}"
    except ccxt.ExchangeError as e:
        if _is_region_block_error(e):
            return None, _region_block_message()
        return None, f"Exchange error while fetching ticker: {e}"
    except Exception as e:
        if _is_region_block_error(e):
            return None, _region_block_message()
        return None, f"Unexpected error while fetching ticker: {e}"


def _display_symbol(ccxt_symbol: str) -> str:
    """BTC/USDT:USDT -> BTC/USDT for the dropdown label."""
    base = ccxt_symbol.split(":")[0]
    return base


def get_top_symbols(n: int = 30) -> tuple[list[str], str | None]:
    """
    Top USDT perpetual futures by 24h quote volume (for coin selector).

    Returns list of display labels like BTC/USDT, not raw ccxt ids.
    """
    try:
        exchange = get_exchange()
        tickers = exchange.fetch_tickers()
        candidates: list[tuple[float, str]] = []

        for market_id, ticker in tickers.items():
            try:
                market = exchange.market(market_id)
            except Exception:
                continue
            if not market.get("swap"):
                continue
            if market.get("quote") != "USDT":
                continue
            vol = float(ticker.get("quoteVolume") or 0)
            if vol <= 0:
                continue
            candidates.append((vol, market_id))

        candidates.sort(key=lambda x: x[0], reverse=True)
        top = [_display_symbol(sym) for _, sym in candidates[:n]]
        # Ensure BTC is available even if ranking shifts
        if not any(s.startswith("BTC/") for s in top):
            if "BTC/USDT:USDT" in tickers:
                top.insert(0, "BTC/USDT")
        return top, None

    except ccxt.NetworkError as e:
        if _is_region_block_error(e):
            return [], _region_block_message()
        return [], f"Network error while loading symbol list: {e}"
    except ccxt.ExchangeError as e:
        if _is_region_block_error(e):
            return [], _region_block_message()
        return [], f"Exchange error while loading symbol list: {e}"
    except Exception as e:
        if _is_region_block_error(e):
            return [], _region_block_message()
        return [], f"Unexpected error while loading symbol list: {e}"


def display_to_ccxt_symbol(display: str) -> str:
    """Convert BTC/USDT dropdown value to ccxt futures symbol BTC/USDT:USDT."""
    if ":" in display:
        return display
    return f"{display}:USDT"