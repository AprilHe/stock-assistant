"""Shared research orchestration service for API, bot, and scheduler."""

from __future__ import annotations

import re
from datetime import datetime, timezone as dt_tz
from datetime import date

from backtesting.engine import run_backtest
from core.strategy_registry import (
    build_prompt_context,
    get_strategy,
    list_strategies,
    list_strategies_by_capability,
)
from core.ai_analysis import (
    analyze_ticker_structured,
    generate_commodity_narrative,
    generate_market_summary,
    generate_us_market_narrative,
    render_ticker_analysis_text,
)
from core.market_data import (
    get_commodity_snapshot,
    get_market_snapshot,
    get_snapshot_for,
    get_us_market_extended_snapshot,
)
from core.news import get_market_news
from domain.schemas.research import (
    BacktestResponse,
    MarketPoint,
    MarketSnapshotResponse,
    ScreenCandidate,
    ScreenResponse,
    StrategyDetailResponse,
    StrategyItem,
    StrategyListResponse,
    SummaryResponse,
    TickerAnalysisStructured,
    TickerAnalysisResponse,
)
from research.strategies.commodity_macro import evaluate_commodity_macro
from research.strategies.breakout import evaluate_breakout
from research.strategies.donchian_breakout import evaluate_donchian_breakout
from research.strategies.mean_reversion import evaluate_mean_reversion
from research.strategies.pullback import evaluate_pullback
from research.strategies.trend_following import evaluate_trend_following

_TICKER_RE = re.compile(r"^[A-Z0-9.\-=^]+$")
_ASSET_TYPES = {"stock", "commodity"}

DEFAULT_STOCK_UNIVERSE = [
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "GOOGL",
    "META",
    "TSLA",
    "JPM",
    "XOM",
    "AVGO",
]

DEFAULT_COMMODITY_UNIVERSE = [
    "GC=F",  # Gold
    "CL=F",  # WTI Oil
    "SI=F",  # Silver
    "HG=F",  # Copper
    "NG=F",  # Natural Gas
]

_EVALUATORS = {
    "breakout": evaluate_breakout,
    "pullback": evaluate_pullback,
    "commodity_macro": evaluate_commodity_macro,
    "trend_following": evaluate_trend_following,
    "mean_reversion": evaluate_mean_reversion,
    "donchian_breakout": evaluate_donchian_breakout,
}


def _to_market_points(raw: dict) -> dict[str, MarketPoint]:
    points: dict[str, MarketPoint] = {}
    for key, val in raw.items():
        points[key] = MarketPoint(
            ticker=val.get("ticker", key),
            price=val.get("price"),
            change_pct=val.get("change_pct"),
            error=val.get("error"),
        )
    return points


def normalize_ticker_or_raise(ticker: str) -> str:
    normalized = ticker.upper().strip()
    if not normalized or not _TICKER_RE.fullmatch(normalized):
        raise ValueError("Invalid ticker symbol.")
    return normalized


def _normalize_tickers(raw_tickers: list[str]) -> list[str]:
    return [normalize_ticker_or_raise(t) for t in raw_tickers]


def _default_universe(asset_type: str) -> list[str]:
    if asset_type == "commodity":
        return list(DEFAULT_COMMODITY_UNIVERSE)
    return list(DEFAULT_STOCK_UNIVERSE)


def _is_commodity_ticker(symbol: str) -> bool:
    return symbol.endswith("=F") or symbol in DEFAULT_COMMODITY_UNIVERSE


def _strategy_asset_type(strategy: str) -> str:
    asset_types = _strategy_asset_types(strategy)
    if not asset_types:
        return "stock"
    return asset_types[0]


def _strategy_asset_types(strategy: str) -> list[str]:
    detail = get_strategy(strategy, capability="screen")
    raw = detail.get("asset_types") or []
    normalized = [str(a).strip() for a in raw if str(a).strip() in _ASSET_TYPES]
    return normalized or ["stock"]


def build_market_snapshot_response() -> MarketSnapshotResponse:
    raw_market_data = get_market_snapshot()
    return MarketSnapshotResponse(market_data=_to_market_points(raw_market_data))


def build_global_summary_response(schedule: str = "daily", language: str = "en") -> SummaryResponse:
    raw_market_data = get_us_market_extended_snapshot()
    news = get_market_news()
    summary = generate_us_market_narrative(raw_market_data, news, schedule=schedule, language=language)
    return SummaryResponse(
        summary=summary,
        market_data=_to_market_points(raw_market_data),
        schedule=schedule,
        language=language,
        requested_tickers=[],
    )


def build_commodity_summary_response(schedule: str = "daily", language: str = "en") -> SummaryResponse:
    raw_market_data = get_commodity_snapshot()
    news = get_market_news(query="commodities gold oil silver copper natural gas")
    summary = generate_commodity_narrative(raw_market_data, news, schedule=schedule, language=language)
    return SummaryResponse(
        summary=summary,
        market_data=_to_market_points(raw_market_data),
        schedule=schedule,
        language=language,
        requested_tickers=[],
    )


def build_watchlist_summary_response(
    watchlist: list[str],
    schedule: str = "daily",
    language: str = "en",
) -> SummaryResponse:
    raw_market_data = get_snapshot_for(watchlist)
    news = get_market_news()
    summary = generate_market_summary(raw_market_data, news, schedule=schedule, language=language)
    return SummaryResponse(
        summary=summary,
        market_data=_to_market_points(raw_market_data),
        schedule=schedule,
        language=language,
        requested_tickers=list(watchlist),
    )


def build_ticker_analysis_response(
    ticker: str,
    strategy: str = "",
) -> TickerAnalysisResponse:
    normalized = normalize_ticker_or_raise(ticker)
    strategy_id = strategy.lower().strip() if strategy else ""
    strategy_name: str | None = None
    strategy_context = ""
    if strategy_id:
        strategy_detail = get_strategy(strategy_id, capability="analysis")
        strategy_name = str(strategy_detail.get("name", strategy_id))
        strategy_context = build_prompt_context(strategy_id)

    structured = analyze_ticker_structured(
        normalized,
        strategy_context=strategy_context,
    )
    analysis = render_ticker_analysis_text(structured, normalized)
    return TickerAnalysisResponse(
        ticker=normalized,
        analysis=analysis,
        analysis_structured=TickerAnalysisStructured(**structured),
        strategy_id=strategy_id or None,
        strategy_name=strategy_name,
    )


def build_strategy_list_response(capability: str = "") -> StrategyListResponse:
    items = list_strategies_by_capability(capability) if capability else list_strategies()
    return StrategyListResponse(
        strategies=[
            StrategyItem(
                id=item["id"],
                name=item["name"],
                summary=item["summary"],
                tags=item["tags"],
                asset_types=item.get("asset_types", []),
                capabilities=item.get("capabilities", {}),
            )
            for item in items
        ]
    )


def build_strategy_detail_response(strategy_id: str, capability: str = "") -> StrategyDetailResponse:
    detail = get_strategy(strategy_id, capability=capability)
    return StrategyDetailResponse(
        id=detail["id"],
        name=detail["name"],
        summary=detail["summary"],
        tags=detail["tags"],
        asset_types=detail.get("asset_types", []),
        capabilities=detail.get("capabilities", {}),
        python_impl=detail.get("python_impl") or None,
        config=detail["config"],
        documentation_md=detail["documentation_md"],
    )


def _parse_iso_date_or_raise(raw_date: str, field_name: str) -> date:
    try:
        return date.fromisoformat(raw_date)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be in YYYY-MM-DD format.") from exc


def build_backtest_response(
    ticker: str,
    strategy: str = "breakout",
    start_date: str = "2024-01-01",
    end_date: str = "2025-01-01",
    initial_cash: float = 10_000.0,
    fee_bps: float = 10.0,
    slippage_bps: float = 5.0,
    stop_loss_pct: float = 8.0,
    take_profit_pct: float = 15.0,
    max_holding_days: int = 20,
) -> BacktestResponse:
    normalized = normalize_ticker_or_raise(ticker)
    normalized_strategy = strategy.lower().strip()
    get_strategy(normalized_strategy, capability="backtest")
    start = _parse_iso_date_or_raise(start_date, "start_date")
    end = _parse_iso_date_or_raise(end_date, "end_date")
    return run_backtest(
        ticker=normalized,
        strategy=normalized_strategy,
        start_date=start,
        end_date=end,
        initial_cash=initial_cash,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
        max_holding_days=max_holding_days,
    )


def build_breakout_screen_response(
    asset_type: str = "stock",
    tickers: list[str] | None = None,
    top_n: int = 5,
) -> ScreenResponse:
    """Backward-compatible wrapper."""
    return build_screen_response(
        strategy="breakout",
        asset_type=asset_type,
        tickers=tickers,
        top_n=top_n,
    )


def build_screen_response(
    strategy: str = "breakout",
    asset_type: str = "stock",
    tickers: list[str] | None = None,
    top_n: int = 5,
) -> ScreenResponse:
    normalized_strategy = strategy.lower().strip()
    normalized_asset_type = asset_type.lower().strip()
    strategy_detail = get_strategy(normalized_strategy, capability="screen")
    if normalized_asset_type not in _ASSET_TYPES:
        raise ValueError("Invalid asset_type. Choose from: stock | commodity")
    if top_n < 1 or top_n > 50:
        raise ValueError("top_n must be between 1 and 50.")
    strategy_asset_types = set(strategy_detail.get("asset_types") or [])
    if strategy_asset_types and normalized_asset_type not in strategy_asset_types:
        raise ValueError(
            f"{normalized_strategy} requires asset_type in: {', '.join(sorted(strategy_asset_types))}"
        )

    requested_tickers = _normalize_tickers(tickers) if tickers else []
    universe = requested_tickers if requested_tickers else _default_universe(normalized_asset_type)
    universe = [
        symbol for symbol in universe
        if _is_commodity_ticker(symbol) == (normalized_asset_type == "commodity")
    ]

    python_impl = str(strategy_detail.get("python_impl", "")).strip()
    evaluator = _EVALUATORS.get(python_impl)
    if evaluator is None:
        raise ValueError(f"Strategy '{normalized_strategy}' has no executable screener implementation yet.")

    candidates: list[ScreenCandidate] = []
    for symbol in universe:
        signal = evaluator(symbol)
        if not signal:
            continue
        candidates.append(
            ScreenCandidate(
                symbol=symbol,
                asset_type=normalized_asset_type,
                strategy=normalized_strategy,
                direction="long",
                score=signal.score,
                confidence=signal.confidence,
                holding_period="days_to_weeks",
                entry_logic=signal.entry_logic,
                exit_logic=signal.exit_logic,
                risk_flags=signal.risk_flags,
                evidence=signal.evidence,
            )
        )

    candidates.sort(key=lambda x: (x.score, x.confidence), reverse=True)
    candidates = candidates[:top_n]

    return ScreenResponse(
        strategy=normalized_strategy,
        asset_type=normalized_asset_type,
        generated_at=datetime.now(dt_tz.utc).isoformat(),
        requested_tickers=requested_tickers,
        candidates=candidates,
    )


def format_screen_response(response: ScreenResponse) -> str:
    if not response.candidates:
        return f"No {response.strategy} candidates right now in your universe."

    lines = [f"{response.strategy.title()} ideas ({response.asset_type})"]
    for idx, candidate in enumerate(response.candidates, 1):
        risk = ", ".join(candidate.risk_flags) if candidate.risk_flags else "none"
        lines.append(
            f"{idx}. {candidate.symbol} | score {candidate.score} | conf {candidate.confidence:.2f}\n"
            f"   Entry: {candidate.entry_logic}\n"
            f"   Exit: {candidate.exit_logic}\n"
            f"   Risks: {risk}"
        )
    return "\n\n".join(lines)


def build_personalized_report(
    watchlist: list[str],
    strategies: list[str],
    report_mode: str,
    schedule: str = "daily",
    language: str = "en",
    top_n: int = 5,
) -> str:
    sections: list[str] = []

    if report_mode in {"summary", "summary+ideas"}:
        summary_response = build_watchlist_summary_response(
            watchlist=watchlist,
            schedule=schedule,
            language=language,
        )
        sections.append(summary_response.summary)

    if report_mode in {"ideas", "summary+ideas"}:
        normalized_strategies = strategies or ["breakout"]
        for strategy in normalized_strategies:
            for strategy_asset_type in _strategy_asset_types(strategy):
                strategy_watchlist = [
                    symbol for symbol in watchlist
                    if _is_commodity_ticker(symbol) == (strategy_asset_type == "commodity")
                ]
                if not strategy_watchlist:
                    continue
                screen_response = build_screen_response(
                    strategy=strategy,
                    asset_type=strategy_asset_type,
                    tickers=strategy_watchlist,
                    top_n=top_n,
                )
                sections.append(format_screen_response(screen_response))

    return "\n\n".join(section for section in sections if section.strip())
