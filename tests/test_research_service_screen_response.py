import sys
from types import SimpleNamespace

sys.modules.setdefault("yfinance", SimpleNamespace(Ticker=lambda *args, **kwargs: None))
sys.modules.setdefault("litellm", SimpleNamespace(completion=lambda *args, **kwargs: None))
sys.modules.setdefault("dotenv", SimpleNamespace(load_dotenv=lambda: None))

from app.services import research_service
from domain.schemas.signals import SignalRunResponse, StrategySignal


def test_build_screen_response_uses_canonical_signal_adapter(monkeypatch):
    monkeypatch.setattr(
        "app.services.signal_service.run_signals",
        lambda *, tickers, strategies, asset_type: SignalRunResponse(
            generated_at="2026-03-16T09:00:00+00:00",
            signals=[
                StrategySignal(
                    ticker="AAPL",
                    strategy_id="breakout",
                    direction="long",
                    score_raw=84,
                    score_normalized=0.72,
                    confidence=0.66,
                    horizon="3-10d",
                    validity_template="expires_after_3_trading_days",
                    entry_logic="close above breakout level",
                    exit_logic="close below breakout level",
                    risk_flags=["extended_after_breakout"],
                    evidence=["close above breakout level"],
                    metadata={"asset_type": "stock", "sector": "Technology"},
                )
            ],
        ),
    )

    response = research_service.build_screen_response(
        strategy="breakout",
        asset_type="stock",
        tickers=["AAPL"],
        top_n=5,
    )

    assert response.strategy == "breakout"
    assert response.candidates[0].symbol == "AAPL"
    assert response.candidates[0].score == 84
    assert response.candidates[0].holding_period == "3-10d"
    assert response.candidates[0].entry_logic == "close above breakout level"
