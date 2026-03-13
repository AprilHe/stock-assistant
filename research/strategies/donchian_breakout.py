"""Daily/swing Donchian breakout strategy."""

from __future__ import annotations

from dataclasses import dataclass

import yfinance as yf


@dataclass
class DonchianBreakoutSignal:
    symbol: str
    score: int
    confidence: float
    entry_logic: str
    exit_logic: str
    risk_flags: list[str]
    evidence: list[str]


def evaluate_donchian_breakout(symbol: str) -> DonchianBreakoutSignal | None:
    df = yf.Ticker(symbol).history(period="9mo", interval="1d")
    if df.empty or len(df) < 120:
        return None

    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    volume = df["Volume"]

    latest_close = float(close.iloc[-1])
    upper_20 = float(high.iloc[-21:-1].max())
    lower_10 = float(low.iloc[-11:-1].min())
    vol_ratio = float(volume.iloc[-1]) / float(volume.iloc[-21:-1].mean())
    breakout_pct = ((latest_close - upper_20) / upper_20) * 100 if upper_20 > 0 else 0.0

    if latest_close <= upper_20:
        return None

    score = 56
    evidence: list[str] = [f"Close above 20-day Donchian upper band by {breakout_pct:.2f}%"]
    risk_flags: list[str] = []

    if vol_ratio >= 1.5:
        score += 20
        evidence.append(f"Volume confirmation strong ({vol_ratio:.2f}x)")
    elif vol_ratio >= 1.2:
        score += 12
        evidence.append(f"Volume confirmation moderate ({vol_ratio:.2f}x)")
    else:
        score -= 8
        risk_flags.append("low_volume_breakout")

    pullback_buffer = ((latest_close - lower_10) / latest_close) * 100 if latest_close > 0 else 0.0
    if pullback_buffer < 3.5:
        score -= 6
        risk_flags.append("tight_exit_band_whipsaw_risk")
    else:
        score += 8
        evidence.append("Sufficient room versus 10-day lower band")

    if breakout_pct > 8.0:
        score -= 8
        risk_flags.append("extended_after_breakout")

    score = max(0, min(100, score))
    confidence = round(score / 100.0, 2)

    return DonchianBreakoutSignal(
        symbol=symbol,
        score=score,
        confidence=confidence,
        entry_logic="Enter on close above 20-day Donchian high",
        exit_logic="Exit on close below 10-day Donchian low",
        risk_flags=risk_flags,
        evidence=evidence,
    )

