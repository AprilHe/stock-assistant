"""Daily/swing mean-reversion strategy."""

from __future__ import annotations

from dataclasses import dataclass

import yfinance as yf


@dataclass
class MeanReversionSignal:
    symbol: str
    score: int
    confidence: float
    entry_logic: str
    exit_logic: str
    risk_flags: list[str]
    evidence: list[str]


def _rsi(series, period: int = 14):
    delta = series.diff()
    gains = delta.clip(lower=0).rolling(period).mean()
    losses = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gains / losses.replace(0, 1e-9)
    return 100 - (100 / (1 + rs))


def evaluate_mean_reversion(symbol: str) -> MeanReversionSignal | None:
    df = yf.Ticker(symbol).history(period="9mo", interval="1d")
    if df.empty or len(df) < 120:
        return None

    close = df["Close"]
    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    upper = sma20 + 2 * std20
    lower = sma20 - 2 * std20
    rsi14 = _rsi(close, period=14)
    sma50 = close.rolling(50).mean()

    latest_close = float(close.iloc[-1])
    lower_now = float(lower.iloc[-1])
    sma20_now = float(sma20.iloc[-1])
    sma50_now = float(sma50.iloc[-1])
    rsi_now = float(rsi14.iloc[-1])

    # Long mean-reversion trigger: oversold versus local distribution.
    if not (latest_close < lower_now and rsi_now < 36):
        return None

    score = 50
    evidence: list[str] = []
    risk_flags: list[str] = []

    evidence.append("Price below lower Bollinger band (20,2)")
    evidence.append(f"RSI indicates short-term oversold state ({rsi_now:.1f})")

    distance_to_mean = ((sma20_now - latest_close) / latest_close) * 100 if latest_close > 0 else 0.0
    if 1.5 <= distance_to_mean <= 8.0:
        score += 18
        evidence.append(f"Reasonable reversion distance ({distance_to_mean:.2f}% to SMA20)")
    elif distance_to_mean > 8.0:
        score += 6
        risk_flags.append("deep_oversold_possible_trend_damage")
    else:
        score += 10

    if latest_close >= sma50_now:
        score += 14
        evidence.append("Medium trend not broken (close near/above SMA50)")
    else:
        score -= 8
        risk_flags.append("counter_trend_reversion")

    score = max(0, min(100, score))
    confidence = round(score / 100.0, 2)

    return MeanReversionSignal(
        symbol=symbol,
        score=score,
        confidence=confidence,
        entry_logic="Enter when price is below lower band with oversold RSI",
        exit_logic="Exit near SMA20 mean reversion or if downside extends",
        risk_flags=risk_flags,
        evidence=evidence,
    )

