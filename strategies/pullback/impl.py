"""Daily/swing pullback screener strategy."""

from __future__ import annotations

import math
from dataclasses import dataclass

import yfinance as yf


@dataclass
class PullbackSignal:
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


def evaluate_pullback(symbol: str) -> PullbackSignal | None:
    ticker = yf.Ticker(symbol)
    df = ticker.history(period="6mo", interval="1d")
    if df.empty or len(df) < 80:
        return None

    close = df["Close"]
    volume = df["Volume"]

    latest_close = float(close.iloc[-1])
    sma20 = float(close.rolling(20).mean().iloc[-1])
    sma50 = float(close.rolling(50).mean().iloc[-1])
    prev_high_20 = float(close.iloc[-21:-1].max())
    vol_ratio = float(volume.iloc[-1]) / float(volume.iloc[-21:-1].mean())
    atr_pct = _atr_percent(df, period=14)

    if not (latest_close > sma50 and sma20 > sma50):
        return None

    pullback_pct = ((latest_close - sma20) / sma20) * 100 if sma20 > 0 else 0.0
    distance_to_high = ((prev_high_20 - latest_close) / prev_high_20) * 100 if prev_high_20 > 0 else 0.0

    if pullback_pct < -3.5 or pullback_pct > 1.5:
        return None
    if distance_to_high < 1.0 or distance_to_high > 8.0:
        return None

    score = 55
    evidence: list[str] = []
    risk_flags: list[str] = []

    evidence.append("Primary uptrend intact: SMA20 > SMA50 and price > SMA50")
    evidence.append(f"Pullback zone near SMA20 ({pullback_pct:.2f}% vs SMA20)")
    evidence.append(f"Not overextended: {distance_to_high:.2f}% below recent high")

    if vol_ratio <= 0.9:
        score += 15
        evidence.append(f"Volume contraction during pullback ({vol_ratio:.2f}x)")
    elif vol_ratio <= 1.1:
        score += 8
        evidence.append(f"Neutral pullback volume ({vol_ratio:.2f}x)")
    else:
        risk_flags.append("pullback_with_heavy_volume")
        score -= 8

    if atr_pct > 5.5:
        risk_flags.append("elevated_volatility")
        score -= 10

    score = max(0, min(100, score))
    confidence = round(score / 100.0, 2)

    return PullbackSignal(
        symbol=symbol,
        score=score,
        confidence=confidence,
        entry_logic="Buy near SMA20 while uptrend remains intact",
        exit_logic=f"Exit below SMA50 or 2 ATR stop ({atr_pct:.2f}% ATR)",
        risk_flags=risk_flags,
        evidence=evidence,
    )

