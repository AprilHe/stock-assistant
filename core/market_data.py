"""
core/market_data.py
Fetches current price and % change for each ticker in the watchlist via yfinance.
"""

import yfinance as yf
from dotenv import load_dotenv

load_dotenv()

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


def get_market_snapshot() -> dict:
    """
    Returns a dict like:
    {
        "S&P 500": {"price": 5123.41, "change_pct": -1.2},
        "Gold":    {"price": None, "change_pct": None, "error": "data unavailable"},
        ...
    }
    """
    snapshot = {}

    for name, ticker_symbol in WATCHLIST.items():
        try:
            ticker = yf.Ticker(ticker_symbol)
            df = ticker.history(period="2d")

            if df.empty or len(df) < 1:
                snapshot[name] = {
                    "ticker": ticker_symbol,
                    "price": None,
                    "change_pct": None,
                    "error": "data unavailable",
                }
                continue

            latest_close = df["Close"].iloc[-1]

            # Calculate % change: need at least 2 rows for a real change
            if len(df) >= 2:
                prev_close = df["Close"].iloc[-2]
                change_pct = ((latest_close - prev_close) / prev_close) * 100
            else:
                change_pct = 0.0

            snapshot[name] = {
                "ticker": ticker_symbol,
                "price": round(float(latest_close), 2),
                "change_pct": round(float(change_pct), 2),
            }

        except Exception as e:
            snapshot[name] = {
                "ticker": ticker_symbol,
                "price": None,
                "change_pct": None,
                "error": str(e),
            }

    return snapshot


def get_snapshot_for(tickers: list[str]) -> dict:
    """
    Like get_market_snapshot() but for an arbitrary list of ticker symbols.
    Returns a dict keyed by ticker symbol.
    """
    snapshot = {}
    for symbol in tickers:
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period="2d")

            if df.empty or len(df) < 1:
                snapshot[symbol] = {"ticker": symbol, "price": None, "change_pct": None, "error": "data unavailable"}
                continue

            latest_close = df["Close"].iloc[-1]
            change_pct = 0.0
            if len(df) >= 2:
                prev_close = df["Close"].iloc[-2]
                change_pct = ((latest_close - prev_close) / prev_close) * 100

            snapshot[symbol] = {
                "ticker": symbol,
                "price": round(float(latest_close), 2),
                "change_pct": round(float(change_pct), 2),
            }
        except Exception as e:
            snapshot[symbol] = {"ticker": symbol, "price": None, "change_pct": None, "error": str(e)}

    return snapshot


def get_us_market_extended_snapshot() -> dict:
    """
    Returns price snapshot for major US indices + sector ETFs.
    Dict keyed by friendly name, same structure as get_market_snapshot().
    """
    ticker_map = US_MARKET_EXTENDED
    snapshot = {}
    for name, symbol in ticker_map.items():
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period="2d")
            if df.empty or len(df) < 1:
                snapshot[name] = {"ticker": symbol, "price": None, "change_pct": None, "error": "data unavailable"}
                continue
            latest_close = df["Close"].iloc[-1]
            change_pct = 0.0
            if len(df) >= 2:
                prev_close = df["Close"].iloc[-2]
                change_pct = ((latest_close - prev_close) / prev_close) * 100
            snapshot[name] = {
                "ticker": symbol,
                "price": round(float(latest_close), 2),
                "change_pct": round(float(change_pct), 2),
            }
        except Exception as e:
            snapshot[name] = {"ticker": symbol, "price": None, "change_pct": None, "error": str(e)}
    return snapshot


def get_commodity_snapshot() -> dict:
    """
    Returns price snapshot for major commodities.
    Dict keyed by friendly name, same structure as get_market_snapshot().
    """
    snapshot = {}
    for name, symbol in COMMODITY_MARKET.items():
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period="2d")
            if df.empty or len(df) < 1:
                snapshot[name] = {"ticker": symbol, "price": None, "change_pct": None, "error": "data unavailable"}
                continue
            latest_close = df["Close"].iloc[-1]
            change_pct = 0.0
            if len(df) >= 2:
                prev_close = df["Close"].iloc[-2]
                change_pct = ((latest_close - prev_close) / prev_close) * 100
            snapshot[name] = {
                "ticker": symbol,
                "price": round(float(latest_close), 2),
                "change_pct": round(float(change_pct), 2),
            }
        except Exception as e:
            snapshot[name] = {"ticker": symbol, "price": None, "change_pct": None, "error": str(e)}
    return snapshot


if __name__ == "__main__":
    import json
    print("Fetching market snapshot...")
    data = get_market_snapshot()
    print(json.dumps(data, indent=2))
