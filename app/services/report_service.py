"""Report composition, archival, and delivery formatting."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone as dt_tz
from pathlib import Path
from typing import Literal

from app.services.research_service import (
    DEFAULT_STOCK_UNIVERSE,
    _is_commodity_ticker,
    _strategy_asset_types,
    build_commodity_summary_response,
    build_global_summary_response,
    build_screen_response,
    build_watchlist_summary_response,
    format_screen_response,
)

REPORTS_DIR = Path(__file__).resolve().parents[2] / "reports"
REPORT_SECTION_OPTIONS = ("watchlist", "market", "commodity")
REPORT_MODE_OPTIONS = ("summary", "ideas", "summary+ideas")
PUSH_DETAIL_OPTIONS = ("brief", "detailed")


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
    if normalized in PUSH_DETAIL_OPTIONS:
        return normalized
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

    candidates = []
    for strategy in strategies or ["breakout"]:
        for asset_type in _strategy_asset_types(strategy):
            scoped_watchlist = [
                symbol for symbol in watchlist
                if _is_commodity_ticker(symbol) == (asset_type == "commodity")
            ]
            if not scoped_watchlist:
                continue
            response = build_screen_response(
                strategy=strategy,
                asset_type=asset_type,
                tickers=scoped_watchlist,
                top_n=3,
            )
            candidates.extend(response.candidates)

    candidates.sort(key=lambda candidate: (candidate.score, candidate.confidence), reverse=True)
    top_n = 5 if detail_level == "detailed" else 3
    top = candidates[:top_n]
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
    for candidate in top:
        if candidate.score >= 65:
            counts["buy"] += 1
        elif candidate.score >= 45:
            counts["hold"] += 1
        else:
            counts["reduce"] += 1

    if language == "zh":
        lines = [
            f"{date_str} 决策简报",
            f"> {len(top)}只 | 🟢{counts['buy']} ⚪{counts['hold']} 🔴{counts['reduce']}",
            "",
        ]
    else:
        lines = [
            f"{date_str} Decision Brief",
            f"> {len(top)} symbols | 🟢{counts['buy']} ⚪{counts['hold']} 🔴{counts['reduce']}",
            "",
        ]

    for candidate in top:
        reason = candidate.evidence[0] if candidate.evidence else candidate.entry_logic
        icon, signal = _signal_from_score(candidate.score)
        if language == "zh":
            lines.append(f"{candidate.symbol} {icon} {signal} | 评分 {candidate.score}")
            lines.append(f"{reason}")
        else:
            lines.append(f"{candidate.symbol} {icon} {signal} | Score {candidate.score}")
            lines.append(f"{reason}")
        lines.append("")

    if detail_level == "detailed":
        if language == "zh":
            lines.extend(["风险提示: 控制仓位，优先高评分标的。"])
        else:
            lines.extend(["Risk note: keep sizing disciplined and prioritize higher-score setups."])
    return "\n".join(lines).strip()


def _top_market_stock_ideas(strategies: list[str], top_n: int = 5) -> list[dict]:
    merged: dict[str, object] = {}
    for strategy in (strategies or ["breakout"]):
        try:
            if "stock" not in _strategy_asset_types(strategy):
                continue
            response = build_screen_response(
                strategy=strategy,
                asset_type="stock",
                tickers=DEFAULT_STOCK_UNIVERSE,
                top_n=top_n,
            )
        except Exception:
            continue
        for candidate in response.candidates:
            current = merged.get(candidate.symbol)
            if current is None:
                merged[candidate.symbol] = candidate
                continue
            if (candidate.score, candidate.confidence) > (current.score, current.confidence):
                merged[candidate.symbol] = candidate

    ranked = sorted(
        merged.values(),
        key=lambda candidate: (candidate.score, candidate.confidence),
        reverse=True,
    )
    return [candidate.model_dump() for candidate in ranked[:top_n]]


def _market_brief_message(
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

        idea = _top_market_stock_ideas(strategies or ["breakout"], top_n=1)
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
    candidates = build_screen_response(
        strategy="commodity_macro",
        asset_type="commodity",
        tickers=None,
        top_n=3 if detail_level == "brief" else 5,
    ).candidates
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
        if not candidates:
            lines.append("- 暂无高质量商品机会。")
        for idx, candidate in enumerate(candidates, 1):
            reason = candidate.evidence[0] if candidate.evidence else candidate.entry_logic
            lines.append(f"{idx}. {candidate.symbol} | 评分 {candidate.score} | {reason}")
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
    if not candidates:
        lines.append("- No strong commodity setups right now.")
    for idx, candidate in enumerate(candidates, 1):
        reason = candidate.evidence[0] if candidate.evidence else candidate.entry_logic
        lines.append(f"{idx}. {candidate.symbol} | score {candidate.score} | {reason}")
    return "\n".join(lines)


def build_push_messages(
    watchlist: list[str],
    strategies: list[str],
    report_sections: list[str] | None,
    detail_level: str = "brief",
    schedule: str = "daily",
    language: str = "en",
) -> list[str]:
    sections = _normalize_sections(report_sections)
    normalized_detail = _normalize_push_detail(detail_level)
    messages = [
        _watchlist_brief_message(
            watchlist,
            strategies,
            detail_level=normalized_detail,
            schedule=schedule,
            language=language,
        )
    ]
    if "market" in sections:
        messages.append(
            _market_brief_message(
                detail_level=normalized_detail,
                strategies=strategies,
                schedule=schedule,
                language=language,
            )
        )
    if "commodity" in sections:
        messages.append(
            _commodity_brief_message(
                detail_level=normalized_detail,
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

    if include_summary and "watchlist" in report_sections:
        watchlist_summary = build_watchlist_summary_response(
            watchlist=watchlist,
            schedule=schedule,
            language=language,
        ).summary
    if include_summary and "market" in report_sections:
        market_summary = build_global_summary_response(schedule=schedule, language=language).summary
        market_stock_ideas = _top_market_stock_ideas(strategies, top_n=5)
    if include_summary and "commodity" in report_sections:
        commodity_summary = build_commodity_summary_response(
            schedule=schedule,
            language=language,
        ).summary

    if include_ideas:
        for strategy in strategies:
            for asset_type in _strategy_asset_types(strategy):
                strategy_watchlist = [
                    symbol for symbol in watchlist
                    if _is_commodity_ticker(symbol) == (asset_type == "commodity")
                ]
                if not strategy_watchlist:
                    continue
                strategy_reports.append(
                    build_screen_response(
                        strategy=strategy,
                        asset_type=asset_type,
                        tickers=strategy_watchlist,
                        top_n=5,
                    ).model_dump()
                )

    created_at = datetime.now(dt_tz.utc).isoformat()
    report_id = _report_id()
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
            "market_summary": market_summary,
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

    if report_mode in {"summary", "summary+ideas"}:
        if "watchlist" in report_sections and sections.get("watchlist_summary"):
            lines.extend(["", "## Watchlist Summary", sections["watchlist_summary"]])
        if "market" in report_sections and sections.get("market_summary"):
            lines.extend(["", "## US Market Summary", sections["market_summary"]])
            market_ideas = sections.get("market_stock_ideas") or []
            lines.extend(["", "## Market Stock Ideas"])
            if market_ideas:
                for idx, candidate in enumerate(market_ideas, 1):
                    evidence = (candidate.get("evidence") or [])
                    reason = evidence[0] if evidence else candidate.get("entry_logic", "setup confirmation")
                    lines.append(
                        f"{idx}. {candidate.get('symbol')} | {candidate.get('strategy')} | "
                        f"score {candidate.get('score')} | {reason}"
                    )
            else:
                lines.append("No high-conviction market stock setups today.")
        if "commodity" in report_sections and sections.get("commodity_summary"):
            lines.extend(["", "## Commodity Summary", sections["commodity_summary"]])

    if report_mode in {"ideas", "summary+ideas"}:
        for report in sections.get("strategy_reports", []):
            lines.extend(
                [
                    "",
                    f"## Strategy: {report['strategy']}",
                    format_screen_response_obj(report),
                ]
            )
    return "\n".join(lines).strip() + "\n"


def format_screen_response_obj(payload: dict) -> str:
    class _Obj:
        def __init__(self, data: dict):
            self.strategy = data["strategy"]
            self.asset_type = data["asset_type"]
            self.candidates = []
            for item in data.get("candidates", []):
                candidate = type("Candidate", (), item)
                self.candidates.append(candidate)

    return format_screen_response(_Obj(payload))


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
