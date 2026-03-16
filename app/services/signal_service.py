"""
app/services/signal_service.py

Layer 2 of the v2 pipeline: Strategy Signal Generation.

Responsibilities:
- Run deterministic strategy evaluators on a ticker universe.
- Adapt each strategy's native output into the shared StrategySignal schema.
- Apply piecewise-linear score normalization via NormalizationProfile.

Design rules:
- This module owns the adapter boundary. Strategy impls (strategies/*/impl.py)
  are NOT changed. All schema translation happens here.
- normalize_score() is a pure function — easy to replace when Phase 4
  calibration data is available. Only the profile breakpoints change.
- If a strategy has no adapter registered, it is skipped with a warning
  rather than raising an exception (resilient to partial rollout).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone as dt_tz

from core.market_data import get_instrument_metadata
from core.strategy_registry import get_strategy
from domain.schemas.signals import (
    NormalizationProfile,
    NORMALIZATION_PROFILES,
    SignalRunResponse,
    StrategySignal,
)

# Strategy evaluators (existing impls, unchanged)
from strategies.breakout.impl import evaluate_breakout, BreakoutSignal
from strategies.pullback.impl import evaluate_pullback, PullbackSignal
from strategies.trend_following.impl import evaluate_trend_following, TrendFollowingSignal
from strategies.mean_reversion.impl import evaluate_mean_reversion, MeanReversionSignal
from strategies.donchian_breakout.impl import evaluate_donchian_breakout, DonchianBreakoutSignal
from strategies.commodity_macro.impl import evaluate_commodity_macro, CommodityMacroSignal

logger = logging.getLogger(__name__)

_ASSET_TYPES = {"stock", "commodity"}

# ---------------------------------------------------------------------------
# Horizon and validity templates per strategy
# (deterministic, not LLM-generated)
# ---------------------------------------------------------------------------

_HORIZON: dict[str, str] = {
    "breakout":         "3-10d",
    "pullback":         "2-7d",
    "trend_following":  "5-20d",
    "mean_reversion":   "1-5d",
    "donchian_breakout":"3-10d",
    "commodity_macro":  "5-15d",
}

_VALIDITY_TEMPLATE: dict[str, str] = {
    "breakout":         "expires_after_3_trading_days_or_on_sma20_break",
    "pullback":         "expires_after_2_trading_days_or_on_sma50_break",
    "trend_following":  "expires_after_5_trading_days_or_on_trend_break",
    "mean_reversion":   "expires_after_2_trading_days_or_on_sma20_reversion",
    "donchian_breakout":"expires_after_3_trading_days_or_on_lower_band_break",
    "commodity_macro":  "expires_after_3_trading_days_or_on_macro_regime_shift",
}

_ASSET_TYPE_BY_STRATEGY: dict[str, str] = {
    "breakout": "stock",
    "pullback": "stock",
    "trend_following": "stock",
    "mean_reversion": "stock",
    "donchian_breakout": "stock",
    "commodity_macro": "commodity",
}

_SIGNAL_FAMILY_BY_STRATEGY: dict[str, str] = {
    "breakout": "trend",
    "pullback": "pullback",
    "trend_following": "trend",
    "mean_reversion": "mean_reversion",
    "donchian_breakout": "trend",
    "commodity_macro": "macro_trend",
}


# ---------------------------------------------------------------------------
# Normalization — pure function, replace only profile breakpoints in Phase 4
# ---------------------------------------------------------------------------

def normalize_score(profile: NormalizationProfile, raw: int) -> float:
    """Piecewise linear map from strategy-native score to 0.0-1.0.

    Segment layout:
        raw ≤ raw_floor                        → norm_floor
        raw_floor  < raw ≤ raw_neutral          → linear norm_floor  → norm_neutral
        raw_neutral < raw ≤ raw_strong          → linear norm_neutral → norm_strong
        raw_strong  < raw ≤ raw_cap             → linear norm_strong  → norm_cap
        raw > raw_cap                           → norm_cap
    """
    r = float(raw)
    if r <= profile.raw_floor:
        return profile.norm_floor
    if r <= profile.raw_neutral:
        t = (r - profile.raw_floor) / (profile.raw_neutral - profile.raw_floor)
        return profile.norm_floor + t * (profile.norm_neutral - profile.norm_floor)
    if r <= profile.raw_strong:
        t = (r - profile.raw_neutral) / (profile.raw_strong - profile.raw_neutral)
        return profile.norm_neutral + t * (profile.norm_strong - profile.norm_neutral)
    if r <= profile.raw_cap:
        t = (r - profile.raw_strong) / (profile.raw_cap - profile.raw_strong)
        return profile.norm_strong + t * (profile.norm_cap - profile.norm_strong)
    return profile.norm_cap


def _round_norm(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 4)


def _base_metadata(strategy_id: str) -> dict[str, float | int | str | bool]:
    asset_type = _ASSET_TYPE_BY_STRATEGY.get(strategy_id, "stock")
    metadata: dict[str, float | int | str | bool] = {
        "asset_type": asset_type,
        "signal_family": _SIGNAL_FAMILY_BY_STRATEGY.get(strategy_id, "unknown"),
    }
    if asset_type == "commodity":
        metadata["sector"] = "commodities"
    return metadata


def _enrich_signal_metadata(signal: StrategySignal) -> StrategySignal:
    base_asset_type = str(signal.metadata.get("asset_type", "stock"))
    instrument_metadata = get_instrument_metadata(signal.ticker, asset_type=base_asset_type)
    merged_metadata = dict(signal.metadata)
    merged_metadata.update(instrument_metadata)
    signal.metadata = merged_metadata
    return signal


# ---------------------------------------------------------------------------
# Per-strategy adapters
# Each adapter converts a strategy-native dataclass → StrategySignal.
# ---------------------------------------------------------------------------

def _adapt_breakout(raw: BreakoutSignal) -> StrategySignal:
    profile = NORMALIZATION_PROFILES["breakout"]
    norm = _round_norm(normalize_score(profile, raw.score))
    return StrategySignal(
        ticker=raw.symbol,
        strategy_id="breakout",
        direction="long",
        score_raw=raw.score,
        score_normalized=norm,
        confidence=float(raw.confidence),
        horizon=_HORIZON["breakout"],
        validity_template=_VALIDITY_TEMPLATE["breakout"],
        entry_logic=raw.entry_logic,
        exit_logic=raw.exit_logic,
        risk_flags=raw.risk_flags,
        evidence=raw.evidence,
        normalization_method=profile.normalization_method,
        metadata=_base_metadata("breakout"),
    )


def _adapt_pullback(raw: PullbackSignal) -> StrategySignal:
    profile = NORMALIZATION_PROFILES["pullback"]
    norm = _round_norm(normalize_score(profile, raw.score))
    return StrategySignal(
        ticker=raw.symbol,
        strategy_id="pullback",
        direction="long",
        score_raw=raw.score,
        score_normalized=norm,
        confidence=float(raw.confidence),
        horizon=_HORIZON["pullback"],
        validity_template=_VALIDITY_TEMPLATE["pullback"],
        entry_logic=raw.entry_logic,
        exit_logic=raw.exit_logic,
        risk_flags=raw.risk_flags,
        evidence=raw.evidence,
        normalization_method=profile.normalization_method,
        metadata=_base_metadata("pullback"),
    )


def _adapt_trend_following(raw: TrendFollowingSignal) -> StrategySignal:
    profile = NORMALIZATION_PROFILES["trend_following"]
    norm = _round_norm(normalize_score(profile, raw.score))
    return StrategySignal(
        ticker=raw.symbol,
        strategy_id="trend_following",
        direction="long",
        score_raw=raw.score,
        score_normalized=norm,
        confidence=float(raw.confidence),
        horizon=_HORIZON["trend_following"],
        validity_template=_VALIDITY_TEMPLATE["trend_following"],
        entry_logic=raw.entry_logic,
        exit_logic=raw.exit_logic,
        risk_flags=raw.risk_flags,
        evidence=raw.evidence,
        normalization_method=profile.normalization_method,
        metadata=_base_metadata("trend_following"),
    )


def _adapt_mean_reversion(raw: MeanReversionSignal) -> StrategySignal:
    profile = NORMALIZATION_PROFILES["mean_reversion"]
    norm = _round_norm(normalize_score(profile, raw.score))
    return StrategySignal(
        ticker=raw.symbol,
        strategy_id="mean_reversion",
        direction="long",
        score_raw=raw.score,
        score_normalized=norm,
        confidence=float(raw.confidence),
        horizon=_HORIZON["mean_reversion"],
        validity_template=_VALIDITY_TEMPLATE["mean_reversion"],
        entry_logic=raw.entry_logic,
        exit_logic=raw.exit_logic,
        risk_flags=raw.risk_flags,
        evidence=raw.evidence,
        normalization_method=profile.normalization_method,
        metadata=_base_metadata("mean_reversion"),
    )


def _adapt_donchian_breakout(raw: DonchianBreakoutSignal) -> StrategySignal:
    profile = NORMALIZATION_PROFILES["donchian_breakout"]
    norm = _round_norm(normalize_score(profile, raw.score))
    return StrategySignal(
        ticker=raw.symbol,
        strategy_id="donchian_breakout",
        direction="long",
        score_raw=raw.score,
        score_normalized=norm,
        confidence=float(raw.confidence),
        horizon=_HORIZON["donchian_breakout"],
        validity_template=_VALIDITY_TEMPLATE["donchian_breakout"],
        entry_logic=raw.entry_logic,
        exit_logic=raw.exit_logic,
        risk_flags=raw.risk_flags,
        evidence=raw.evidence,
        normalization_method=profile.normalization_method,
        metadata=_base_metadata("donchian_breakout"),
    )


def _adapt_commodity_macro(raw: CommodityMacroSignal) -> StrategySignal:
    profile = NORMALIZATION_PROFILES["commodity_macro"]
    norm = _round_norm(normalize_score(profile, raw.score))
    return StrategySignal(
        ticker=raw.symbol,
        strategy_id="commodity_macro",
        direction="long",
        score_raw=raw.score,
        score_normalized=norm,
        confidence=float(raw.confidence),
        horizon=_HORIZON["commodity_macro"],
        validity_template=_VALIDITY_TEMPLATE["commodity_macro"],
        entry_logic=raw.entry_logic,
        exit_logic=raw.exit_logic,
        risk_flags=raw.risk_flags,
        evidence=raw.evidence,
        normalization_method=profile.normalization_method,
        metadata=_base_metadata("commodity_macro"),
    )


# Registry: strategy_id → (evaluator_fn, adapter_fn)
_STRATEGY_REGISTRY: dict[str, tuple] = {
    "breakout":         (evaluate_breakout,         _adapt_breakout),
    "pullback":         (evaluate_pullback,          _adapt_pullback),
    "trend_following":  (evaluate_trend_following,   _adapt_trend_following),
    "mean_reversion":   (evaluate_mean_reversion,    _adapt_mean_reversion),
    "donchian_breakout":(evaluate_donchian_breakout, _adapt_donchian_breakout),
    "commodity_macro":  (evaluate_commodity_macro,   _adapt_commodity_macro),
}


def _strategy_asset_types(strategy_id: str) -> list[str]:
    detail = get_strategy(strategy_id, capability="screen")
    raw = detail.get("asset_types") or []
    normalized = [str(asset).strip() for asset in raw if str(asset).strip() in _ASSET_TYPES]
    return normalized or ["stock"]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_signal_for_ticker(ticker: str, strategy_id: str) -> StrategySignal | None:
    """Run one strategy on one ticker. Returns None if no signal fires."""
    entry = _STRATEGY_REGISTRY.get(strategy_id)
    if entry is None:
        logger.warning("signal_service: no adapter for strategy '%s', skipping", strategy_id)
        return None
    evaluator, adapter = entry
    try:
        raw = evaluator(ticker)
        if raw is None:
            return None
        return _enrich_signal_metadata(adapter(raw))
    except Exception:
        logger.exception(
            "signal_service: error running strategy '%s' on ticker '%s'",
            strategy_id, ticker,
        )
        return None


def run_signals(
    tickers: list[str],
    strategies: list[str],
    asset_type: str = "stock",
) -> SignalRunResponse:
    """Run multiple strategies on a ticker universe.

    Returns a SignalRunResponse with all firing StrategySignals.
    Skips unknown strategies and individual ticker errors gracefully.
    """
    normalized_asset_type = asset_type.lower().strip()
    if normalized_asset_type not in _ASSET_TYPES:
        raise ValueError("Invalid asset_type. Choose from: stock | commodity")

    eligible_strategies: list[str] = []
    for strategy_id in strategies:
        strategy_asset_types = _strategy_asset_types(strategy_id)
        if normalized_asset_type not in strategy_asset_types:
            logger.warning(
                "signal_service: skipping strategy '%s' for asset_type '%s' (allowed: %s)",
                strategy_id,
                normalized_asset_type,
                ", ".join(strategy_asset_types),
            )
            continue
        eligible_strategies.append(strategy_id)

    signals: list[StrategySignal] = []
    for ticker in tickers:
        for strategy_id in eligible_strategies:
            signal = run_signal_for_ticker(ticker, strategy_id)
            if signal is not None:
                signals.append(signal)

    return SignalRunResponse(
        generated_at=datetime.now(dt_tz.utc).isoformat(),
        signals=signals,
    )
