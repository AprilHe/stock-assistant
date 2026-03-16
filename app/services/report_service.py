"""Report composition, archival, and delivery formatting."""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone as dt_tz
from pathlib import Path
from types import SimpleNamespace
from typing import Literal

from app.services.pipeline_service import run_pipeline
from app.renderers.proposal_renderer import (
    render_market_stock_ideas_markdown,
    render_strategy_report_markdown,
    render_strategy_reports_markdown,
)
from core.market_data import get_snapshot_for
from app.services.research_service import (
    DEFAULT_COMMODITY_UNIVERSE,
    DEFAULT_STOCK_UNIVERSE,
    _is_commodity_ticker,
    _strategy_asset_types,
    build_commodity_summary_response,
    build_global_summary_response,
    build_watchlist_summary_response,
)
from domain.schemas.report import (
    FeaturedIdeaReport,
    FeaturedSectorIdea,
    FeaturedStockIdea,
    MarketOverviewReport,
    PricePlan,
    WatchlistReportItem,
    WatchlistSummaryReport,
)
from domain.schemas.signals import PipelineResponse

REPORTS_DIR = Path(__file__).resolve().parents[2] / "reports"
REPORT_SECTION_OPTIONS = ("watchlist", "market", "commodity")
REPORT_MODE_OPTIONS = ("summary", "ideas", "summary+ideas")
PUSH_DETAIL_OPTIONS = ("brief", "detailed", "simple", "full")


def _dedupe_preserving_order(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = str(value).strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        deduped.append(cleaned)
    return deduped


def _watchlist_asset_buckets(
    watchlist: list[str],
    strategies: list[str],
) -> list[tuple[str, list[str], list[str]]]:
    normalized_watchlist = _dedupe_preserving_order(watchlist)
    normalized_strategies = _dedupe_preserving_order(strategies or ["breakout"])

    stock_tickers = [ticker for ticker in normalized_watchlist if not _is_commodity_ticker(ticker)]
    commodity_tickers = [ticker for ticker in normalized_watchlist if _is_commodity_ticker(ticker)]
    stock_strategies = [strategy for strategy in normalized_strategies if "stock" in _strategy_asset_types(strategy)]
    commodity_strategies = [
        strategy for strategy in normalized_strategies
        if "commodity" in _strategy_asset_types(strategy)
    ]

    buckets: list[tuple[str, list[str], list[str]]] = []
    if stock_tickers and stock_strategies:
        buckets.append(("stock", stock_tickers, stock_strategies))
    if commodity_tickers and commodity_strategies:
        buckets.append(("commodity", commodity_tickers, commodity_strategies))
    return buckets


def _watchlist_pipeline_asset_type(watchlist: list[str]) -> str:
    has_stock = any(not _is_commodity_ticker(ticker) for ticker in watchlist)
    has_commodity = any(_is_commodity_ticker(ticker) for ticker in watchlist)
    if has_stock and has_commodity:
        return "mixed"
    if has_commodity:
        return "commodity"
    return "stock"


def build_watchlist_pipeline(
    profile_id: str,
    watchlist: list[str],
    strategies: list[str],
) -> PipelineResponse:
    """Run the canonical watchlist pipeline across stock and commodity buckets."""
    from app.services.signal_service import run_signals

    normalized_watchlist = _dedupe_preserving_order(watchlist)
    normalized_strategies = _dedupe_preserving_order(strategies or ["breakout"])

    all_signals = []
    for asset_type, bucket_tickers, bucket_strategies in _watchlist_asset_buckets(
        normalized_watchlist,
        normalized_strategies,
    ):
        signal_response = run_signals(
            tickers=bucket_tickers,
            strategies=bucket_strategies,
            asset_type=asset_type,
        )
        all_signals.extend(signal_response.signals)

    return run_pipeline(
        tickers=normalized_watchlist,
        strategies=normalized_strategies,
        profile_id=profile_id,
        asset_type=_watchlist_pipeline_asset_type(normalized_watchlist),
        precomputed_signals=all_signals,
    )


def build_market_pipeline(
    profile_id: str,
    strategies: list[str],
) -> PipelineResponse | None:
    """Run the canonical market-stock pipeline over the default stock universe."""
    stock_strategies = [
        strategy for strategy in _dedupe_preserving_order(strategies or ["breakout"])
        if "stock" in _strategy_asset_types(strategy)
    ]
    if not stock_strategies:
        return None

    return run_pipeline(
        tickers=DEFAULT_STOCK_UNIVERSE,
        strategies=stock_strategies,
        profile_id=profile_id,
        asset_type="stock",
    )


def build_commodity_pipeline(
    profile_id: str,
    strategies: list[str],
) -> PipelineResponse | None:
    """Run the canonical commodity pipeline over the default commodity universe."""
    commodity_strategies = [
        strategy for strategy in _dedupe_preserving_order(strategies or ["commodity_macro"])
        if "commodity" in _strategy_asset_types(strategy)
    ]
    if not commodity_strategies:
        return None

    return run_pipeline(
        tickers=DEFAULT_COMMODITY_UNIVERSE,
        strategies=commodity_strategies,
        profile_id=profile_id,
        asset_type="commodity",
    )


def build_strategy_reports_from_pipeline(
    *,
    pipeline: PipelineResponse,
    watchlist: list[str],
    strategies: list[str],
    top_n: int = 5,
) -> list[dict]:
    """Project canonical watchlist pipeline data into per-strategy report sections."""
    normalized_watchlist = _dedupe_preserving_order(watchlist)
    normalized_strategies = _dedupe_preserving_order(strategies or ["breakout"])

    candidates_by_ticker = {candidate.ticker: candidate for candidate in pipeline.candidates}
    syntheses_by_ticker = {synthesis.ticker: synthesis for synthesis in pipeline.signal_syntheses}
    decisions_by_ticker = {decision.ticker: decision for decision in pipeline.portfolio_decisions}
    actions_by_ticker = {action.ticker: action for action in pipeline.proposal.proposed_actions}

    reports: list[dict] = []
    for strategy in normalized_strategies:
        for asset_type in _strategy_asset_types(strategy):
            items: list[dict] = []
            for ticker in normalized_watchlist:
                if _is_commodity_ticker(ticker) != (asset_type == "commodity"):
                    continue

                candidate = candidates_by_ticker.get(ticker)
                action = actions_by_ticker.get(ticker)
                if candidate is None or action is None:
                    continue

                strategy_signal = next(
                    (signal for signal in candidate.strategy_signals if signal.strategy_id == strategy),
                    None,
                )
                if strategy_signal is None:
                    continue

                synthesis = syntheses_by_ticker.get(ticker)
                decision = decisions_by_ticker.get(ticker)
                execution_plan = action.execution_plan
                reason_parts = [action.reason]
                if synthesis is not None and synthesis.summary:
                    reason_parts.append(synthesis.summary)

                items.append(
                    {
                        "ticker": ticker,
                        "action": action.action,
                        "conviction": action.conviction,
                        "aggregate_score": candidate.aggregate_score,
                        "strategy_score": strategy_signal.score_normalized,
                        "aggregate_confidence": candidate.aggregate_confidence,
                        "strategy_confidence": strategy_signal.confidence,
                        "agreement_level": candidate.agreement_level,
                        "reason": " | ".join(part for part in reason_parts if part),
                        "proposal_validity": (
                            action.proposal_validity.model_dump() if action.proposal_validity else None
                        ),
                        "execution_plan": execution_plan.model_dump() if execution_plan else None,
                        "portfolio_decision": decision.model_dump() if decision else None,
                        "synthesis": synthesis.model_dump() if synthesis is not None else None,
                    }
                )

            items.sort(
                key=lambda item: (item.get("aggregate_score", 0.0), item.get("strategy_score", 0.0)),
                reverse=True,
            )
            reports.append(
                {
                    "strategy": strategy,
                    "asset_type": asset_type,
                    "generated_at": pipeline.generated_at,
                    "source": "canonical_pipeline",
                    "items": items[:top_n],
                    "status": None if items else "no_actionable_idea",
                    "reason": None if items else "no candidate for this strategy cleared the canonical pipeline",
                }
            )

    return reports


def build_telegram_report_text(profile_id: str, prefs: dict) -> str:
    """Build a concise Telegram report from canonical pipeline-backed sections."""
    watchlist = prefs["watchlist"]
    strategies = prefs.get("strategies", ["breakout"])
    schedule = prefs.get("schedule", "daily")
    language = prefs.get("language", "en")
    report_mode = _normalize_report_mode(prefs.get("report_mode", "summary"))
    report_sections = _normalize_sections(prefs.get("report_sections", ["watchlist"]))
    detail_level = "detailed" if prefs.get("push_mode", "simple") == "full" else "brief"

    watchlist_pipeline = build_watchlist_pipeline(
        profile_id=profile_id,
        watchlist=watchlist,
        strategies=strategies,
    )

    sections: list[str] = []
    if report_mode in {"summary", "summary+ideas"} and "watchlist" in report_sections:
        sections.append(
            _render_structured_watchlist_message(
                build_structured_watchlist_report_from_pipeline(
                    profile_id=profile_id,
                    watchlist=watchlist,
                    strategies=strategies,
                    pipeline=watchlist_pipeline,
                ),
                language=language,
                detail_level=detail_level,
            )
        )
    if report_mode in {"summary", "summary+ideas"} and "market" in report_sections:
        market_overview = build_structured_market_overview(
            profile_id=profile_id,
            strategies=strategies,
            schedule=schedule,
            language=language,
        )
        featured_idea = build_structured_featured_idea(
            profile_id=profile_id,
            strategies=strategies,
            schedule=schedule,
            language=language,
        )
        sections.append(
            _render_structured_market_message(
                market_overview,
                language=language,
                detail_level=detail_level,
            )
        )
        sections.append(
            _render_structured_featured_idea(
                featured_idea,
                language=language,
                detail_level=detail_level,
            )
        )
    if report_mode in {"summary", "summary+ideas"} and "commodity" in report_sections:
        sections.append(
            _commodity_brief_message(
                detail_level=detail_level,
                schedule=schedule,
                language=language,
            )
        )
    if report_mode in {"ideas", "summary+ideas"}:
        sections.append(
            render_strategy_reports_markdown(
                build_strategy_reports_from_pipeline(
                    pipeline=watchlist_pipeline,
                    watchlist=watchlist,
                    strategies=strategies,
                    top_n=5,
                )
            )
        )

    return "\n\n".join(section for section in sections if section.strip())


def build_telegram_ideas_text(
    *,
    profile_id: str,
    watchlist: list[str],
    strategies: list[str],
    top_n: int = 5,
) -> str:
    """Build Telegram ideas output from canonical strategy reports."""
    watchlist_pipeline = build_watchlist_pipeline(
        profile_id=profile_id,
        watchlist=watchlist,
        strategies=strategies,
    )
    reports = build_strategy_reports_from_pipeline(
        pipeline=watchlist_pipeline,
        watchlist=watchlist,
        strategies=strategies,
        top_n=top_n,
    )
    return render_strategy_reports_markdown(reports)


def _score_to_action(score: int) -> str:
    if score >= 65:
        return "buy"
    if score >= 45:
        return "hold"
    return "reduce"


def _score_to_confidence(score: int) -> str:
    if score >= 75:
        return "high"
    if score >= 55:
        return "medium"
    return "low"


def _iso_valid_until(days_ahead: int = 3) -> str:
    return (
        (datetime.now(dt_tz.utc) + timedelta(days=days_ahead))
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _strategy_id_from_candidate(candidate) -> str:
    return str(getattr(candidate, "strategy", "") or getattr(candidate, "strategy_id", "")).strip().lower()


def _recent_price_context(symbol: str) -> dict[str, float] | None:
    try:
        import yfinance as yf

        df = yf.Ticker(symbol).history(period="9mo", interval="1d")
        if df.empty or len(df) < 30:
            return None
        close = df["Close"]
        high = df["High"]
        low = df["Low"]
        sma20 = close.rolling(20).mean()
        sma50 = close.rolling(50).mean()
        std20 = close.rolling(20).std()
        latest = float(close.iloc[-1])
        context = {
            "latest": latest,
            "sma20": float(sma20.iloc[-1]) if not math.isnan(float(sma20.iloc[-1])) else latest,
            "sma50": float(sma50.iloc[-1]) if not math.isnan(float(sma50.iloc[-1])) else latest,
            "upper20": float(high.iloc[-21:-1].max()) if len(high) >= 21 else latest,
            "lower10": float(low.iloc[-11:-1].min()) if len(low) >= 11 else latest,
            "lower_band": float((sma20 - 2 * std20).iloc[-1]) if len(std20) else latest,
            "upper_band": float((sma20 + 2 * std20).iloc[-1]) if len(std20) else latest,
        }
        return context
    except Exception:
        return None


def _generic_price_plan(candidate, last_price: float | None) -> PricePlan:
    if last_price is None or last_price <= 0:
        return PricePlan(
            entry_range="n/a",
            ideal_entry=None,
            take_profit_zone="n/a",
            stop_loss_or_invalidation=candidate.exit_logic or "n/a",
            valid_until=_iso_valid_until(),
            invalidate_if=[candidate.exit_logic] if candidate.exit_logic else [],
        )

    action = _score_to_action(candidate.score)
    if action == "buy":
        low = round(last_price * 0.99, 2)
        high = round(last_price * 1.01, 2)
        take_profit_low = round(last_price * 1.05, 2)
        take_profit_high = round(last_price * 1.08, 2)
        stop = round(last_price * 0.97, 2)
    elif action == "hold":
        low = round(last_price * 0.985, 2)
        high = round(last_price * 1.005, 2)
        take_profit_low = round(last_price * 1.03, 2)
        take_profit_high = round(last_price * 1.05, 2)
        stop = round(last_price * 0.965, 2)
    else:
        low = round(last_price * 0.995, 2)
        high = round(last_price * 1.015, 2)
        take_profit_low = round(last_price * 0.94, 2)
        take_profit_high = round(last_price * 0.97, 2)
        stop = round(last_price * 1.03, 2)

    return PricePlan(
        entry_range=f"{low}-{high}",
        ideal_entry=round((low + high) / 2, 2),
        take_profit_zone=f"{take_profit_low}-{take_profit_high}",
        stop_loss_or_invalidation=f"close beyond {stop}",
        valid_until=_iso_valid_until(),
        invalidate_if=[candidate.exit_logic] if candidate.exit_logic else [],
    )


def _price_plan_from_candidate(candidate, last_price: float | None) -> PricePlan:
    if last_price is None or last_price <= 0:
        return _generic_price_plan(candidate, last_price)

    strategy_id = _strategy_id_from_candidate(candidate)
    context = _recent_price_context(getattr(candidate, "symbol", "") or getattr(candidate, "ticker", ""))
    if not context:
        return _generic_price_plan(candidate, last_price)

    latest = context["latest"]
    sma20 = context["sma20"]
    sma50 = context["sma50"]
    upper20 = context["upper20"]
    lower10 = context["lower10"]
    lower_band = context["lower_band"]
    upper_band = context["upper_band"]
    invalidate = [candidate.exit_logic] if candidate.exit_logic else []

    if strategy_id in {"breakout", "donchian_breakout"}:
        trigger = upper20
        entry_low = round(min(trigger * 0.995, latest), 2)
        entry_high = round(max(trigger * 1.01, latest), 2)
        ideal = round((trigger + latest) / 2, 2)
        stop = round(sma20 if strategy_id == "breakout" else lower10, 2)
        tp_low = round(latest * 1.05, 2)
        tp_high = round(latest * 1.09, 2)
        return PricePlan(
            entry_range=f"{entry_low}-{entry_high}",
            ideal_entry=ideal,
            take_profit_zone=f"{tp_low}-{tp_high}",
            stop_loss_or_invalidation=f"close below {stop}",
            valid_until=_iso_valid_until(3),
            invalidate_if=invalidate,
        )

    if strategy_id in {"pullback", "trend_following"}:
        anchor = sma20 if strategy_id == "pullback" else max(sma20, sma50)
        entry_low = round(anchor * 0.99, 2)
        entry_high = round(anchor * 1.01, 2)
        stop = round(sma50 * 0.99, 2)
        tp_low = round(latest * 1.04, 2)
        tp_high = round(latest * 1.07, 2)
        return PricePlan(
            entry_range=f"{entry_low}-{entry_high}",
            ideal_entry=round(anchor, 2),
            take_profit_zone=f"{tp_low}-{tp_high}",
            stop_loss_or_invalidation=f"close below {stop}",
            valid_until=_iso_valid_until(4),
            invalidate_if=invalidate,
        )

    if strategy_id == "mean_reversion":
        entry_low = round(min(lower_band, latest) * 0.995, 2)
        entry_high = round(max(lower_band, latest) * 1.005, 2)
        stop = round(min(lower_band, latest) * 0.97, 2)
        tp_low = round(sma20 * 0.99, 2)
        tp_high = round(min(upper_band, sma20 * 1.03), 2)
        return PricePlan(
            entry_range=f"{entry_low}-{entry_high}",
            ideal_entry=round((entry_low + entry_high) / 2, 2),
            take_profit_zone=f"{tp_low}-{tp_high}",
            stop_loss_or_invalidation=f"close below {stop}",
            valid_until=_iso_valid_until(2),
            invalidate_if=invalidate,
        )

    if strategy_id == "commodity_macro":
        anchor = sma20
        entry_low = round(anchor * 0.99, 2)
        entry_high = round(max(anchor * 1.015, latest), 2)
        stop = round(sma20 * 0.97, 2)
        tp_low = round(latest * 1.05, 2)
        tp_high = round(latest * 1.1, 2)
        return PricePlan(
            entry_range=f"{entry_low}-{entry_high}",
            ideal_entry=round(anchor, 2),
            take_profit_zone=f"{tp_low}-{tp_high}",
            stop_loss_or_invalidation=f"close below {stop}",
            valid_until=_iso_valid_until(5),
            invalidate_if=invalidate,
        )

    return _generic_price_plan(candidate, last_price)


def _stringify_pipeline_entry_range(entry_range) -> str:
    if entry_range is None:
        return "n/a"
    if isinstance(entry_range, dict):
        lower_bound = entry_range.get("lower_bound")
        upper_bound = entry_range.get("upper_bound")
        if lower_bound is not None and upper_bound is not None:
            return f"{lower_bound}-{upper_bound}"
        return entry_range.get("reference") or "n/a"
    if entry_range.lower_bound is not None and entry_range.upper_bound is not None:
        return f"{entry_range.lower_bound}-{entry_range.upper_bound}"
    return entry_range.reference or "n/a"


def build_structured_watchlist_report_from_pipeline(
    profile_id: str,
    watchlist: list[str],
    strategies: list[str],
    top_n: int = 5,
    pipeline: PipelineResponse | None = None,
) -> WatchlistSummaryReport:
    """Build the watchlist section from the canonical pipeline.

    A legacy fallback is still merged in for symbols that do not yet map
    cleanly into canonical proposal output. New feature work should extend the
    canonical path rather than expanding the fallback branch.
    """
    pipeline = pipeline or build_watchlist_pipeline(
        profile_id=profile_id,
        watchlist=watchlist,
        strategies=strategies,
    )
    syntheses_by_ticker = {
        synthesis.ticker: synthesis
        for synthesis in pipeline.signal_syntheses
    }

    items_by_ticker: dict[str, WatchlistReportItem] = {}
    for action in pipeline.proposal.proposed_actions:
        execution_plan = action.execution_plan
        validity = action.proposal_validity
        synthesis = syntheses_by_ticker.get(action.ticker)
        reason_parts = [action.reason]
        if synthesis is not None and synthesis.summary:
            reason_parts.append(synthesis.summary)
        if synthesis is not None and synthesis.key_risks:
            reason_parts.append(f"risk: {synthesis.key_risks[0]}")
        reason = " | ".join(part for part in reason_parts if part)
        if validity is not None:
            reason = f"{reason} | validity: {validity.status}"

        items_by_ticker[action.ticker] = WatchlistReportItem(
            ticker=action.ticker,
            action=action.action,
            confidence=action.conviction or "",
            why_now=reason,
            price_plan=PricePlan(
                entry_range=_stringify_pipeline_entry_range(
                    execution_plan.entry_range if execution_plan else None
                ),
                ideal_entry=(
                    execution_plan.entry_range.lower_bound
                    if execution_plan and execution_plan.entry_range and execution_plan.entry_range.lower_bound is not None
                    else None
                ),
                take_profit_zone=execution_plan.take_profit_condition if execution_plan else "n/a",
                stop_loss_or_invalidation=execution_plan.stop_condition if execution_plan else "n/a",
                valid_until=execution_plan.valid_until if execution_plan else action.valid_until,
                invalidate_if=execution_plan.invalidate_if if execution_plan else [],
            ),
        )

    # Price-based fallback for tickers that produced no strategy signal
    # (e.g. indices like ^GSPC, crypto, or names not at a signal condition).
    unscreened = [s for s in watchlist if s not in items_by_ticker]
    if unscreened:
        fallback_prices = get_snapshot_for(unscreened)
        for symbol in unscreened:
            data = fallback_prices.get(symbol) or {}
            chg = data.get("change_pct")
            price = data.get("price")
            if chg is None or data.get("error"):
                score, action, confidence = 50, "hold", "low"
                why_now = "price data unavailable — monitoring only"
            elif chg >= 1.5:
                score, action, confidence = 62, "buy", "medium"
                why_now = f"up {chg:+.1f}% today — positive momentum, no specific strategy signal"
            elif chg <= -1.5:
                score, action, confidence = 38, "reduce", "medium"
                why_now = f"down {abs(chg):.1f}% today — caution warranted, no specific strategy signal"
            else:
                score, action, confidence = 50, "hold", "low"
                why_now = f"{chg:+.1f}% today — range-bound, no directional strategy signal"
            mock = SimpleNamespace(score=score, exit_logic="", evidence=[])
            items_by_ticker[symbol] = WatchlistReportItem(
                ticker=symbol,
                action=action,
                confidence=confidence,
                why_now=why_now,
                price_plan=_generic_price_plan(mock, price),
            )

    ordered_items = [items_by_ticker[ticker] for ticker in watchlist if ticker in items_by_ticker]
    if not ordered_items:
        return WatchlistSummaryReport(
            generated_at=pipeline.generated_at,
            status="no_actionable_idea",
            reason="signal quality is mixed and no setup cleared the minimum threshold",
        )

    return WatchlistSummaryReport(
        generated_at=pipeline.generated_at,
        items=ordered_items[:top_n],
    )


def _featured_stock_from_market_pipeline(
    pipeline: PipelineResponse | None,
) -> FeaturedStockIdea | None:
    if pipeline is None:
        return None

    syntheses_by_ticker = {
        synthesis.ticker: synthesis
        for synthesis in pipeline.signal_syntheses
    }
    candidates_by_ticker = {
        candidate.ticker: candidate
        for candidate in pipeline.candidates
    }

    for action in pipeline.proposal.proposed_actions:
        if action.action not in {"buy", "add"}:
            continue

        candidate = candidates_by_ticker.get(action.ticker)
        if candidate is None or candidate.aggregate_score < 0.70:
            continue

        synthesis = syntheses_by_ticker.get(action.ticker)
        execution_plan = action.execution_plan
        reason_parts = []
        if action.reason:
            reason_parts.append(action.reason)
        if synthesis is not None and synthesis.summary:
            reason_parts.append(synthesis.summary)
        reason = " | ".join(reason_parts) or "canonical proposal remains actionable"

        return FeaturedStockIdea(
            ticker=action.ticker,
            action=action.action,
            why_now=reason,
            price_plan=PricePlan(
                entry_range=_stringify_pipeline_entry_range(
                    execution_plan.entry_range if execution_plan else None
                ),
                ideal_entry=(
                    execution_plan.entry_range.lower_bound
                    if execution_plan and execution_plan.entry_range and execution_plan.entry_range.lower_bound is not None
                    else None
                ),
                take_profit_zone=execution_plan.take_profit_condition if execution_plan else "n/a",
                stop_loss_or_invalidation=execution_plan.stop_condition if execution_plan else "n/a",
                valid_until=execution_plan.valid_until if execution_plan else action.valid_until,
                invalidate_if=execution_plan.invalidate_if if execution_plan else [],
            ),
        )

    return None


def build_structured_market_overview(
    strategies: list[str],
    profile_id: str = "default",
    schedule: str = "daily",
    language: str = "en",
) -> MarketOverviewReport:
    generated_at = datetime.now(dt_tz.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    summary_response = build_global_summary_response(schedule=schedule, language=language)
    market_pipeline = build_market_pipeline(profile_id=profile_id, strategies=strategies)
    snapshot = summary_response.market_data
    lookup = {point.ticker: point for point in snapshot.values()}

    def _change_value(ticker: str) -> float | None:
        point = lookup.get(ticker)
        if not point or point.change_pct is None:
            return None
        value = float(point.change_pct)
        if math.isnan(value):
            return None
        return value

    spx_chg = _change_value("^GSPC")
    ndx_chg = _change_value("^IXIC")
    risk_tone = "mixed"
    if spx_chg is not None and ndx_chg is not None:
        if spx_chg > 0 and ndx_chg > 0:
            risk_tone = "risk-on"
        elif spx_chg < 0 and ndx_chg < 0:
            risk_tone = "risk-off"

    sector_map = {
        "Technology": "XLK",
        "Financials": "XLF",
        "Energy": "XLE",
        "Utilities": "XLU",
        "Industrials": "XLI",
        "Materials": "XLB",
    }
    sector_moves = []
    for name, ticker in sector_map.items():
        val = _change_value(ticker)
        if val is not None:
            sector_moves.append((name, ticker, val))
    featured_sector = None
    if sector_moves:
        leader_name, leader_ticker, leader_change = sorted(sector_moves, key=lambda x: x[2], reverse=True)[0]
        if leader_change >= 0.75:
            featured_sector = FeaturedSectorIdea(
                sector_name=leader_name,
                reason="sector leadership and relative strength are currently supportive",
                representative_tickers=[leader_ticker],
                entry_style="buy pullbacks above support",
                valid_until=_iso_valid_until(),
            )

    featured_stock = None
    if featured_sector is None:
        featured_stock = _featured_stock_from_market_pipeline(market_pipeline)

    if featured_sector is None and featured_stock is None:
        return MarketOverviewReport(
            generated_at=generated_at,
            risk_tone=risk_tone,
            summary=summary_response.summary,
            status="no_featured_idea_today",
            reason="signal quality is mixed and no sector or stock passed the minimum threshold",
        )

    return MarketOverviewReport(
        generated_at=generated_at,
        risk_tone=risk_tone,
        summary=summary_response.summary,
        featured_sector=featured_sector,
        featured_stock=featured_stock,
    )


def build_structured_featured_idea(
    strategies: list[str],
    profile_id: str = "default",
    schedule: str = "daily",
    language: str = "en",
) -> FeaturedIdeaReport:
    generated_at = datetime.now(dt_tz.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    overview = build_structured_market_overview(
        profile_id=profile_id,
        strategies=strategies,
        schedule=schedule,
        language=language,
    )
    if overview.featured_stock is not None:
        return FeaturedIdeaReport(
            idea_kind="stock",
            generated_at=generated_at,
            featured_stock=overview.featured_stock,
        )
    if overview.featured_sector is not None:
        return FeaturedIdeaReport(
            idea_kind="sector",
            generated_at=generated_at,
            featured_sector=overview.featured_sector,
        )
    return FeaturedIdeaReport(
        idea_kind="none",
        generated_at=generated_at,
        status="no_featured_idea_today",
        reason=overview.reason or "no setup passed the minimum threshold",
    )


def _render_price_plan_text(plan: PricePlan, language: str = "en") -> list[str]:
    if language == "zh":
        lines = [
            f"- 建议区间: {plan.entry_range or 'n/a'}",
            f"- 理想价位: {plan.ideal_entry if plan.ideal_entry is not None else 'n/a'}",
            f"- 止盈区间: {plan.take_profit_zone or 'n/a'}",
            f"- 失效条件: {plan.stop_loss_or_invalidation or 'n/a'}",
            f"- 有效期至: {plan.valid_until or 'n/a'}",
        ]
        if plan.invalidate_if:
            lines.append(f"- 关注触发: {'; '.join(plan.invalidate_if)}")
        return lines

    lines = [
        f"- Entry range: {plan.entry_range or 'n/a'}",
        f"- Ideal entry: {plan.ideal_entry if plan.ideal_entry is not None else 'n/a'}",
        f"- Take-profit zone: {plan.take_profit_zone or 'n/a'}",
        f"- Invalidation: {plan.stop_loss_or_invalidation or 'n/a'}",
        f"- Valid until: {plan.valid_until or 'n/a'}",
    ]
    if plan.invalidate_if:
        lines.append(f"- Watch triggers: {'; '.join(plan.invalidate_if)}")
    return lines


def _render_structured_watchlist_message(
    report: WatchlistSummaryReport,
    language: str = "en",
    detail_level: str = "brief",
) -> str:
    date_str = str(report.generated_at or datetime.now(dt_tz.utc).isoformat())[:10]
    if report.status == "no_actionable_idea" or not report.items:
        if language == "zh":
            return (
                f"{date_str} 决策简报\n"
                "> watchlist\n\n"
                "当前无高质量可执行机会。\n"
                f"{report.reason or '继续观察，等待更清晰确认。'}"
            )
        return (
            f"{date_str} Decision Brief\n"
            "> watchlist\n\n"
            "No actionable watchlist setup right now.\n"
            f"{report.reason or 'Stay selective and wait for cleaner confirmation.'}"
        )

    show_price_plan = detail_level == "detailed"
    lines = [
        f"{date_str} 决策简报" if language == "zh" else f"{date_str} Decision Brief",
        f"> {len(report.items)} ideas",
        "",
    ]
    for item in report.items:
        validity_hint = ""
        if "validity:" in item.why_now:
            validity_hint = item.why_now.split("validity:", 1)[-1].strip()

        if language == "zh":
            lines.append(f"{item.ticker} | {item.action.upper()} | 置信度 {item.confidence}")
            lines.append(f"- 逻辑: {item.why_now}")
            if not show_price_plan and item.price_plan.entry_range:
                lines.append(f"- 建议区间: {item.price_plan.entry_range}")
            if not show_price_plan and item.price_plan.valid_until:
                lines.append(f"- 有效期至: {item.price_plan.valid_until}")
            if validity_hint:
                lines.append(f"- 当前状态: {validity_hint}")
        else:
            lines.append(f"{item.ticker} | {item.action.upper()} | confidence {item.confidence}")
            lines.append(f"- Why now: {item.why_now}")
            if not show_price_plan and item.price_plan.entry_range:
                lines.append(f"- Entry range: {item.price_plan.entry_range}")
            if not show_price_plan and item.price_plan.valid_until:
                lines.append(f"- Valid until: {item.price_plan.valid_until}")
            if validity_hint:
                lines.append(f"- Status: {validity_hint}")
        if show_price_plan:
            lines.extend(_render_price_plan_text(item.price_plan, language=language))
        lines.append("")
    return "\n".join(lines).strip()


def _render_structured_market_message(
    report: MarketOverviewReport,
    language: str = "en",
    detail_level: str = "brief",
) -> str:
    date_str = datetime.now(dt_tz.utc).strftime("%Y-%m-%d")
    show_details = detail_level == "detailed"
    lines = [
        f"{date_str} 大盘概览" if language == "zh" else f"{date_str} Market Overview",
        f"- Risk tone: {report.risk_tone}",
        "",
        report.summary,
        "",
    ]
    if report.featured_sector is not None:
        sector = report.featured_sector
        if language == "zh":
            lines.append(f"重点板块: {sector.sector_name}")
            if show_details:
                lines.extend(
                    [
                        f"- 原因: {sector.reason}",
                        f"- 代表标的: {', '.join(sector.representative_tickers) or 'n/a'}",
                        f"- 介入方式: {sector.entry_style or 'n/a'}",
                        f"- 有效期至: {sector.valid_until or 'n/a'}",
                    ]
                )
        else:
            lines.append(f"Featured Sector: {sector.sector_name}")
            if show_details:
                lines.extend(
                    [
                        f"- Reason: {sector.reason}",
                        f"- Tickers: {', '.join(sector.representative_tickers) or 'n/a'}",
                        f"- Entry style: {sector.entry_style or 'n/a'}",
                        f"- Valid until: {sector.valid_until or 'n/a'}",
                    ]
                )
    elif report.featured_stock is not None:
        stock = report.featured_stock
        if language == "zh":
            lines.extend([f"重点个股: {stock.ticker}", f"- 原因: {stock.why_now}"])
        else:
            lines.extend([f"Featured Stock: {stock.ticker}", f"- Why now: {stock.why_now}"])
        if show_details:
            lines.extend(_render_price_plan_text(stock.price_plan, language=language))
    else:
        lines.append(
            "今日无重点机会。" if language == "zh" else "No featured sector or stock today."
        )
        if report.reason:
            lines.append(report.reason)
    return "\n".join(lines).strip()


def _render_structured_featured_idea(
    report: FeaturedIdeaReport,
    language: str = "en",
    detail_level: str = "brief",
) -> str:
    date_str = datetime.now(dt_tz.utc).strftime("%Y-%m-%d")
    show_details = detail_level == "detailed"
    lines = [
        f"{date_str} 今日重点机会" if language == "zh" else f"{date_str} Featured Idea",
        "",
    ]
    if report.featured_stock is not None:
        stock = report.featured_stock
        if language == "zh":
            lines.extend([f"{stock.ticker} | {stock.action.upper()}", f"- 原因: {stock.why_now}"])
        else:
            lines.extend([f"{stock.ticker} | {stock.action.upper()}", f"- Why now: {stock.why_now}"])
        if show_details:
            lines.extend(_render_price_plan_text(stock.price_plan, language=language))
        return "\n".join(lines).strip()
    if report.featured_sector is not None:
        sector = report.featured_sector
        if language == "zh":
            lines.append(f"板块: {sector.sector_name}")
            if show_details:
                lines.extend(
                    [
                        f"- 原因: {sector.reason}",
                        f"- 代表标的: {', '.join(sector.representative_tickers) or 'n/a'}",
                        f"- 介入方式: {sector.entry_style or 'n/a'}",
                        f"- 有效期至: {sector.valid_until or 'n/a'}",
                    ]
                )
        else:
            lines.append(f"Sector: {sector.sector_name}")
            if show_details:
                lines.extend(
                    [
                        f"- Reason: {sector.reason}",
                        f"- Tickers: {', '.join(sector.representative_tickers) or 'n/a'}",
                        f"- Entry style: {sector.entry_style or 'n/a'}",
                        f"- Valid until: {sector.valid_until or 'n/a'}",
                    ]
                )
        return "\n".join(lines).strip()
    lines.append("今日无重点机会。" if language == "zh" else "No featured idea today.")
    if report.reason:
        lines.append(report.reason)
    return "\n".join(lines).strip()


def _normalize_sections(sections: list[str] | None) -> list[str]:
    requested = [section.lower().strip() for section in (sections or []) if section.strip()]
    if "watchlist" not in requested:
        requested.insert(0, "watchlist")
    deduped = list(dict.fromkeys(requested))
    return [section for section in deduped if section in REPORT_SECTION_OPTIONS]


def _normalize_report_mode(report_mode: str | None) -> str:
    normalized = (report_mode or "").lower().strip()
    if normalized in REPORT_MODE_OPTIONS:
        return normalized
    return "summary+ideas"


def _normalize_push_detail(detail_level: str | None) -> str:
    normalized = (detail_level or "").lower().strip()
    if normalized in {"simple", "brief"}:
        return "brief"
    if normalized in {"full", "detailed"}:
        return "detailed"
    return "brief"


def _safe_profile_id(profile_id: str) -> str:
    return "".join(ch for ch in profile_id if ch.isalnum() or ch in {"-", "_", "."}) or "default"


def _bounded_section_text(
    text: str,
    *,
    language: str = "en",
    min_chars: int = 30,
    max_chars: int = 60,
    filler: str | None = None,
) -> str:
    cleaned = " ".join((text or "").split())
    fallback = filler or (
        "继续等待更清晰确认，避免在噪音阶段强行交易。"
        if language == "zh"
        else "Wait for cleaner confirmation and avoid forcing trades in noisy conditions."
    )

    if not cleaned:
        cleaned = fallback

    def _trim(raw: str) -> str:
        if len(raw) <= max_chars:
            return raw
        chunk = raw[:max_chars]
        for marker in ("。", "！", "？", "，", ".", "!", "?", ",", ";", " "):
            pos = chunk.rfind(marker)
            if pos >= max_chars - 16:
                candidate = chunk[: pos + 1].strip()
                if candidate:
                    return candidate
        return chunk.strip()

    cleaned = _trim(cleaned)
    if len(cleaned) >= min_chars:
        return cleaned

    needed = min_chars - len(cleaned)
    spacer = "" if (not cleaned or cleaned.endswith(("。", ".", "!", "！", "?", "？"))) else " "
    extra = fallback[:needed].strip()
    padded = f"{cleaned}{spacer}{extra}".strip()
    return _trim(padded)


def _report_id() -> str:
    # Include microseconds to avoid filename collisions in concurrent runs.
    return datetime.now(dt_tz.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _profile_dir(profile_id: str) -> Path:
    path = REPORTS_DIR / _safe_profile_id(profile_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _watchlist_brief_message(
    watchlist: list[str],
    strategies: list[str],
    detail_level: Literal["brief", "detailed"] = "brief",
    schedule: str = "daily",
    language: str = "en",
) -> str:
    """Legacy watchlist brief message helper.

    This helper is retained only for compatibility during the migration to the
    canonical renderer-backed watchlist/report flow and is no longer the
    preferred path for new product work.
    """
    def _signal_from_score(score: int) -> tuple[str, str]:
        if language == "zh":
            if score >= 65:
                return "🟢", "买入"
            if score >= 45:
                return "⚪", "观望"
            return "🔴", "减仓"
        if score >= 65:
            return "🟢", "Buy"
        if score >= 45:
            return "⚪", "Hold"
        return "🔴", "Reduce"

    def _one_line_watchlist_summary(
        buy_count: int,
        hold_count: int,
        reduce_count: int,
        *,
        language: str,
    ) -> str:
        total = buy_count + hold_count + reduce_count
        if total == 0:
            return (
                "一句话总结：当前高质量信号不足，先观察，避免勉强交易。"
                if language == "zh"
                else "One-line takeaway: setup quality is thin, so stay selective."
            )

        buy_ratio = buy_count / total
        reduce_ratio = reduce_count / total
        if language == "zh":
            if buy_ratio >= 0.5:
                return "一句话总结：机会端占优，可小仓位分批试错，优先高评分标的。"
            if reduce_ratio >= 0.4:
                return "一句话总结：防守优先，减少追涨，等待趋势与量能共振后再出手。"
            return "一句话总结：结构中性偏谨慎，优先等待更清晰确认信号。"

        if buy_ratio >= 0.5:
            return "One-line takeaway: setup quality is improving; scale in gradually on strength."
        if reduce_ratio >= 0.4:
            return "One-line takeaway: stay defensive and avoid momentum chasing."
        return "One-line takeaway: mixed tape; wait for cleaner confirmation."

    watchlist_pipeline = build_watchlist_pipeline(
        profile_id="watchlist-brief",
        watchlist=watchlist,
        strategies=strategies,
    )
    strategy_reports = build_strategy_reports_from_pipeline(
        pipeline=watchlist_pipeline,
        watchlist=watchlist,
        strategies=strategies,
        top_n=5 if detail_level == "detailed" else 3,
    )
    items = [item for report in strategy_reports for item in report.get("items", [])]
    items.sort(
        key=lambda item: (item.get("aggregate_score", 0.0), item.get("strategy_score", 0.0)),
        reverse=True,
    )
    top_n = 5 if detail_level == "detailed" else 3
    top = items[:top_n]
    date_str = datetime.now(dt_tz.utc).strftime("%Y-%m-%d")

    if not top:
        if language == "zh":
            lines = [
                f"{date_str} 决策简报",
                f"> {len(watchlist)}只 | 🟢0 ⚪0 🔴0",
                "",
                "当前无高质量入场信号，建议继续观察，避免勉强交易。",
            ]
            return "\n".join(lines)
        lines = [
            f"{date_str} Decision Brief",
            f"> {len(watchlist)} symbols | 🟢0 ⚪0 🔴0",
            "",
            "No high-conviction setups right now. Stay selective and avoid forced entries.",
        ]
        return "\n".join(lines)

    counts = {"buy": 0, "hold": 0, "reduce": 0}
    for item in top:
        score = round(float(item.get("aggregate_score", 0.0)) * 100)
        if score >= 65:
            counts["buy"] += 1
        elif score >= 45:
            counts["hold"] += 1
        else:
            counts["reduce"] += 1

    if language == "zh":
        lines = [
            f"{date_str} 决策简报",
            f"> {len(top)}只 | 🟢{counts['buy']} ⚪{counts['hold']} 🔴{counts['reduce']}",
            _one_line_watchlist_summary(
                counts["buy"],
                counts["hold"],
                counts["reduce"],
                language="zh",
            ),
            "",
        ]
    else:
        lines = [
            f"{date_str} Decision Brief",
            f"> {len(top)} symbols | 🟢{counts['buy']} ⚪{counts['hold']} 🔴{counts['reduce']}",
            _one_line_watchlist_summary(
                counts["buy"],
                counts["hold"],
                counts["reduce"],
                language="en",
            ),
            "",
        ]

    for item in top:
        score = round(float(item.get("aggregate_score", 0.0)) * 100)
        synthesis = item.get("synthesis") or {}
        reason = item.get("reason") or synthesis.get("summary") or "wait for cleaner confirmation"
        icon, signal = _signal_from_score(score)
        if language == "zh":
            lines.append(f"{item.get('ticker')} {icon} {signal} | 评分 {score}")
            lines.append(f"{reason}")
        else:
            lines.append(f"{item.get('ticker')} {icon} {signal} | Score {score}")
            lines.append(f"{reason}")
        lines.append("")

    if detail_level == "detailed":
        if language == "zh":
            lines.extend(["风险提示: 控制仓位，优先高评分标的。"])
        else:
            lines.extend(["Risk note: keep sizing disciplined and prioritize higher-score setups."])
    return "\n".join(lines).strip()


def _top_market_stock_ideas(profile_id: str, strategies: list[str], top_n: int = 5) -> list[dict]:
    pipeline = build_market_pipeline(profile_id=profile_id, strategies=strategies)
    if pipeline is None:
        return []

    syntheses_by_ticker = {
        synthesis.ticker: synthesis
        for synthesis in pipeline.signal_syntheses
    }
    candidates_by_ticker = {
        candidate.ticker: candidate
        for candidate in pipeline.candidates
    }
    decisions_by_ticker = {
        decision.ticker: decision
        for decision in pipeline.portfolio_decisions
    }

    ideas: list[dict] = []
    for action in pipeline.proposal.proposed_actions:
        candidate = candidates_by_ticker.get(action.ticker)
        if candidate is None:
            continue
        synthesis = syntheses_by_ticker.get(action.ticker)
        decision = decisions_by_ticker.get(action.ticker)
        execution_plan = action.execution_plan
        reason = action.reason
        if synthesis is not None and synthesis.summary:
            reason = f"{reason} | {synthesis.summary}" if reason else synthesis.summary
        ideas.append(
            {
                "ticker": action.ticker,
                "action": action.action,
                "conviction": action.conviction,
                "reason": reason,
                "signal_summary": action.signal_summary.model_dump() if action.signal_summary else None,
                "proposal_validity": (
                    action.proposal_validity.model_dump() if action.proposal_validity else None
                ),
                "execution_plan": execution_plan.model_dump() if execution_plan else None,
                "portfolio_decision": decision.model_dump() if decision else None,
                "candidate": candidate.model_dump(),
                "synthesis": synthesis.model_dump() if synthesis is not None else None,
                "strategy": str(candidate.metadata.get("primary_strategy_id", "")),
                "score": round(candidate.aggregate_score * 100),
                "confidence": candidate.aggregate_confidence,
                "symbol": action.ticker,
                "entry_logic": execution_plan.entry_condition if execution_plan else action.reason,
                "evidence": synthesis.key_supports if synthesis is not None else [],
                "valid_until": action.valid_until,
            }
        )

    ideas.sort(key=lambda item: (item.get("score", 0), item.get("confidence", 0)), reverse=True)
    return ideas[:top_n]


def _market_brief_message(
    profile_id: str = "default",
    detail_level: Literal["brief", "detailed"] = "brief",
    strategies: list[str] | None = None,
    schedule: str = "daily",
    language: str = "en",
) -> str:
    summary_response = build_global_summary_response(schedule=schedule, language=language)
    snapshot = summary_response.market_data
    lookup = {point.ticker: point for point in snapshot.values()}

    def _change_value(ticker: str) -> float | None:
        point = lookup.get(ticker)
        if not point or point.change_pct is None:
            return None
        value = float(point.change_pct)
        if math.isnan(value):
            return None
        return value

    def change_for(ticker: str) -> str:
        change = _change_value(ticker)
        if change is None:
            return "n/a"
        sign = "+" if change >= 0 else "-"
        return f"{sign}{abs(change):.1f}%"

    spx_chg = _change_value("^GSPC")
    ndx_chg = _change_value("^IXIC")
    vix_chg = _change_value("^VIX")
    risk_tone = "mixed"
    if spx_chg is not None and ndx_chg is not None:
        if spx_chg > 0 and ndx_chg > 0:
            risk_tone = "risk-on"
        elif spx_chg < 0 and ndx_chg < 0:
            risk_tone = "risk-off"

    if detail_level == "brief":
        date_str = datetime.now(dt_tz.utc).strftime("%Y-%m-%d")
        summary_text = _bounded_section_text(
            summary_response.summary,
            language=language,
            min_chars=30,
            max_chars=60,
            filler=(
                "市场情绪仍偏谨慎，等待成交量与广度同步改善。"
                if language == "zh"
                else "Sentiment is still cautious while participants wait for broader confirmation."
            ),
        )
        sector_map = {
            "Utilities": "XLU",
            "Financials": "XLF",
            "Real Estate": "XLRE",
            "Technology": "XLK",
            "Industrials": "XLI",
            "Materials": "XLB",
            "Energy": "XLE",
        }
        sector_moves = []
        for name, ticker in sector_map.items():
            val = _change_value(ticker)
            if val is None:
                continue
            sector_moves.append((name, val))
        leaders = ", ".join(name for name, _ in sorted(sector_moves, key=lambda x: x[1], reverse=True)[:3]) or "n/a"
        laggards = ", ".join(name for name, _ in sorted(sector_moves, key=lambda x: x[1])[:2]) or "n/a"

        idea = _top_market_stock_ideas(profile_id, strategies or ["breakout"], top_n=1)
        stock_idea_line = "n/a"
        if idea:
            top = idea[0]
            ev = (top.get("evidence") or [])
            reason = ev[0] if ev else top.get("entry_logic", "setup confirmation")
            stock_idea_line = f"{top.get('symbol')} | {top.get('strategy')} | Score {top.get('score')} | {reason}"

        if language == "zh":
            tone_map = {"risk-on": "偏风险偏好", "risk-off": "偏防御", "mixed": "中性偏谨慎"}
            risk_line = _bounded_section_text(
                f"情绪{tone_map.get(risk_tone, risk_tone)}，VIX {change_for('^VIX')}，关注收益率与宏观数据。",
                language="zh",
                min_chars=30,
                max_chars=60,
            )
            outlook_line = _bounded_section_text(
                "短线仍以震荡为主，若成交量与市场广度改善，再考虑逐步提高风险暴露。",
                language="zh",
                min_chars=30,
                max_chars=60,
            )
            strategy_line = _bounded_section_text(
                f"仓位建议60%-70%，当前立场{'中性偏进攻' if risk_tone != 'risk-off' else '中性偏防御'}，分批执行。",
                language="zh",
                min_chars=30,
                max_chars=60,
            )
            return (
                f"US Market Daily Review | {date_str}\n\n"
                "Market Snapshot\n"
                f"{summary_text}\n"
                f"{risk_line}\n\n"
                "Index Moves\n"
                f"- S&P 500: {change_for('^GSPC')}\n"
                f"- Nasdaq: {change_for('^IXIC')}\n"
                f"- Dow Jones: {change_for('^DJI')}\n"
                f"- Russell 2000: {change_for('^RUT')}\n"
                f"- VIX: {change_for('^VIX')}\n\n"
                "Sector Watch\n"
                f"- Leaders: {leaders}\n"
                f"- Laggards: {laggards}\n\n"
                "Risk Tone\n"
                f"- {risk_line}\n\n"
                "Near-Term Outlook (1–3 days)\n"
                f"- {outlook_line}\n\n"
                "Strategy View\n"
                f"- {strategy_line}\n\n"
                "Stock Idea\n"
                f"- {stock_idea_line}"
            )

        risk_line = _bounded_section_text(
            f"Tone is {risk_tone}; VIX is {change_for('^VIX')}. Watch rates, Fed signals, and macro data.",
            language="en",
            min_chars=30,
            max_chars=60,
        )
        outlook_line = _bounded_section_text(
            "Bias is cautiously constructive, but upside needs broader participation and stronger breadth.",
            language="en",
            min_chars=30,
            max_chars=60,
        )
        strategy_line = _bounded_section_text(
            f"Stance is {'neutral-offensive' if risk_tone != 'risk-off' else 'neutral-defensive'} with ~70% exposure and staged entries.",
            language="en",
            min_chars=30,
            max_chars=60,
        )
        return (
            f"US Market Daily Review | {date_str}\n\n"
            "Market Snapshot\n"
            f"{summary_text}\n"
            f"{risk_line}\n\n"
            "Index Moves\n"
            f"- S&P 500: {change_for('^GSPC')}\n"
            f"- Nasdaq: {change_for('^IXIC')}\n"
            f"- Dow Jones: {change_for('^DJI')}\n"
            f"- Russell 2000: {change_for('^RUT')}\n"
            f"- VIX: {change_for('^VIX')}\n\n"
            "Sector Watch\n"
            f"- Leaders: {leaders}\n"
            f"- Laggards: {laggards}\n\n"
            "Risk Tone\n"
            f"- {risk_line}\n\n"
            "Near-Term Outlook (1–3 days)\n"
            f"- {outlook_line}\n\n"
            "Strategy View\n"
            f"- {strategy_line}\n\n"
            "Stock Idea\n"
            f"- {stock_idea_line}"
        )

    if language == "zh":
        tone_map = {"risk-on": "风险偏好上行", "risk-off": "风险偏好下降", "mixed": "分化"}
        stance = "Risk-off" if risk_tone == "risk-off" else ("Risk-on" if risk_tone == "risk-on" else "中性")
        vix_signal = "波动上行" if (vix_chg is not None and vix_chg > 0) else "波动可控"
        return (
            "🎯 大盘复盘\n\n"
            f"{datetime.now(dt_tz.utc).strftime('%Y-%m-%d')} US Market Recap\n\n"
            "1. Market Summary\n"
            f"美股三大指数整体表现为 {tone_map.get(risk_tone, risk_tone)}，资金偏谨慎。\n\n"
            "2. Index Commentary\n"
            f"S&P 500 {change_for('^GSPC')} | Nasdaq {change_for('^IXIC')} | Dow {change_for('^DJI')} | VIX {change_for('^VIX')}。\n\n"
            "3. Outlook\n"
            "短线以波动驱动为主，建议等待确认信号再加仓。\n\n"
            "4. Risk Alerts\n"
            f"- 波动信号: {vix_signal}\n"
            "- 若指数同步转弱，需防止回撤扩大。\n\n"
            "5. Strategy Plan\n"
            f"- Stance: {stance}\n"
            "- Position Sizing: 控制仓位，分批执行。\n"
            "- Invalidation Trigger: 标普与纳指同步转强且VIX回落。"
        )

    stance = "Risk-off" if risk_tone == "risk-off" else ("Risk-on" if risk_tone == "risk-on" else "Neutral")
    return (
        "🎯 US Market Recap\n\n"
        f"{datetime.now(dt_tz.utc).strftime('%Y-%m-%d')} US Market Recap\n\n"
        "1. Market Summary\n"
        f"US majors are showing a {risk_tone} tape with cautious risk appetite.\n\n"
        "2. Index Commentary\n"
        f"S&P 500 {change_for('^GSPC')} | Nasdaq {change_for('^IXIC')} | Dow {change_for('^DJI')} | VIX {change_for('^VIX')}.\n\n"
        "3. Outlook\n"
        "Near-term direction remains headline and volatility driven.\n\n"
        "4. Risk Alerts\n"
        f"- VIX signal: {'elevated' if (vix_chg is not None and vix_chg > 0) else 'contained'}\n"
        "- Broad index weakness would confirm risk-off continuation.\n\n"
        "5. Strategy Plan\n"
        f"- Stance: {stance}\n"
        "- Position Sizing: keep size small and scale on confirmation.\n"
        "- Invalidation Trigger: S&P/Nasdaq regain trend with softer VIX."
    )


def _commodity_brief_message(
    detail_level: Literal["brief", "detailed"] = "brief",
    schedule: str = "daily",
    language: str = "en",
) -> str:
    summary = build_commodity_summary_response(schedule=schedule, language=language)
    commodity_pipeline = build_commodity_pipeline(
        profile_id="commodity-brief",
        strategies=["commodity_macro"],
    )
    strategy_reports = build_strategy_reports_from_pipeline(
        pipeline=commodity_pipeline,
        watchlist=DEFAULT_COMMODITY_UNIVERSE,
        strategies=["commodity_macro"],
        top_n=3 if detail_level == "brief" else 5,
    ) if commodity_pipeline is not None else []
    strategy_items = strategy_reports[0]["items"] if strategy_reports else []
    snapshot = summary.market_data
    lookup = {point.ticker: point for point in snapshot.values()}

    def change_for(ticker: str) -> str:
        point = lookup.get(ticker)
        if not point or point.change_pct is None:
            return "n/a"
        sign = "+" if point.change_pct >= 0 else "-"
        return f"{sign}{abs(point.change_pct):.1f}%"

    raw_summary = " ".join((summary.summary or "").split())

    if language == "zh":
        snapshot_line = _bounded_section_text(
            raw_summary,
            language="zh",
            min_chars=30,
            max_chars=60,
            filler="商品板块整体分化，短线以区间震荡为主，等待更明确驱动。",
        )
        risk_line = _bounded_section_text(
            "重点关注美元与实际利率变化，防止价格受宏观数据超预期冲击。",
            language="zh",
            min_chars=30,
            max_chars=60,
        )
        strategy_line = _bounded_section_text(
            "策略上优先顺势交易，控制仓位，并在关键位确认后再追单。",
            language="zh",
            min_chars=30,
            max_chars=60,
        )
        lines = [
            "🛢 商品复盘",
            f"黄金 {change_for('GC=F')} | 原油 {change_for('CL=F')} | 白银 {change_for('SI=F')} | 铜 {change_for('HG=F')}",
            "",
            "Commodity Overview",
            snapshot_line,
            "",
            "Risk & Plan",
            f"- {risk_line}",
            f"- {strategy_line}",
        ]
        if detail_level == "detailed":
            lines.extend(["", "Top Commodity Setups"])
        else:
            lines.extend(["", "重点机会"])
        if not strategy_items:
            lines.append("- 暂无高质量商品机会。")
        for idx, item in enumerate(strategy_items, 1):
            lines.append(
                f"{idx}. {item.get('ticker')} | 综合评分 {round(float(item.get('aggregate_score', 0.0)) * 100)} | "
                f"{item.get('reason') or '等待更清晰确认'}"
            )
        return "\n".join(lines)

    snapshot_line = _bounded_section_text(
        raw_summary,
        language="en",
        min_chars=30,
        max_chars=60,
        filler="Commodities are mixed and range-bound, with conviction still limited.",
    )
    risk_line = _bounded_section_text(
        "Watch dollar strength and real yields, which can quickly reshape precious metals and energy momentum.",
        language="en",
        min_chars=30,
        max_chars=60,
    )
    strategy_line = _bounded_section_text(
        "Prefer trend-following entries, keep size controlled, and add only after clean level confirmation.",
        language="en",
        min_chars=30,
        max_chars=60,
    )
    lines = [
        "🛢 Commodity Recap",
        f"Gold {change_for('GC=F')} | Oil {change_for('CL=F')} | Silver {change_for('SI=F')} | Copper {change_for('HG=F')}",
        "",
        "Commodity Overview",
        snapshot_line,
        "",
        "Risk & Plan",
        f"- {risk_line}",
        f"- {strategy_line}",
    ]
    if detail_level == "detailed":
        lines.extend(["", "Top Commodity Setups"])
    else:
        lines.extend(["", "Top ideas"])
    if not strategy_items:
        lines.append("- No strong commodity setups right now.")
    for idx, item in enumerate(strategy_items, 1):
        lines.append(
            f"{idx}. {item.get('ticker')} | aggregate score {round(float(item.get('aggregate_score', 0.0)) * 100)} | "
            f"{item.get('reason') or 'wait for cleaner confirmation'}"
        )
    return "\n".join(lines)


def build_push_messages(
    profile_id: str,
    watchlist: list[str],
    strategies: list[str],
    report_sections: list[str] | None,
    detail_level: str = "brief",
    schedule: str = "daily",
    language: str = "en",
) -> list[str]:
    sections = _normalize_sections(report_sections)
    normalized_detail = _normalize_push_detail(detail_level)
    messages = [_render_structured_watchlist_message(
        build_structured_watchlist_report_from_pipeline(
            profile_id=profile_id,
            watchlist=watchlist,
            strategies=strategies,
        ),
        language=language,
        detail_level=normalized_detail,
    )]
    if "market" in sections:
        messages.append(
            _render_structured_market_message(
                build_structured_market_overview(
                    profile_id=profile_id,
                    strategies=strategies,
                    schedule=schedule,
                    language=language,
                ),
                language=language,
                detail_level=normalized_detail,
            )
        )
        messages.append(
            _render_structured_featured_idea(
                build_structured_featured_idea(
                    profile_id=profile_id,
                    strategies=strategies,
                    schedule=schedule,
                    language=language,
                ),
                language=language,
                detail_level=normalized_detail,
            )
        )
    if "commodity" in sections:
        messages.append(
            _commodity_brief_message(
                profile_id=profile_id,
                detail_level=_normalize_push_detail(detail_level),
                schedule=schedule,
                language=language,
            )
        )
    return messages


def build_detailed_report_payload(profile_id: str, prefs: dict) -> dict:
    watchlist = prefs["watchlist"]
    strategies = prefs.get("strategies", ["breakout"])
    schedule = prefs.get("schedule", "weekly")
    language = prefs.get("language", "en")
    report_sections = _normalize_sections(prefs.get("report_sections", ["watchlist"]))
    report_mode = _normalize_report_mode(prefs.get("report_mode", "summary+ideas"))

    watchlist_summary = ""
    market_summary = ""
    market_stock_ideas: list[dict] = []
    commodity_summary = ""

    strategy_reports = []
    include_summary = report_mode in {"summary", "summary+ideas"}
    include_ideas = report_mode in {"ideas", "summary+ideas"}
    watchlist_pipeline = build_watchlist_pipeline(
        profile_id=profile_id,
        watchlist=watchlist,
        strategies=strategies,
    )
    structured_watchlist_report = build_structured_watchlist_report_from_pipeline(
        profile_id=profile_id,
        watchlist=watchlist,
        strategies=strategies,
        pipeline=watchlist_pipeline,
    )

    if include_summary and "watchlist" in report_sections:
        watchlist_summary = _render_structured_watchlist_message(
            structured_watchlist_report,
            language=language,
            detail_level="brief",
        )
    if include_summary and "market" in report_sections:
        market_summary = build_global_summary_response(schedule=schedule, language=language).summary
        market_stock_ideas = _top_market_stock_ideas(profile_id, strategies, top_n=5)
    if include_summary and "commodity" in report_sections:
        commodity_summary = build_commodity_summary_response(
            schedule=schedule,
            language=language,
        ).summary

    if include_ideas:
        strategy_reports = build_strategy_reports_from_pipeline(
            pipeline=watchlist_pipeline,
            watchlist=watchlist,
            strategies=strategies,
            top_n=5,
        )

    created_at = datetime.now(dt_tz.utc).isoformat()
    report_id = _report_id()
    structured_watchlist = structured_watchlist_report.model_dump()
    structured_market = (
        build_structured_market_overview(
            profile_id=profile_id,
            strategies=strategies,
            schedule=schedule,
            language=language,
        ).model_dump()
        if "market" in report_sections
        else None
    )
    structured_featured = (
        build_structured_featured_idea(
            profile_id=profile_id,
            strategies=strategies,
            schedule=schedule,
            language=language,
        ).model_dump()
        if "market" in report_sections
        else None
    )
    return {
        "report_id": report_id,
        "profile_id": profile_id,
        "created_at": created_at,
        "preferences": prefs,
        "report_config": {
            "report_mode": report_mode,
            "report_sections": report_sections,
        },
        "sections": {
            "watchlist_summary": watchlist_summary,
            "watchlist_structured": structured_watchlist,
            "signal_syntheses": [synthesis.model_dump() for synthesis in watchlist_pipeline.signal_syntheses],
            "portfolio_decisions": [decision.model_dump() for decision in watchlist_pipeline.portfolio_decisions],
            "proposal": watchlist_pipeline.proposal.model_dump(),
            "market_summary": market_summary,
            "market_overview_structured": structured_market,
            "featured_idea_structured": structured_featured,
            "market_stock_ideas": market_stock_ideas,
            "commodity_summary": commodity_summary,
            "strategy_reports": strategy_reports,
        },
    }


def render_detailed_report_markdown(payload: dict) -> str:
    sections = payload["sections"]
    config = payload.get("report_config", {})
    report_sections_raw = config.get("report_sections")
    if report_sections_raw is None:
        inferred_sections = []
        if sections.get("watchlist_summary"):
            inferred_sections.append("watchlist")
        if sections.get("market_summary"):
            inferred_sections.append("market")
        if sections.get("commodity_summary"):
            inferred_sections.append("commodity")
        report_sections = _normalize_sections(inferred_sections)
    else:
        report_sections = _normalize_sections(report_sections_raw)

    report_mode_raw = config.get("report_mode")
    if report_mode_raw is None:
        has_summary = bool(
            sections.get("watchlist_summary")
            or sections.get("market_summary")
            or sections.get("commodity_summary")
        )
        has_ideas = bool(sections.get("strategy_reports"))
        if has_summary and has_ideas:
            report_mode = "summary+ideas"
        elif has_ideas:
            report_mode = "ideas"
        else:
            report_mode = "summary"
    else:
        report_mode = _normalize_report_mode(report_mode_raw)
    lines = [
        f"# Stock Assistant Report",
        "",
        f"- Profile: {payload['profile_id']}",
        f"- Generated: {payload['created_at']}",
    ]

    watchlist_structured = (
        WatchlistSummaryReport(**sections["watchlist_structured"])
        if sections.get("watchlist_structured")
        else None
    )
    market_structured = (
        MarketOverviewReport(**sections["market_overview_structured"])
        if sections.get("market_overview_structured")
        else None
    )
    featured_structured = (
        FeaturedIdeaReport(**sections["featured_idea_structured"])
        if sections.get("featured_idea_structured")
        else None
    )
    signal_syntheses = sections.get("signal_syntheses") or []

    if report_mode in {"summary", "summary+ideas"}:
        if "watchlist" in report_sections:
            rendered_watchlist = (
                _render_structured_watchlist_message(watchlist_structured)
                if watchlist_structured is not None
                else sections.get("watchlist_summary", "")
            )
            if rendered_watchlist:
                lines.extend(["", "## Watchlist Summary", rendered_watchlist])
            if signal_syntheses:
                lines.extend(["", "## Signal Synthesis"])
                for synthesis in signal_syntheses:
                    summary = synthesis.get("summary", "")
                    risks = synthesis.get("key_risks") or []
                    lines.append(f"- {synthesis.get('ticker')}: {summary}")
                    if risks:
                        lines.append(f"  Risk: {risks[0]}")
        if "market" in report_sections:
            rendered_market = (
                _render_structured_market_message(market_structured)
                if market_structured is not None
                else sections.get("market_summary", "")
            )
            if rendered_market:
                lines.extend(["", "## US Market Summary", rendered_market])
            if featured_structured is not None:
                lines.extend(["", "## Featured Idea", _render_structured_featured_idea(featured_structured)])
            market_ideas = sections.get("market_stock_ideas") or []
            lines.extend(["", "## Market Stock Ideas"])
            if market_ideas:
                lines.append(render_market_stock_ideas_markdown(market_ideas))
            else:
                lines.append(render_market_stock_ideas_markdown([]))
        if "commodity" in report_sections and sections.get("commodity_summary"):
            lines.extend(["", "## Commodity Summary", sections["commodity_summary"]])

    if report_mode in {"ideas", "summary+ideas"}:
        for report in sections.get("strategy_reports", []):
            lines.extend(
                [
                    "",
                    f"## Strategy: {report['strategy']} ({report.get('asset_type', 'stock')})",
                    render_strategy_report_markdown(report),
                ]
            )
    return "\n".join(lines).strip() + "\n"


def save_detailed_report(profile_id: str, payload: dict) -> dict:
    profile_dir = _profile_dir(profile_id)
    report_id = payload["report_id"]
    json_path = profile_dir / f"{report_id}.json"
    md_path = profile_dir / f"{report_id}.md"

    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    md_path.write_text(render_detailed_report_markdown(payload), encoding="utf-8")

    return {
        "report_id": report_id,
        "created_at": payload["created_at"],
        "json_path": str(json_path),
        "markdown_path": str(md_path),
    }


def generate_and_save_report(profile_id: str, prefs: dict) -> dict:
    payload = build_detailed_report_payload(profile_id, prefs)
    saved = save_detailed_report(profile_id, payload)
    return {
        "report_id": payload["report_id"],
        "created_at": payload["created_at"],
        "report": render_detailed_report_markdown(payload),
        "payload": payload,
        "files": saved,
    }


def list_saved_reports(profile_id: str) -> list[dict]:
    profile_dir = _profile_dir(profile_id)
    results = []
    for json_file in sorted(profile_dir.glob("*.json"), reverse=True):
        try:
            payload = json.loads(json_file.read_text(encoding="utf-8"))
            results.append(
                {
                    "report_id": payload["report_id"],
                    "created_at": payload["created_at"],
                    "json_path": str(json_file),
                    "markdown_path": str(json_file.with_suffix(".md")),
                }
            )
        except Exception:
            continue
    return results


def load_saved_report(profile_id: str, report_id: str) -> dict:
    path = _profile_dir(profile_id) / f"{report_id}.json"
    if not path.exists():
        raise FileNotFoundError("Report not found.")
    return json.loads(path.read_text(encoding="utf-8"))


def report_file_path(profile_id: str, report_id: str, fmt: str) -> Path:
    if fmt not in {"json", "md"}:
        raise ValueError("format must be json or md")
    path = _profile_dir(profile_id) / f"{report_id}.{fmt}"
    if not path.exists():
        raise FileNotFoundError("Report not found.")
    return path
