import sys
from importlib import import_module
from types import SimpleNamespace

sys.modules.setdefault("yfinance", SimpleNamespace(Ticker=lambda *args, **kwargs: None))
sys.modules.setdefault("litellm", SimpleNamespace(completion=lambda *args, **kwargs: None))
sys.modules.setdefault("dotenv", SimpleNamespace(load_dotenv=lambda: None))

report_service = import_module("app.services.report_service")

from domain.schemas.portfolio import PortfolioSnapshot, UserProfile
from domain.schemas.research import MarketPoint, SummaryResponse
from domain.schemas.signals import SignalRunResponse, StrategySignal


def test_build_watchlist_pipeline_merges_stock_and_commodity_buckets(monkeypatch):
    calls: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = []

    def fake_run_signals(*, tickers, strategies, asset_type):
        calls.append((asset_type, tuple(tickers), tuple(strategies)))
        if asset_type == "stock":
            signals = [
                StrategySignal(
                    ticker="AAPL",
                    strategy_id="breakout",
                    direction="long",
                    score_raw=82,
                    score_normalized=0.68,
                    confidence=0.64,
                    horizon="3-10d",
                    validity_template="expires_after_3_trading_days",
                    metadata={"asset_type": "stock", "sector": "Technology"},
                )
            ]
        else:
            signals = [
                StrategySignal(
                    ticker="GC=F",
                    strategy_id="commodity_macro",
                    direction="long",
                    score_raw=78,
                    score_normalized=0.66,
                    confidence=0.61,
                    horizon="5-15d",
                    validity_template="expires_after_3_trading_days",
                    metadata={"asset_type": "commodity", "sector": "commodities"},
                )
            ]
        return SignalRunResponse(generated_at="2026-03-16T09:00:00+00:00", signals=signals)

    monkeypatch.setattr("app.services.signal_service.run_signals", fake_run_signals)

    profile = UserProfile(profile_id="demo")
    snapshot = PortfolioSnapshot(current_invested_ratio=0.2, holdings=[], sector_exposure={})
    monkeypatch.setattr(report_service, "run_pipeline", lambda **kwargs: import_module("app.services.pipeline_service").run_pipeline(
        user_profile=profile,
        portfolio_snapshot=snapshot,
        **kwargs,
    ))

    response = report_service.build_watchlist_pipeline(
        profile_id="demo",
        watchlist=["AAPL", "GC=F"],
        strategies=["breakout", "commodity_macro"],
    )

    assert calls == [
        ("stock", ("AAPL",), ("breakout",)),
        ("commodity", ("GC=F",), ("commodity_macro",)),
    ]
    assert response.asset_type == "mixed"
    assert {candidate.ticker for candidate in response.candidates} == {"AAPL", "GC=F"}
    assert {action.ticker for action in response.proposal.proposed_actions} == {"AAPL", "GC=F"}


def test_build_detailed_report_payload_includes_canonical_proposal_sections(monkeypatch):
    profile = UserProfile(profile_id="demo")
    snapshot = PortfolioSnapshot(current_invested_ratio=0.2, holdings=[], sector_exposure={})

    monkeypatch.setattr(
        report_service,
        "build_watchlist_pipeline",
        lambda **kwargs: import_module("app.services.pipeline_service").run_pipeline(
            tickers=["AAPL"],
            strategies=["breakout"],
            profile_id="demo",
            asset_type="stock",
            user_profile=profile,
            portfolio_snapshot=snapshot,
            precomputed_signals=[
                StrategySignal(
                    ticker="AAPL",
                    strategy_id="breakout",
                    direction="long",
                    score_raw=82,
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
        ),
    )
    monkeypatch.setattr(
        report_service,
        "build_global_summary_response",
        lambda schedule="weekly", language="en": SimpleNamespace(summary="market summary"),
    )
    monkeypatch.setattr(report_service, "_top_market_stock_ideas", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        report_service,
        "build_structured_market_overview",
        lambda **kwargs: SimpleNamespace(model_dump=lambda: {"generated_at": "2026-03-16T09:00:00+00:00"}),
    )
    monkeypatch.setattr(
        report_service,
        "build_structured_featured_idea",
        lambda **kwargs: SimpleNamespace(model_dump=lambda: {"idea_kind": "none", "generated_at": "2026-03-16T09:00:00+00:00"}),
    )

    payload = report_service.build_detailed_report_payload(
        "demo",
        {
            "watchlist": ["AAPL"],
            "strategies": ["breakout"],
            "schedule": "weekly",
            "language": "en",
            "report_sections": ["watchlist", "market"],
            "report_mode": "summary+ideas",
        },
    )

    assert "Decision Brief" in payload["sections"]["watchlist_summary"]
    assert payload["sections"]["proposal"]["proposed_actions"][0]["ticker"] == "AAPL"
    assert payload["sections"]["portfolio_decisions"][0]["ticker"] == "AAPL"
    assert payload["sections"]["strategy_reports"][0]["source"] == "canonical_pipeline"
    assert payload["sections"]["strategy_reports"][0]["items"][0]["ticker"] == "AAPL"


def test_market_overview_uses_canonical_market_pipeline_for_featured_stock(monkeypatch):
    profile = UserProfile(profile_id="demo")
    snapshot = PortfolioSnapshot(current_invested_ratio=0.2, holdings=[], sector_exposure={})

    pipeline = import_module("app.services.pipeline_service").run_pipeline(
        tickers=["AAPL"],
        strategies=["breakout"],
        profile_id="demo",
        asset_type="stock",
        user_profile=profile,
        portfolio_snapshot=snapshot,
        precomputed_signals=[
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
                evidence=["close above breakout level"],
                metadata={"asset_type": "stock", "sector": "Technology"},
            )
        ],
    )

    monkeypatch.setattr(report_service, "build_market_pipeline", lambda profile_id, strategies: pipeline)
    monkeypatch.setattr(
        report_service,
        "build_global_summary_response",
        lambda schedule="daily", language="en": SummaryResponse(
            summary="mixed tape",
            market_data={
                "S&P 500": MarketPoint(ticker="^GSPC", price=100.0, change_pct=0.2),
                "Nasdaq": MarketPoint(ticker="^IXIC", price=100.0, change_pct=-0.1),
                "Technology": MarketPoint(ticker="XLK", price=100.0, change_pct=0.4),
                "Financials": MarketPoint(ticker="XLF", price=100.0, change_pct=0.2),
                "Energy": MarketPoint(ticker="XLE", price=100.0, change_pct=0.3),
                "Utilities": MarketPoint(ticker="XLU", price=100.0, change_pct=0.1),
                "Industrials": MarketPoint(ticker="XLI", price=100.0, change_pct=0.0),
                "Materials": MarketPoint(ticker="XLB", price=100.0, change_pct=0.2),
            },
        ),
    )

    overview = report_service.build_structured_market_overview(
        profile_id="demo",
        strategies=["breakout"],
        schedule="daily",
        language="en",
    )

    assert overview.featured_sector is None
    assert overview.featured_stock is not None
    assert overview.featured_stock.ticker == "AAPL"
    assert overview.featured_stock.price_plan.valid_until is not None


def test_top_market_stock_ideas_exposes_canonical_market_proposal_fields(monkeypatch):
    profile = UserProfile(profile_id="demo")
    snapshot = PortfolioSnapshot(current_invested_ratio=0.2, holdings=[], sector_exposure={})

    pipeline = import_module("app.services.pipeline_service").run_pipeline(
        tickers=["AAPL"],
        strategies=["breakout"],
        profile_id="demo",
        asset_type="stock",
        user_profile=profile,
        portfolio_snapshot=snapshot,
        precomputed_signals=[
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
                evidence=["close above breakout level"],
                metadata={"asset_type": "stock", "sector": "Technology"},
            )
        ],
    )

    monkeypatch.setattr(report_service, "build_market_pipeline", lambda profile_id, strategies: pipeline)

    ideas = report_service._top_market_stock_ideas("demo", ["breakout"], top_n=5)

    assert len(ideas) == 1
    idea = ideas[0]
    assert idea["ticker"] == "AAPL"
    assert idea["signal_summary"]["agreement_level"] == "low"
    assert idea["proposal_validity"]["status"] in {"active", "review_due"}
    assert idea["execution_plan"]["entry_condition"] == "close above breakout level"
    assert idea["portfolio_decision"]["ticker"] == "AAPL"
    assert idea["candidate"]["ticker"] == "AAPL"


def test_render_detailed_report_markdown_uses_canonical_market_stock_ideas():
    markdown = report_service.render_detailed_report_markdown(
        {
            "profile_id": "demo",
            "created_at": "2026-03-16T09:00:00+00:00",
            "report_config": {"report_sections": ["market"], "report_mode": "summary"},
            "sections": {
                "market_summary": "market summary",
                "market_overview_structured": {
                    "generated_at": "2026-03-16T09:00:00+00:00",
                    "risk_tone": "mixed",
                    "summary": "mixed tape",
                },
                "featured_idea_structured": {
                    "idea_kind": "none",
                    "generated_at": "2026-03-16T09:00:00+00:00",
                    "status": "no_featured_idea_today",
                    "reason": "none",
                },
                "market_stock_ideas": [
                    {
                        "ticker": "AAPL",
                        "action": "buy",
                        "strategy": "breakout",
                        "score": 72,
                        "reason": "canonical reason",
                        "signal_summary": {"aggregate_score": 0.72, "agreement_level": "medium"},
                        "proposal_validity": {"status": "active"},
                        "execution_plan": {
                            "entry_range": {"lower_bound": 99.5, "upper_bound": 101.0, "reference": ""},
                            "valid_until": "2026-03-19T09:00:00+00:00",
                        },
                    }
                ],
                "strategy_reports": [],
            },
        }
    )

    assert "AAPL | BUY | breakout | score 72 | canonical reason" in markdown
    assert "agreement=medium aggregate_score=0.72" in markdown
    assert "validity=active" in markdown
    assert "entry=99.5-101.0 valid_until=2026-03-19T09:00:00+00:00" in markdown


def test_build_strategy_reports_from_pipeline_uses_canonical_strategy_views():
    profile = UserProfile(profile_id="demo")
    snapshot = PortfolioSnapshot(current_invested_ratio=0.2, holdings=[], sector_exposure={})

    pipeline = import_module("app.services.pipeline_service").run_pipeline(
        tickers=["AAPL", "GC=F"],
        strategies=["breakout", "commodity_macro"],
        profile_id="demo",
        asset_type="mixed",
        user_profile=profile,
        portfolio_snapshot=snapshot,
        precomputed_signals=[
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
                evidence=["close above breakout level"],
                metadata={"asset_type": "stock", "sector": "Technology"},
            ),
            StrategySignal(
                ticker="GC=F",
                strategy_id="commodity_macro",
                direction="long",
                score_raw=80,
                score_normalized=0.67,
                confidence=0.62,
                horizon="5-15d",
                validity_template="expires_after_3_trading_days",
                entry_logic="macro trend remains supportive",
                exit_logic="macro regime shifts",
                evidence=["macro trend remains supportive"],
                metadata={"asset_type": "commodity", "sector": "commodities"},
            ),
        ],
    )

    reports = report_service.build_strategy_reports_from_pipeline(
        pipeline=pipeline,
        watchlist=["AAPL", "GC=F"],
        strategies=["breakout", "commodity_macro"],
    )

    assert len(reports) == 2
    breakout_report = next(report for report in reports if report["strategy"] == "breakout")
    commodity_report = next(report for report in reports if report["strategy"] == "commodity_macro")
    assert breakout_report["items"][0]["ticker"] == "AAPL"
    assert breakout_report["items"][0]["proposal_validity"]["status"] in {"active", "review_due"}
    assert commodity_report["items"][0]["ticker"] == "GC=F"
    assert commodity_report["items"][0]["execution_plan"]["entry_condition"] == "macro trend remains supportive"


def test_render_detailed_report_markdown_uses_canonical_strategy_reports():
    markdown = report_service.render_detailed_report_markdown(
        {
            "profile_id": "demo",
            "created_at": "2026-03-16T09:00:00+00:00",
            "report_config": {"report_sections": ["watchlist"], "report_mode": "ideas"},
            "sections": {
                "strategy_reports": [
                    {
                        "strategy": "breakout",
                        "asset_type": "stock",
                        "source": "canonical_pipeline",
                        "items": [
                            {
                                "ticker": "AAPL",
                                "action": "buy",
                                "aggregate_score": 0.72,
                                "strategy_score": 0.72,
                                "agreement_level": "medium",
                                "conviction": "medium",
                                "proposal_validity": {"status": "active"},
                                "execution_plan": {
                                    "entry_range": {"lower_bound": 99.5, "upper_bound": 101.0, "reference": ""},
                                    "valid_until": "2026-03-19T09:00:00+00:00",
                                },
                                "reason": "canonical strategy reason",
                            }
                        ],
                    }
                ]
            },
        }
    )

    assert "## Strategy: breakout (stock)" in markdown
    assert "1. AAPL | BUY | aggregate 72 | strategy 72" in markdown
    assert "agreement=medium conviction=medium validity=active" in markdown
    assert "entry=99.5-101.0 valid_until=2026-03-19T09:00:00+00:00" in markdown


def test_build_telegram_ideas_text_uses_canonical_strategy_reports(monkeypatch):
    profile = UserProfile(profile_id="demo")
    snapshot = PortfolioSnapshot(current_invested_ratio=0.2, holdings=[], sector_exposure={})

    monkeypatch.setattr(
        report_service,
        "build_watchlist_pipeline",
        lambda **kwargs: import_module("app.services.pipeline_service").run_pipeline(
            tickers=["AAPL"],
            strategies=["breakout"],
            profile_id="demo",
            asset_type="stock",
            user_profile=profile,
            portfolio_snapshot=snapshot,
            precomputed_signals=[
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
                    evidence=["close above breakout level"],
                    metadata={"asset_type": "stock", "sector": "Technology"},
                )
            ],
        ),
    )

    text = report_service.build_telegram_ideas_text(
        profile_id="demo",
        watchlist=["AAPL"],
        strategies=["breakout"],
        top_n=5,
    )

    assert "## Strategy: breakout (stock)" in text
    assert "AAPL | BUY | aggregate 72 | strategy 72" in text


def test_build_telegram_report_text_uses_renderer_backed_sections(monkeypatch):
    profile = UserProfile(profile_id="demo")
    snapshot = PortfolioSnapshot(current_invested_ratio=0.2, holdings=[], sector_exposure={})

    monkeypatch.setattr(
        report_service,
        "build_watchlist_pipeline",
        lambda **kwargs: import_module("app.services.pipeline_service").run_pipeline(
            tickers=["AAPL"],
            strategies=["breakout"],
            profile_id="demo",
            asset_type="stock",
            user_profile=profile,
            portfolio_snapshot=snapshot,
            precomputed_signals=[
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
                    evidence=["close above breakout level"],
                    metadata={"asset_type": "stock", "sector": "Technology"},
                )
            ],
        ),
    )
    monkeypatch.setattr(
        report_service,
        "build_global_summary_response",
        lambda schedule="daily", language="en": SummaryResponse(
            summary="mixed tape",
            market_data={
                "S&P 500": MarketPoint(ticker="^GSPC", price=100.0, change_pct=0.2),
                "Nasdaq": MarketPoint(ticker="^IXIC", price=100.0, change_pct=-0.1),
                "Technology": MarketPoint(ticker="XLK", price=100.0, change_pct=0.4),
                "Financials": MarketPoint(ticker="XLF", price=100.0, change_pct=0.2),
                "Energy": MarketPoint(ticker="XLE", price=100.0, change_pct=0.3),
                "Utilities": MarketPoint(ticker="XLU", price=100.0, change_pct=0.1),
                "Industrials": MarketPoint(ticker="XLI", price=100.0, change_pct=0.0),
                "Materials": MarketPoint(ticker="XLB", price=100.0, change_pct=0.2),
            },
        ),
    )
    monkeypatch.setattr(
        report_service,
        "build_structured_featured_idea",
        lambda **kwargs: report_service.FeaturedIdeaReport(
            idea_kind="none",
            generated_at="2026-03-16T09:00:00+00:00",
            status="no_featured_idea_today",
            reason="none",
        ),
    )

    text = report_service.build_telegram_report_text(
        "demo",
        {
            "watchlist": ["AAPL"],
            "strategies": ["breakout"],
            "report_mode": "summary+ideas",
            "report_sections": ["watchlist", "market"],
            "schedule": "daily",
            "language": "en",
            "push_mode": "simple",
        },
    )

    assert "Decision Brief" in text
    assert "## Strategy: breakout (stock)" in text
