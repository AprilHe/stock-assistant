"""Canonical pipeline orchestration service."""

from __future__ import annotations

from datetime import datetime, timezone as dt_tz

from app.services.candidate_merge_service import merge_signals
from app.services.execution_planner import build_proposal_response
from app.services.portfolio_engine import build_portfolio_decisions
from app.services.signal_synthesis import synthesize_candidates
from core.portfolio_store import get_portfolio_snapshot, get_user_profile
from domain.schemas.portfolio import PortfolioSnapshot, UserProfile
from domain.schemas.signals import PipelineResponse, StrategySignal


def _normalize_input(values: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = str(value).strip()
        if not cleaned:
            continue
        if cleaned in seen:
            continue
        seen.add(cleaned)
        normalized.append(cleaned)
    return normalized


def run_pipeline(
    *,
    tickers: list[str],
    strategies: list[str],
    profile_id: str = "default",
    asset_type: str = "stock",
    user_profile: UserProfile | None = None,
    portfolio_snapshot: PortfolioSnapshot | None = None,
    precomputed_signals: list[StrategySignal] | None = None,
) -> PipelineResponse:
    """Run the full deterministic pipeline for one profile/universe."""
    normalized_tickers = _normalize_input(tickers)
    normalized_strategies = _normalize_input(strategies)
    normalized_asset_type = str(asset_type or "stock").lower().strip()

    profile = user_profile or get_user_profile(profile_id)
    snapshot = portfolio_snapshot or get_portfolio_snapshot(profile.profile_id)

    if precomputed_signals is None:
        from app.services.signal_service import run_signals

        signal_response = run_signals(
            tickers=normalized_tickers,
            strategies=normalized_strategies,
            asset_type=normalized_asset_type,
        )
        signals = signal_response.signals
    else:
        signals = list(precomputed_signals)

    candidates = merge_signals(signals)
    signal_syntheses = synthesize_candidates(candidates, signals)
    portfolio_decisions = build_portfolio_decisions(candidates, profile, snapshot)
    proposal = build_proposal_response(
        profile=profile,
        decisions=portfolio_decisions,
        candidates=candidates,
        signals=signals,
    )

    return PipelineResponse(
        generated_at=datetime.now(dt_tz.utc).isoformat(),
        profile_id=profile.profile_id,
        asset_type=normalized_asset_type,
        tickers_requested=normalized_tickers,
        strategies_run=normalized_strategies,
        user_profile=profile,
        portfolio_snapshot=snapshot,
        signals=signals,
        candidates=candidates,
        signal_syntheses=signal_syntheses,
        portfolio_decisions=portfolio_decisions,
        proposal=proposal,
    )
