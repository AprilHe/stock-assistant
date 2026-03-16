"""Portfolio decision engine built on merged strategy candidates."""

from __future__ import annotations

from domain.schemas.portfolio import Holding, PortfolioDecision, PortfolioSnapshot, UserProfile
from domain.schemas.signals import AggregatedCandidate

from app.services.constraint_engine import assess_candidate_constraints


def _copy_snapshot(snapshot: PortfolioSnapshot) -> PortfolioSnapshot:
    return PortfolioSnapshot(
        cash=snapshot.cash,
        equity_value=snapshot.equity_value,
        current_invested_ratio=snapshot.current_invested_ratio,
        holdings=[
            Holding(
                ticker=holding.ticker,
                weight=holding.weight,
                sector=holding.sector,
                beta_bucket=holding.beta_bucket,
            )
            for holding in snapshot.holdings
        ],
        sector_exposure=dict(snapshot.sector_exposure),
    )


def _upsert_holding(snapshot: PortfolioSnapshot, ticker: str, target_weight: float, sector: str = "") -> None:
    for holding in snapshot.holdings:
        if holding.ticker == ticker:
            prior_weight = holding.weight
            holding.weight = target_weight
            if sector and not holding.sector:
                holding.sector = sector
            if snapshot.current_invested_ratio >= 0:
                snapshot.current_invested_ratio = max(
                    0.0,
                    round(snapshot.current_invested_ratio + (target_weight - prior_weight), 4),
                )
            if sector:
                snapshot.sector_exposure[sector] = round(
                    snapshot.sector_exposure.get(sector, 0.0) + (target_weight - prior_weight),
                    4,
                )
            return

    snapshot.holdings.append(
        Holding(
            ticker=ticker,
            weight=target_weight,
            sector=sector,
        )
    )
    snapshot.current_invested_ratio = round(snapshot.current_invested_ratio + target_weight, 4)
    if sector:
        snapshot.sector_exposure[sector] = round(snapshot.sector_exposure.get(sector, 0.0) + target_weight, 4)


def _decision_action(current_weight: float, eligible: bool, target_weight: float) -> str:
    if not eligible:
        return "hold" if current_weight > 0 else "avoid"
    if current_weight > 0:
        return "add" if target_weight > current_weight else "hold"
    return "buy"


def build_portfolio_decisions(
    candidates: list[AggregatedCandidate],
    profile: UserProfile,
    snapshot: PortfolioSnapshot,
) -> list[PortfolioDecision]:
    """Turn ranked merged candidates into portfolio-aware decisions."""
    working_snapshot = _copy_snapshot(snapshot)
    ranked_candidates = sorted(
        candidates,
        key=lambda item: (item.aggregate_score, item.aggregate_confidence),
        reverse=True,
    )

    decisions: list[PortfolioDecision] = []
    actionable_rank = 0

    for candidate in ranked_candidates:
        assessment = assess_candidate_constraints(candidate, profile, working_snapshot)
        action = _decision_action(
            current_weight=assessment.current_weight,
            eligible=assessment.eligible,
            target_weight=assessment.target_weight,
        )

        if assessment.eligible:
            actionable_rank += 1
            _upsert_holding(
                working_snapshot,
                ticker=candidate.ticker,
                target_weight=assessment.target_weight,
                sector=assessment.sector,
            )

        decisions.append(
            PortfolioDecision(
                ticker=candidate.ticker,
                eligible=assessment.eligible,
                action=action,
                target_weight=assessment.target_weight,
                sizing_method=assessment.sizing_method,
                rank_within_candidates=actionable_rank if assessment.eligible else None,
                portfolio_rationale=assessment.portfolio_rationale,
                constraints_applied=assessment.constraints_applied,
                rejection_reasons=assessment.rejection_reasons,
            )
        )

    return decisions
