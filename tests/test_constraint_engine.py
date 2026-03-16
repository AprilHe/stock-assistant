from app.services.candidate_merge_service import merge_signals
from app.services.portfolio_engine import build_portfolio_decisions
from domain.schemas.portfolio import PortfolioSnapshot, UserProfile
from domain.schemas.signals import StrategySignal


def test_portfolio_decision_rejects_avoid_sector_candidate():
    signals = [
        StrategySignal(
            ticker="AAPL",
            strategy_id="breakout",
            direction="long",
            score_raw=80,
            score_normalized=0.66,
            confidence=0.62,
            horizon="3-10d",
            validity_template="expires_after_3_trading_days",
            metadata={"asset_type": "stock", "sector": "Technology", "industry": "Consumer Electronics"},
        )
    ]
    candidates = merge_signals(signals)

    profile = UserProfile(
        avoid_sectors=["Technology"],
        target_invested_ratio=0.75,
        max_single_position=0.08,
        max_new_position_size=0.03,
        max_sector_exposure=0.25,
    )
    snapshot = PortfolioSnapshot(current_invested_ratio=0.50, holdings=[], sector_exposure={})

    decisions = build_portfolio_decisions(candidates, profile, snapshot)

    assert len(decisions) == 1
    decision = decisions[0]
    assert decision.eligible is False
    assert decision.action == "avoid"
    assert "sector_Technology_is_on_avoid_list" in decision.rejection_reasons

