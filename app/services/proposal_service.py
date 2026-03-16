"""Canonical proposal service built on top of the deterministic pipeline."""

from __future__ import annotations

from app.services.pipeline_service import run_pipeline
from core.preferences import get_prefs
from domain.schemas.portfolio import PortfolioSnapshot, UserProfile
from domain.schemas.proposal import ProposalResponse
from domain.schemas.signals import PipelineResponse, StrategySignal


def build_proposal(
    *,
    tickers: list[str],
    strategies: list[str],
    profile_id: str = "default",
    asset_type: str = "stock",
    user_profile: UserProfile | None = None,
    portfolio_snapshot: PortfolioSnapshot | None = None,
    precomputed_signals: list[StrategySignal] | None = None,
) -> ProposalResponse:
    """Build the canonical proposal object for a ticker universe."""
    pipeline = run_pipeline(
        tickers=tickers,
        strategies=strategies,
        profile_id=profile_id,
        asset_type=asset_type,
        user_profile=user_profile,
        portfolio_snapshot=portfolio_snapshot,
        precomputed_signals=precomputed_signals,
    )
    return pipeline.proposal


def build_latest_proposal(profile_id: str = "default") -> ProposalResponse:
    """Build the latest canonical proposal from a saved profile's preferences."""
    return build_latest_candidates(profile_id).proposal


def build_latest_candidates(profile_id: str = "default") -> PipelineResponse:
    """Build the latest canonical watchlist pipeline from saved preferences."""
    from app.services.report_service import build_watchlist_pipeline

    prefs = get_prefs(profile_id)
    watchlist = list(prefs.get("watchlist", []))
    strategies = list(prefs.get("strategies", []))

    return build_watchlist_pipeline(
        profile_id=profile_id,
        watchlist=watchlist,
        strategies=strategies,
    )
