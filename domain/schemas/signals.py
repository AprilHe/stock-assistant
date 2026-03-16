"""
domain/schemas/signals.py
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_CALIBRATION_DIR = Path(__file__).parent.parent.parent / "data" / "calibration"

from .portfolio import PortfolioDecision, PortfolioSnapshot, UserProfile
from .proposal import ProposalResponse

SignalDirection = Literal["long", "short", "flat"]
AgreementLevel = Literal["low", "medium", "high"]
DataSufficiency = Literal["sufficient", "insufficient"]
NormalizationMethod = Literal["piecewise_linear_v1", "calibrated_v1", "fallback"]


class NormalizationProfile(BaseModel):
    strategy_id: str
    normalization_method: NormalizationMethod = "piecewise_linear_v1"
    raw_floor: int
    raw_neutral: int
    raw_strong: int
    raw_cap: int = 100
    norm_floor: float = Field(default=0.40, ge=0.0, le=1.0)
    norm_neutral: float = Field(default=0.50, ge=0.0, le=1.0)
    norm_strong: float = Field(default=0.65, ge=0.0, le=1.0)
    norm_cap: float = Field(default=0.80, ge=0.0, le=1.0)


NORMALIZATION_PROFILES: dict[str, NormalizationProfile] = {
    "breakout": NormalizationProfile(
        strategy_id="breakout",
        raw_floor=42, raw_neutral=62, raw_strong=82, raw_cap=100,
        norm_floor=0.40, norm_neutral=0.50, norm_strong=0.65, norm_cap=0.80,
    ),
    "pullback": NormalizationProfile(
        strategy_id="pullback",
        raw_floor=47, raw_neutral=58, raw_strong=68, raw_cap=80,
        norm_floor=0.40, norm_neutral=0.50, norm_strong=0.65, norm_cap=0.75,
    ),
    "trend_following": NormalizationProfile(
        strategy_id="trend_following",
        raw_floor=42, raw_neutral=60, raw_strong=72, raw_cap=88,
        norm_floor=0.40, norm_neutral=0.50, norm_strong=0.65, norm_cap=0.80,
    ),
    "mean_reversion": NormalizationProfile(
        strategy_id="mean_reversion",
        raw_floor=42, raw_neutral=58, raw_strong=72, raw_cap=82,
        norm_floor=0.38, norm_neutral=0.47, norm_strong=0.60, norm_cap=0.72,
    ),
    "donchian_breakout": NormalizationProfile(
        strategy_id="donchian_breakout",
        raw_floor=48, raw_neutral=64, raw_strong=76, raw_cap=84,
        norm_floor=0.40, norm_neutral=0.50, norm_strong=0.65, norm_cap=0.78,
    ),
    "commodity_macro": NormalizationProfile(
        strategy_id="commodity_macro",
        raw_floor=24, raw_neutral=56, raw_strong=76, raw_cap=96,
        norm_floor=0.40, norm_neutral=0.50, norm_strong=0.65, norm_cap=0.80,
    ),
}


def load_normalization_profiles(
    path: Path | None = None,
) -> dict[str, NormalizationProfile]:
    """Load normalization profiles from data/calibration/regime_adjustments.json.

    Falls back to the hardcoded NORMALIZATION_PROFILES if the file is missing,
    malformed, or a specific strategy key is absent.  This allows the calibration
    file to be updated with backtest-derived breakpoints without touching source code.
    """
    calibration_path = path or (_CALIBRATION_DIR / "regime_adjustments.json")
    if not calibration_path.exists():
        logger.warning("Calibration file not found at %s; using hardcoded profiles.", calibration_path)
        return dict(NORMALIZATION_PROFILES)
    try:
        data = json.loads(calibration_path.read_text(encoding="utf-8"))
        raw_profiles = data.get("normalization_profiles", {})
    except Exception as exc:
        logger.warning("Failed to load calibration file %s: %s; using hardcoded profiles.", calibration_path, exc)
        return dict(NORMALIZATION_PROFILES)

    merged: dict[str, NormalizationProfile] = dict(NORMALIZATION_PROFILES)
    for strategy_id, profile_data in raw_profiles.items():
        try:
            merged[strategy_id] = NormalizationProfile(strategy_id=strategy_id, **profile_data)
        except Exception as exc:
            logger.warning("Skipping invalid profile for %s: %s", strategy_id, exc)
    return merged


class StrategySignal(BaseModel):
    ticker: str
    strategy_id: str
    direction: SignalDirection = Field(default="long")
    score_raw: int
    score_normalized: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    horizon: str
    validity_template: str | None = None
    entry_logic: str = ""
    exit_logic: str = ""
    risk_flags: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    data_sufficiency: DataSufficiency = "sufficient"
    normalization_method: NormalizationMethod = "piecewise_linear_v1"
    metadata: dict[str, float | int | str | bool] = Field(default_factory=dict)


class SignalRunRequest(BaseModel):
    tickers: list[str] = Field(default_factory=list)
    strategies: list[str] = Field(default_factory=list)
    asset_type: str = Field(default="stock")


class SignalRunResponse(BaseModel):
    generated_at: str
    signals: list[StrategySignal] = Field(default_factory=list)


class CandidateSignalView(BaseModel):
    strategy_id: str
    score_normalized: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    direction: SignalDirection
    horizon: str = ""
    validity_template: str | None = None
    metadata: dict[str, float | int | str | bool] = Field(default_factory=dict)


class AggregatedCandidate(BaseModel):
    ticker: str
    aggregate_direction: SignalDirection
    aggregate_score: float = Field(ge=0.0, le=1.0)
    aggregate_confidence: float = Field(ge=0.0, le=1.0)
    strategy_signals: list[CandidateSignalView] = Field(default_factory=list)
    agreement_level: AgreementLevel = "low"
    conflicts: list[str] = Field(default_factory=list)
    preliminary_rank: int | None = None
    generated_at: str = ""
    metadata: dict[str, float | int | str | bool] = Field(default_factory=dict)


class SignalSynthesis(BaseModel):
    ticker: str
    overall_direction: SignalDirection
    conviction: str
    signal_alignment: dict[str, float] = Field(default_factory=dict)
    summary: str
    key_supports: list[str] = Field(default_factory=list)
    key_risks: list[str] = Field(default_factory=list)


class SignalPipelineResponse(BaseModel):
    """Full v2 pipeline output: raw signals + merged/ranked candidates."""
    generated_at: str
    tickers_requested: list[str] = Field(default_factory=list)
    strategies_run: list[str] = Field(default_factory=list)
    asset_type: str = "stock"
    signals: list[StrategySignal] = Field(default_factory=list)
    candidates: list[AggregatedCandidate] = Field(default_factory=list)


class PipelineResponse(BaseModel):
    """Canonical end-to-end pipeline output."""
    generated_at: str
    profile_id: str = "default"
    asset_type: str = "stock"
    tickers_requested: list[str] = Field(default_factory=list)
    strategies_run: list[str] = Field(default_factory=list)
    user_profile: UserProfile
    portfolio_snapshot: PortfolioSnapshot
    signals: list[StrategySignal] = Field(default_factory=list)
    candidates: list[AggregatedCandidate] = Field(default_factory=list)
    signal_syntheses: list[SignalSynthesis] = Field(default_factory=list)
    portfolio_decisions: list[PortfolioDecision] = Field(default_factory=list)
    proposal: ProposalResponse
