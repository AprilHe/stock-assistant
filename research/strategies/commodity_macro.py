"""Daily/swing commodity macro strategy."""

from __future__ import annotations

import math
from dataclasses import dataclass

import yfinance as yf


@dataclass
class CommodityMacroSignal:
    symbol: str
    score: int
    confidence: float
    entry_logic: str
    exit_logic: str
    risk_flags: list[str]
    evidence: list[str]


def _history(symbol: str, period: str = "6mo"):
    return yf.Ticker(symbol).history(period=period, interval="1d")


def _pct_change(series, lookback: int) -> float:
    if len(series) <= lookback:
        return 0.0
    start = float(series.iloc[-lookback - 1])
    end = float(series.iloc[-1])
    if start == 0:
        return 0.0
    return ((end - start) / start) * 100


def _atr_percent(df, period: int = 14) -> float:
    high = df["High"]
    low = df["Low"]
    close = df["Close"]
    prev_close = close.shift(1)
    tr = (high - low).to_frame("hl")
    tr["hc"] = (high - prev_close).abs()
    tr["lc"] = (low - prev_close).abs()
    atr = tr.max(axis=1).rolling(period).mean().iloc[-1]
    latest_close = float(close.iloc[-1])
    if latest_close <= 0 or math.isnan(float(atr)):
        return 0.0
    return float(atr) / latest_close * 100


def _macro_series() -> tuple | None:
    dxy = _history("DX-Y.NYB", period="3mo")
    tnx = _history("^TNX", period="3mo")
    spy = _history("SPY", period="3mo")
    if dxy.empty or tnx.empty or spy.empty:
        return None
    return dxy["Close"], tnx["Close"], spy["Close"]


def evaluate_commodity_macro(symbol: str) -> CommodityMacroSignal | None:
    df = _history(symbol, period="6mo")
    if df.empty or len(df) < 80:
        return None

    close = df["Close"]
    latest_close = float(close.iloc[-1])
    sma20 = float(close.rolling(20).mean().iloc[-1])
    sma50 = float(close.rolling(50).mean().iloc[-1])
    ret20 = _pct_change(close, 20)
    ret60 = _pct_change(close, 60)
    atr_pct = _atr_percent(df, period=14)

    macro = _macro_series()
    if macro is None:
        return None

    dxy_close, tnx_close, spy_close = macro
    dxy_ret20 = _pct_change(dxy_close, 20)
    tnx_ret20 = _pct_change(tnx_close, 20)
    spy_ret20 = _pct_change(spy_close, 20)

    score = 0
    evidence: list[str] = []
    risk_flags: list[str] = []

    if latest_close > sma20 > sma50 and ret20 > 0:
        score += 42
        evidence.append("Commodity trend is positive across 20/50 day averages")
    elif latest_close > sma50 and ret60 > 0:
        score += 24
        evidence.append("Commodity remains above 50 day trend")
    else:
        return None

    if symbol in {"GC=F", "SI=F"}:
        if dxy_ret20 < 0:
            score += 18
            evidence.append(f"Weaker USD supportive ({dxy_ret20:.2f}% over 20d)")
        else:
            risk_flags.append("usd_headwind")
            score -= 8
        if tnx_ret20 <= 0:
            score += 14
            evidence.append(f"Rates stable/down supportive ({tnx_ret20:.2f}% over 20d)")
        else:
            risk_flags.append("rates_headwind")
            score -= 10
    else:
        if spy_ret20 > 0:
            score += 16
            evidence.append(f"Risk-on backdrop supportive ({spy_ret20:.2f}% SPY over 20d)")
        else:
            risk_flags.append("risk_off_equity_tape")
            score -= 8
        if dxy_ret20 <= 0:
            score += 12
            evidence.append(f"USD not acting as a headwind ({dxy_ret20:.2f}% over 20d)")
        else:
            risk_flags.append("usd_headwind")
            score -= 6

    if ret60 > 8:
        score += 10
        evidence.append(f"Medium-term momentum strong ({ret60:.2f}% over 60d)")

    if atr_pct > 6.0:
        risk_flags.append("elevated_volatility")
        score -= 10
    if atr_pct > 9.0:
        risk_flags.append("very_high_volatility")
        score -= 10

    score = max(0, min(100, score))
    confidence = round(score / 100.0, 2)

    return CommodityMacroSignal(
        symbol=symbol,
        score=score,
        confidence=confidence,
        entry_logic="Follow commodity trend when macro backdrop is supportive",
        exit_logic=f"Exit below 20 day trend or 2 ATR stop ({atr_pct:.2f}% ATR)",
        risk_flags=risk_flags,
        evidence=evidence,
    )

