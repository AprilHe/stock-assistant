from types import SimpleNamespace

from app.services.proposal_service import build_latest_candidates, build_latest_proposal, build_proposal
from domain.schemas.portfolio import PortfolioSnapshot, UserProfile
from domain.schemas.signals import StrategySignal


def test_build_proposal_returns_canonical_proposal_response():
    proposal = build_proposal(
        tickers=["XOM"],
        strategies=["breakout"],
        profile_id="demo",
        asset_type="stock",
        user_profile=UserProfile(profile_id="demo"),
        portfolio_snapshot=PortfolioSnapshot(current_invested_ratio=0.25, holdings=[], sector_exposure={}),
        precomputed_signals=[
            StrategySignal(
                ticker="XOM",
                strategy_id="breakout",
                direction="long",
                score_raw=84,
                score_normalized=0.69,
                confidence=0.65,
                horizon="3-10d",
                validity_template="expires_after_3_trading_days_or_on_breakout_failure",
                entry_logic="close above 20-day high with volume confirmation",
                exit_logic="close below breakout level",
                evidence=["close above 20-day high"],
                metadata={"asset_type": "stock", "sector": "Energy"},
            )
        ],
    )

    assert proposal.profile_id == "demo"
    assert proposal.proposed_actions
    assert proposal.proposed_actions[0].ticker == "XOM"
    assert proposal.proposed_actions[0].proposal_validity is not None


def test_build_latest_proposal_uses_saved_preferences(monkeypatch):
    proposal = build_proposal(
        tickers=["AAPL"],
        strategies=["breakout"],
        profile_id="demo",
        asset_type="stock",
        user_profile=UserProfile(profile_id="demo"),
        portfolio_snapshot=PortfolioSnapshot(current_invested_ratio=0.25, holdings=[], sector_exposure={}),
        precomputed_signals=[
            StrategySignal(
                ticker="AAPL",
                strategy_id="breakout",
                direction="long",
                score_raw=83,
                score_normalized=0.68,
                confidence=0.64,
                horizon="3-10d",
                validity_template="expires_after_3_trading_days",
                entry_logic="close above breakout level",
                exit_logic="close below breakout level",
                evidence=["close above breakout level"],
                metadata={"asset_type": "stock", "sector": "Technology"},
            )
        ],
    )

    monkeypatch.setattr(
        "app.services.proposal_service.get_prefs",
        lambda profile_id: {"watchlist": ["AAPL"], "strategies": ["breakout"]},
    )
    monkeypatch.setattr(
        "app.services.report_service.build_watchlist_pipeline",
        lambda profile_id, watchlist, strategies: SimpleNamespace(proposal=proposal),
    )

    latest = build_latest_proposal("demo")

    assert latest.profile_id == "demo"
    assert latest.proposed_actions[0].ticker == "AAPL"


def test_build_latest_candidates_uses_saved_preferences(monkeypatch):
    proposal = build_proposal(
        tickers=["AAPL"],
        strategies=["breakout"],
        profile_id="demo",
        asset_type="stock",
        user_profile=UserProfile(profile_id="demo"),
        portfolio_snapshot=PortfolioSnapshot(current_invested_ratio=0.25, holdings=[], sector_exposure={}),
        precomputed_signals=[
            StrategySignal(
                ticker="AAPL",
                strategy_id="breakout",
                direction="long",
                score_raw=83,
                score_normalized=0.68,
                confidence=0.64,
                horizon="3-10d",
                validity_template="expires_after_3_trading_days",
                entry_logic="close above breakout level",
                exit_logic="close below breakout level",
                evidence=["close above breakout level"],
                metadata={"asset_type": "stock", "sector": "Technology"},
            )
        ],
    )
    pipeline = SimpleNamespace(
        profile_id="demo",
        candidates=[SimpleNamespace(ticker="AAPL")],
        proposal=proposal,
    )

    monkeypatch.setattr(
        "app.services.proposal_service.get_prefs",
        lambda profile_id: {"watchlist": ["AAPL"], "strategies": ["breakout"]},
    )
    monkeypatch.setattr(
        "app.services.report_service.build_watchlist_pipeline",
        lambda profile_id, watchlist, strategies: pipeline,
    )

    latest = build_latest_candidates("demo")

    assert latest.profile_id == "demo"
    assert latest.candidates[0].ticker == "AAPL"
