"""
core/market_data.py
Fetches current price and % change for each ticker in the watchlist via yfinance.

Every snapshot function now returns an `_as_of` key at the top level of the
result dict.  This is the date of the most-recent trading session reflected
in the data (which may be Friday when the code runs on a Saturday/Sunday).
Downstream callers (e.g. ai_analysis.py) should use this date in report
headers instead of datetime.now(), so weekend/holiday runs do not mislabel
the report with a non-trading date.

Example extra key:
    {"_as_of": "2026-03-14", "S&P 500": {...}, ...}
"""

import json
from datetime import date, datetime, timedelta, timezone as dt_tz
from pathlib import Path
from typing import Optional

import yfinance as yf
from dotenv import load_dotenv

load_dotenv()

_DATA_DIR = Path(__file__).resolve().parents[1] / "data"
_INSTRUMENT_METADATA_CACHE = _DATA_DIR / "instrument_metadata.json"
_INSTRUMENT_METADATA_TTL = timedelta(hours=24)

WATCHLIST = {
    # US Indices
    "S&P 500":   "^GSPC",
    "Nasdaq":    "^IXIC",
    "Dow Jones": "^DJI",
    # Commodities
    "Gold":      "GC=F",
    "Oil (WTI)": "CL=F",
    # Crypto
    "Bitcoin":   "BTC-USD",
}

# Extended US market data: major indices + sector ETFs + fear gauge
US_MARKET_EXTENDED = {
    # Major Indices
    "S&P 500":       "^GSPC",
    "Nasdaq":        "^IXIC",
    "Dow Jones":     "^DJI",
    "Russell 2000":  "^RUT",
    "VIX":           "^VIX",
    # Sector ETFs
    "Technology":    "XLK",
    "Financials":    "XLF",
    "Energy":        "XLE",
    "Healthcare":    "XLV",
    "Utilities":     "XLU",
    "Consumer Disc": "XLY",
    "Consumer Staples": "XLP",
    "Industrials":   "XLI",
    "Real Estate":   "XLRE",
    "Materials":     "XLB",
    "Communication": "XLC",
}

COMMODITY_MARKET = {
    "Gold":         "GC=F",
    "Silver":       "SI=F",
    "WTI Oil":      "CL=F",
    "Natural Gas":  "NG=F",
    "Copper":       "HG=F",
}


def _load_instrument_metadata_cache() -> dict[str, dict]:
    if not _INSTRUMENT_METADATA_CACHE.exists():
        return {}
    try:
        return json.loads(_INSTRUMENT_METADATA_CACHE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_instrument_metadata_cache(cache: dict[str, dict]) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    _INSTRUMENT_METADATA_CACHE.write_text(
        json.dumps(cache, ensure_ascii=True, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _cache_is_fresh(fetched_at: str | None) -> bool:
    if not fetched_at:
        return False
    try:
        fetched = datetime.fromisoformat(fetched_at)
    except ValueError:
        return False
    return datetime.now(dt_tz.utc) - fetched <= _INSTRUMENT_METADATA_TTL


def _sanitize_instrument_metadata(raw: dict) -> dict[str, float | int | str | bool]:
    clean: dict[str, float | int | str | bool] = {}
    for key, value in raw.items():
        if value in (None, ""):
            continue
        if isinstance(value, (str, bool, int, float)):
            clean[key] = value
    return clean


def get_instrument_metadata(symbol: str, asset_type: str = "stock") -> dict[str, float | int | str | bool]:
    """Return lightweight instrument metadata with a small on-disk cache."""
    normalized_symbol = str(symbol).upper().strip()
    normalized_asset_type = str(asset_type or "stock").lower().strip()

    if normalized_asset_type == "commodity":
        return {
            "asset_type": "commodity",
            "sector": "commodities",
            "industry": "commodities",
        }

    cache = _load_instrument_metadata_cache()
    cached = cache.get(normalized_symbol, {})
    if cached and _cache_is_fresh(cached.get("fetched_at")):
        return _sanitize_instrument_metadata(cached.get("metadata", {}))

    metadata: dict[str, float | int | str | bool] = {"asset_type": normalized_asset_type or "stock"}
    try:
        ticker = yf.Ticker(normalized_symbol)
        info = ticker.info or {}
        metadata.update(
            _sanitize_instrument_metadata(
                {
                    "asset_type": normalized_asset_type or str(info.get("quoteType", "stock")).lower(),
                    "sector": info.get("sector") or "",
                    "industry": info.get("industry") or "",
                    "instrument_name": info.get("longName") or info.get("shortName") or normalized_symbol,
                    "currency": info.get("currency") or "",
                    "exchange": info.get("exchange") or "",
                }
            )
        )
    except Exception:
        pass

    cache[normalized_symbol] = {
        "fetched_at": datetime.now(dt_tz.utc).isoformat(),
        "metadata": metadata,
    }
    _save_instrument_metadata_cache(cache)
    return metadata


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _last_trading_date_from_df(df) -> Optional[str]:
    """Return the ISO date string of the last row in a yfinance DataFrame.

    yfinance history() always returns rows indexed by *trading* sessions, so
    the last row is the most-recent trading day regardless of when this code
    runs (weekends, holidays, etc.).  Returns None if df is empty.
    """
    if df is None or df.empty:
        return None
    try:
        return df.index[-1].date().isoformat()
    except Exception:
        return None


def _fetch_ticker_snapshot(symbol: str, name: str) -> tuple[dict, Optional[str]]:
    """Fetch price data for one ticker.  Returns (entry_dict, as_of_date)."""
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="2d")

        if df.empty or len(df) < 1:
            return (
                {"ticker": symbol, "price": None, "change_pct": None, "error": "data unavailable"},
                None,
            )

        latest_close = df["Close"].iloc[-1]
        as_of = _last_trading_date_from_df(df)

        if len(df) >= 2:
            prev_close = df["Close"].iloc[-2]
            change_pct = ((latest_close - prev_close) / prev_close) * 100
        else:
            change_pct = 0.0

        return (
            {
                "ticker": symbol,
                "price": round(float(latest_close), 2),
                "change_pct": round(float(change_pct), 2),
            },
            as_of,
        )

    except Exception as e:
        return (
            {"ticker": symbol, "price": None, "change_pct": None, "error": str(e)},
            None,
        )


def _build_snapshot(ticker_map: dict) -> dict:
    """Generic snapshot builder used by all public functions.

    Returns a dict where:
    - every key from ticker_map maps to its price entry
    - "_as_of" contains the most-recent trading date found across all tickers
      (ISO string, e.g. "2026-03-14"), or None if no data was available
    """
    snapshot: dict = {}
    latest_date: Optional[str] = None

    for name, symbol in ticker_map.items():
        entry, as_of = _fetch_ticker_snapshot(symbol, name)
        snapshot[name] = entry
        # Keep the latest date seen across all tickers
        if as_of is not None and (latest_date is None or as_of > latest_date):
            latest_date = as_of

    snapshot["_as_of"] = latest_date
    return snapshot


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_market_snapshot() -> dict:
    """
    Returns a dict like:
    {
        "_as_of": "2026-03-14",
        "S&P 500": {"ticker": "^GSPC", "price": 5123.41, "change_pct": -1.2},
        "Gold":    {"ticker": "GC=F",  "price": None, "change_pct": None, "error": "..."},
        ...
    }
    """
    return _build_snapshot(WATCHLIST)


def get_snapshot_for(tickers: list[str]) -> dict:
    """
    Like get_market_snapshot() but for an arbitrary list of ticker symbols.
    Returns a dict keyed by ticker symbol, plus "_as_of".
    """
    return _build_snapshot({symbol: symbol for symbol in tickers})


def get_us_market_extended_snapshot() -> dict:
    """
    Returns price snapshot for major US indices + sector ETFs, plus "_as_of".
    """
    return _build_snapshot(US_MARKET_EXTENDED)


def get_commodity_snapshot() -> dict:
    """
    Returns price snapshot for major commodities, plus "_as_of".
    """
    return _build_snapshot(COMMODITY_MARKET)


def get_last_trading_date() -> Optional[str]:
    """Return the ISO date of the most recent completed trading session.

    Uses SPY as a proxy (highly liquid, never has data gaps).
    Falls back to None if yfinance is unavailable.
    """
    try:
        df = yf.Ticker("SPY").history(period="2d")
        return _last_trading_date_from_df(df)
    except Exception:
        return None


if __name__ == "__main__":
    import json
    print("Fetching market snapshot...")
    data = get_market_snapshot()
    print(f"As of: {data.get('_as_of')}")
    print(json.dumps({k: v for k, v in data.items() if k != "_as_of"}, indent=2))
