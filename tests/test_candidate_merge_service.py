from app.services.candidate_merge_service import merge_signals
from domain.schemas.signals import StrategySignal


def test_merge_signals_preserves_sector_metadata_from_strongest_signal():
    signals = [
        StrategySignal(
            ticker="XOM",
            strategy_id="breakout",
            direction="long",
            score_raw=82,
            score_normalized=0.68,
            confidence=0.64,
            horizon="3-10d",
            validity_template="expires_after_3_trading_days",
            metadata={"asset_type": "stock", "sector": "Energy", "signal_family": "trend"},
        ),
        StrategySignal(
            ticker="XOM",
            strategy_id="trend_following",
            direction="long",
            score_raw=74,
            score_normalized=0.61,
            confidence=0.58,
            horizon="5-20d",
            validity_template="expires_after_5_trading_days",
            metadata={"asset_type": "stock", "sector": "Energy", "signal_family": "trend"},
        ),
    ]

    candidates = merge_signals(signals)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.metadata["sector"] == "Energy"
    assert candidate.metadata["primary_strategy_id"] == "breakout"
    assert candidate.strategy_signals[0].metadata["signal_family"] == "trend"

