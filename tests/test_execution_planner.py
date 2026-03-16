from app.services.candidate_merge_service import merge_signals
from app.services.execution_planner import build_proposal_response
from app.services.portfolio_engine import build_portfolio_decisions
from domain.schemas.portfolio import PortfolioSnapshot, UserProfile
from domain.schemas.signals import StrategySignal


def test_execution_planner_builds_plan_for_actionable_buy():
    signals = [
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
            metadata={"asset_type": "stock", "sector": "Energy", "industry": "Oil & Gas Integrated"},
        )
    ]
    candidates = merge_signals(signals)
    profile = UserProfile(
        profile_id="test-profile",
        target_invested_ratio=0.75,
        max_single_position=0.08,
        max_new_position_size=0.03,
        max_sector_exposure=0.25,
    )
    snapshot = PortfolioSnapshot(current_invested_ratio=0.40, holdings=[], sector_exposure={"Energy": 0.10})

    decisions = build_portfolio_decisions(candidates, profile, snapshot)
    proposal = build_proposal_response(
        profile=profile,
        decisions=decisions,
        candidates=candidates,
        signals=signals,
    )

    assert len(proposal.proposed_actions) == 1
    action = proposal.proposed_actions[0]
    assert action.action == "buy"
    assert action.execution_plan is not None
    assert action.execution_plan.entry_style == "breakout_confirmation"
    assert "expires_after_3_trading_days_or_on_breakout_failure" in action.execution_plan.invalidate_if
