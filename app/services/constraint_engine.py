"""Portfolio constraint evaluation for aggregated candidates."""

from __future__ import annotations

from dataclasses import dataclass, field

from domain.schemas.portfolio import Holding, PortfolioSnapshot, UserProfile
from domain.schemas.signals import AggregatedCandidate

MIN_CANDIDATE_SCORE = 0.50
_AGREEMENT_MULTIPLIER = {
    "high": 1.00,
    "medium": 0.85,
    "low": 0.70,
}


@dataclass
class ConstraintAssessment:
    ticker: str
    eligible: bool
    current_weight: float
    target_weight: float
    sector: str = ""
    sizing_method: str = ""
    portfolio_rationale: list[str] = field(default_factory=list)
    constraints_applied: list[str] = field(default_factory=list)
    rejection_reasons: list[str] = field(default_factory=list)


def _holding_by_ticker(snapshot: PortfolioSnapshot, ticker: str) -> Holding | None:
    for holding in snapshot.holdings:
        if holding.ticker == ticker:
            return holding
    return None


def _candidate_sector(candidate: AggregatedCandidate, holding: Holding | None) -> str:
    if holding and holding.sector:
        return holding.sector
    sector = candidate.metadata.get("sector", "")
    if sector:
        return str(sector)
    return ""


def _invested_room(profile: UserProfile, snapshot: PortfolioSnapshot) -> float:
    return max(0.0, profile.target_invested_ratio - snapshot.current_invested_ratio)


def _sector_room(profile: UserProfile, snapshot: PortfolioSnapshot, sector: str, current_weight: float) -> float:
    if not sector:
        return profile.max_sector_exposure
    current_sector_weight = snapshot.sector_exposure.get(sector, 0.0)
    effective_sector_weight = max(0.0, current_sector_weight - current_weight)
    return max(0.0, profile.max_sector_exposure - effective_sector_weight)


def _conviction_multiplier(candidate: AggregatedCandidate) -> float:
    score_component = candidate.aggregate_score * 0.65
    confidence_component = candidate.aggregate_confidence * 0.35
    raw = score_component + confidence_component
    agreement = _AGREEMENT_MULTIPLIER.get(candidate.agreement_level, 0.70)
    return max(0.35, min(1.0, raw * agreement))


def assess_candidate_constraints(
    candidate: AggregatedCandidate,
    profile: UserProfile,
    snapshot: PortfolioSnapshot,
) -> ConstraintAssessment:
    """Evaluate whether a candidate fits profile and portfolio constraints."""
    holding = _holding_by_ticker(snapshot, candidate.ticker)
    current_weight = holding.weight if holding else 0.0
    sector = _candidate_sector(candidate, holding)

    constraints_applied: list[str] = []
    rejection_reasons: list[str] = []
    rationale: list[str] = []

    if candidate.aggregate_direction != "long":
        if candidate.aggregate_direction == "short" and not profile.allow_shorting:
            rejection_reasons.append("short_signals_not_allowed_by_profile")
        else:
            rejection_reasons.append("aggregate_direction_not_actionable_for_long_portfolio")

    if candidate.aggregate_score < MIN_CANDIDATE_SCORE:
        rejection_reasons.append("aggregate_score_below_minimum_threshold")
    else:
        rationale.append(
            f"aggregate score {candidate.aggregate_score:.2f} cleared the minimum candidate threshold"
        )

    if candidate.ticker in profile.restricted_tickers:
        rejection_reasons.append("ticker_is_restricted_in_profile")

    if sector and sector in profile.avoid_sectors:
        rejection_reasons.append(f"sector_{sector}_is_on_avoid_list")

    if sector and sector in profile.preferred_sectors:
        rationale.append(f"sector {sector} is preferred in the user profile")

    single_name_room = max(0.0, profile.max_single_position - current_weight)
    invested_room = _invested_room(profile, snapshot)
    sector_room = _sector_room(profile, snapshot, sector, current_weight)

    constraints_applied.append(f"max_single_position={profile.max_single_position:.2f}")
    constraints_applied.append(f"target_invested_ratio={profile.target_invested_ratio:.2f}")
    constraints_applied.append(f"max_sector_exposure={profile.max_sector_exposure:.2f}")

    if holding is None and invested_room <= 0:
        rejection_reasons.append("no_invested_ratio_capacity_for_new_positions")
    if single_name_room <= 0:
        rejection_reasons.append("position_already_at_max_single_position")
    if sector and sector_room <= 0:
        rejection_reasons.append(f"sector_{sector}_at_max_exposure")

    if rejection_reasons:
        return ConstraintAssessment(
            ticker=candidate.ticker,
            eligible=False,
            current_weight=current_weight,
            target_weight=current_weight,
            sector=sector,
            sizing_method="rejected_by_constraints",
            portfolio_rationale=rationale,
            constraints_applied=constraints_applied,
            rejection_reasons=rejection_reasons,
        )

    conviction = _conviction_multiplier(candidate)
    base_increment = profile.max_new_position_size * conviction
    desired_weight = current_weight + base_increment
    target_weight = min(
        desired_weight,
        profile.max_single_position,
        current_weight + single_name_room,
        current_weight + sector_room,
    )
    if holding is None:
        target_weight = min(target_weight, invested_room)
    else:
        target_weight = min(target_weight, current_weight + invested_room)

    target_weight = max(current_weight, round(target_weight, 4))

    if target_weight <= current_weight:
        rejection_reasons.append("no_remaining_capacity_after_constraints")
        return ConstraintAssessment(
            ticker=candidate.ticker,
            eligible=False,
            current_weight=current_weight,
            target_weight=current_weight,
            sector=sector,
            sizing_method="rejected_by_constraints",
            portfolio_rationale=rationale,
            constraints_applied=constraints_applied,
            rejection_reasons=rejection_reasons,
        )

    rationale.append(
        f"target weight scaled by signal quality ({candidate.aggregate_score:.2f}) and confidence "
        f"({candidate.aggregate_confidence:.2f})"
    )
    if candidate.conflicts:
        rationale.append("conflicting strategy signals kept size below the max new-position budget")

    return ConstraintAssessment(
        ticker=candidate.ticker,
        eligible=True,
        current_weight=current_weight,
        target_weight=target_weight,
        sector=sector,
        sizing_method="signal_strength_capped_by_profile_constraints",
        portfolio_rationale=rationale,
        constraints_applied=constraints_applied,
        rejection_reasons=[],
    )
