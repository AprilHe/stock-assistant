"""Smoke-check the signal -> merge -> synthesis -> portfolio -> execution pipeline."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.pipeline_service import run_pipeline
from domain.schemas.portfolio import PortfolioSnapshot, UserProfile
from domain.schemas.signals import StrategySignal


def _mock_signals() -> list[StrategySignal]:
    return [
        StrategySignal(
            ticker="XOM",
            strategy_id="breakout",
            direction="long",
            score_raw=82,
            score_normalized=0.68,
            confidence=0.64,
            horizon="3-10d",
            validity_template="expires_after_3_trading_days_or_on_breakout_failure",
            entry_logic="close above 20-day high with volume confirmation",
            exit_logic="close back below breakout level",
            evidence=["close above 20-day high", "volume ratio above 1.5x"],
            metadata={
                "asset_type": "stock",
                "sector": "Energy",
                "industry": "Oil & Gas Integrated",
                "signal_family": "trend",
            },
        ),
        StrategySignal(
            ticker="XOM",
            strategy_id="trend_following",
            direction="long",
            score_raw=74,
            score_normalized=0.61,
            confidence=0.58,
            horizon="5-20d",
            validity_template="expires_after_5_trading_days_or_on_trend_break",
            entry_logic="price remains above SMA50 with SMA20>SMA50",
            exit_logic="close below SMA50",
            evidence=["price above SMA50", "SMA20 above SMA50"],
            metadata={
                "asset_type": "stock",
                "sector": "Energy",
                "industry": "Oil & Gas Integrated",
                "signal_family": "trend",
            },
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
            evidence=["RSI oversold", "below lower Bollinger band"],
            metadata={
                "asset_type": "stock",
                "sector": "Technology",
                "industry": "Consumer Electronics",
                "signal_family": "mean_reversion",
            },
        ),
    ]


def main() -> None:
    signals = _mock_signals()
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
        strategies=["breakout", "trend_following", "mean_reversion"],
        profile_id=profile.profile_id,
        asset_type="stock",
        user_profile=profile,
        portfolio_snapshot=snapshot,
        precomputed_signals=signals,
    )
    print(json.dumps(response.model_dump(), indent=2))


if __name__ == "__main__":
    main()
