"""Daily/swing breakout screener strategy."""

from __future__ import annotations

import math
from dataclasses import dataclass

import yfinance as yf


@dataclass
class BreakoutSignal:
    symbol: str
    score: int
    confidence: float
    entry_logic: str
    exit_logic: str
    risk_flags: list[str]
    evidence: list[str]


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


def evaluate_breakout(symbol: str) -> BreakoutSignal | None:
    ticker = yf.Ticker(symbol)
    df = ticker.history(period="6mo", interval="1d")
    if df.empty or len(df) < 80:
        return None

    close = df["Close"]
    volume = df["Volume"]

    latest_close = float(close.iloc[-1])
    prev_high_20 = float(close.iloc[-21:-1].max())
    sma20 = float(close.rolling(20).mean().iloc[-1])
    sma50 = float(close.rolling(50).mean().iloc[-1])
    vol_ratio = float(volume.iloc[-1]) / float(volume.iloc[-21:-1].mean())
    atr_pct = _atr_percent(df, period=14)
    breakout_pct = ((latest_close - prev_high_20) / prev_high_20) * 100 if prev_high_20 > 0 else 0.0

    score = 0
    evidence: list[str] = []
    risk_flags: list[str] = []

    if latest_close > prev_high_20:
        score += 42
        evidence.append(f"Close broke above 20-day high by {breakout_pct:.2f}%")
    else:
        return None

    if latest_close > sma20 > sma50:
        score += 26
        evidence.append("Trend alignment: close > SMA20 > SMA50")
    elif latest_close > sma20:
        score += 14
        evidence.append("Short trend supportive: close > SMA20")

    if vol_ratio >= 1.6:
        score += 24
        evidence.append(f"Volume expansion strong ({vol_ratio:.2f}x)")
    elif vol_ratio >= 1.2:
        score += 16
        evidence.append(f"Volume expansion moderate ({vol_ratio:.2f}x)")
    else:
        risk_flags.append("low_volume_confirmation")

    if atr_pct > 5.0:
        score -= 10
        risk_flags.append("elevated_volatility")
    if atr_pct > 8.0:
        score -= 10
        risk_flags.append("very_high_volatility")

    if breakout_pct > 8.0:
        risk_flags.append("extended_after_breakout")

    score = max(0, min(100, score))
    confidence = round(score / 100.0, 2)

    return BreakoutSignal(
        symbol=symbol,
        score=score,
        confidence=confidence,
        entry_logic=f"Breakout above 20-day high with {vol_ratio:.2f}x volume",
        exit_logic=f"Exit on close below SMA20 or 2 ATR stop ({atr_pct:.2f}% ATR)",
        risk_flags=risk_flags,
        evidence=evidence,
    )

