"""Daily/swing trend-following strategy."""

from __future__ import annotations

from dataclasses import dataclass

import yfinance as yf


@dataclass
class TrendFollowingSignal:
    symbol: str
    score: int
    confidence: float
    entry_logic: str
    exit_logic: str
    risk_flags: list[str]
    evidence: list[str]


def evaluate_trend_following(symbol: str) -> TrendFollowingSignal | None:
    df = yf.Ticker(symbol).history(period="9mo", interval="1d")
    if df.empty or len(df) < 120:
        return None

    close = df["Close"]
    sma20 = close.rolling(20).mean()
    sma50 = close.rolling(50).mean()

    latest_close = float(close.iloc[-1])
    sma20_now = float(sma20.iloc[-1])
    sma50_now = float(sma50.iloc[-1])
    sma50_prev = float(sma50.iloc[-11]) if len(sma50.dropna()) >= 11 else sma50_now

    if latest_close <= sma50_now or sma20_now <= sma50_now:
        return None

    score = 52
    evidence: list[str] = []
    risk_flags: list[str] = []

    evidence.append("Price above medium trend baseline (SMA50)")
    evidence.append("Trend alignment in place (SMA20 above SMA50)")

    slope_pct = ((sma50_now - sma50_prev) / sma50_prev) * 100 if sma50_prev > 0 else 0.0
    if slope_pct > 1.0:
        score += 20
        evidence.append(f"SMA50 slope positive ({slope_pct:.2f}% over 10d)")
    elif slope_pct > 0:
        score += 10
        evidence.append(f"SMA50 slightly rising ({slope_pct:.2f}% over 10d)")
    else:
        risk_flags.append("flat_or_falling_medium_trend")
        score -= 10

    extension_pct = ((latest_close - sma20_now) / sma20_now) * 100 if sma20_now > 0 else 0.0
    if extension_pct > 6.0:
        risk_flags.append("extended_above_short_trend")
        score -= 8
    else:
        score += 8
        evidence.append("Not excessively extended above short trend")

    score = max(0, min(100, score))
    confidence = round(score / 100.0, 2)

    return TrendFollowingSignal(
        symbol=symbol,
        score=score,
        confidence=confidence,
        entry_logic="Enter on pullback/continuation while close>SMA50 and SMA20>SMA50",
        exit_logic="Exit on close below SMA50 or trend structure breakdown",
        risk_flags=risk_flags,
        evidence=evidence,
    )

