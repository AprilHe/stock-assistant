from app.services.candidate_merge_service import merge_signals
from app.services.signal_synthesis import synthesize_candidates
from domain.schemas.signals import StrategySignal


def test_signal_synthesis_explains_alignment_and_risks():
    signals = [
        StrategySignal(
            ticker="XOM",
            strategy_id="breakout",
            direction="long",
            score_raw=84,
            score_normalized=0.69,
            confidence=0.65,
            horizon="3-10d",
            validity_template="expires_after_3_trading_days",
            evidence=["close above 20-day high", "volume ratio above 1.5x"],
            risk_flags=["extended_after_breakout"],
            metadata={"asset_type": "stock", "sector": "Energy"},
        ),
        StrategySignal(
            ticker="XOM",
            strategy_id="trend_following",
            direction="long",
            score_raw=76,
            score_normalized=0.62,
            confidence=0.59,
            horizon="5-20d",
            validity_template="expires_after_5_trading_days",
            evidence=["price above SMA50"],
            metadata={"asset_type": "stock", "sector": "Energy"},
        ),
    ]

    candidates = merge_signals(signals)
    syntheses = synthesize_candidates(candidates, signals)

    assert len(syntheses) == 1
    synthesis = syntheses[0]
    assert synthesis.ticker == "XOM"
    assert synthesis.signal_alignment["breakout"] == 0.69
    assert synthesis.key_supports
    assert "Energy" in " ".join(synthesis.key_supports)
    assert "extended_after_breakout" in synthesis.key_risks
    assert "Long bias" in synthesis.summary

