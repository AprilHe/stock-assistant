from app.services.pipeline_service import run_pipeline
from domain.schemas.portfolio import PortfolioSnapshot, UserProfile
from domain.schemas.signals import StrategySignal


def test_pipeline_service_returns_syntheses_decisions_and_proposal():
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
            evidence=["close above 20-day high", "volume ratio above 1.5x"],
            metadata={"asset_type": "stock", "sector": "Energy", "industry": "Oil & Gas Integrated"},
        ),
        StrategySignal(
            ticker="AAPL",
            strategy_id="mean_reversion",
            direction="long",
            score_raw=70,
            score_normalized=0.59,
            confidence=0.55,
            horizon="1-5d",
            validity_template="expires_after_2_trading_days_or_on_sma20_reversion",
            entry_logic="oversold versus lower band with RSI support",
            exit_logic="exit on failed reversion",
            evidence=["RSI oversold"],
            metadata={"asset_type": "stock", "sector": "Technology", "industry": "Consumer Electronics"},
        ),
    ]
    profile = UserProfile(
        profile_id="demo",
        preferred_sectors=["Energy"],
        avoid_sectors=["Technology"],
        target_invested_ratio=0.75,
        max_single_position=0.08,
        max_new_position_size=0.03,
        max_sector_exposure=0.25,
    )
    snapshot = PortfolioSnapshot(
        cash=25_000.0,
        equity_value=75_000.0,
        current_invested_ratio=0.50,
        holdings=[],
        sector_exposure={"Energy": 0.12},
    )

    response = run_pipeline(
        tickers=["XOM", "AAPL"],
        strategies=["breakout", "mean_reversion"],
        profile_id="demo",
        asset_type="stock",
        user_profile=profile,
        portfolio_snapshot=snapshot,
        precomputed_signals=signals,
    )

    assert response.profile_id == "demo"
    assert len(response.candidates) == 2
    assert len(response.signal_syntheses) == 2
    assert len(response.portfolio_decisions) == 2
    assert response.proposal.proposed_actions
    assert response.proposal.proposed_actions[0].proposal_validity is not None
