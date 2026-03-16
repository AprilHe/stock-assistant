from core import portfolio_store
from domain.schemas.portfolio import Holding, PortfolioSnapshot, UserProfile


def test_portfolio_store_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_store, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(portfolio_store, "_DB_FILE", tmp_path / "portfolio-test.db")

    profile = UserProfile(
        profile_id="demo",
        preferred_sectors=["Energy"],
        avoid_sectors=["Technology"],
    )
    snapshot = PortfolioSnapshot(
        cash=10_000.0,
        equity_value=20_000.0,
        current_invested_ratio=0.5,
        holdings=[Holding(ticker="XOM", weight=0.05, sector="Energy")],
        sector_exposure={"Energy": 0.05},
    )

    portfolio_store.save_user_profile(profile)
    portfolio_store.save_portfolio_snapshot("demo", snapshot)

    loaded_profile = portfolio_store.get_user_profile("demo")
    loaded_snapshot = portfolio_store.get_portfolio_snapshot("demo")

    assert loaded_profile.profile_id == "demo"
    assert loaded_profile.preferred_sectors == ["Energy"]
    assert loaded_snapshot.holdings[0].ticker == "XOM"
    assert loaded_snapshot.sector_exposure["Energy"] == 0.05

