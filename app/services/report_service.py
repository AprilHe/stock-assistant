"""Report composition, archival, and delivery formatting."""

from __future__ import annotations

import json
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
    if not top:
        compact = ""
        try:
            summary = build_watchlist_summary_response(
                watchlist=watchlist,
                schedule=schedule,
                language=language,
            ).summary
            compact = " ".join(summary.strip().split())[:220]
        except Exception:
            compact = ""
        if language == "zh":
            lines = ["📋 自选股复盘", "当前无明显高质量机会，建议耐心等待并控制风险。"]
            if compact:
                lines.append(f"简要背景: {compact}")
            return "\n".join(lines)
        lines = ["📋 Watchlist Recap", "No strong watchlist setups right now. Stay selective and manage risk."]
        if compact:
            lines.append(f"Context: {compact}")
        return "\n".join(lines)

    if language == "zh":
        lines = ["📋 自选股复盘"]
        if detail_level == "detailed":
            lines.extend(["1. Setup Summary", f"共扫描 {len(watchlist)} 个标的，筛出 {len(top)} 个高分机会。", "", "2. Top Setups"])
    else:
        lines = ["📋 Watchlist Recap"]
        if detail_level == "detailed":
            lines.extend(["1. Setup Summary", f"Scanned {len(watchlist)} symbols; selected {len(top)} high-score setups.", "", "2. Top Setups"])

    for idx, candidate in enumerate(top, 1):
        reason = candidate.evidence[0] if candidate.evidence else candidate.entry_logic
        risk = candidate.risk_flags[0] if candidate.risk_flags else ("无" if language == "zh" else "none")
        if language == "zh":
            lines.append(
                f"{idx}. {candidate.symbol} | {candidate.strategy} | 评分 {candidate.score} | {reason} | 风险提示: {risk}"
            )
        else:
            lines.append(
                f"{idx}. {candidate.symbol} | {candidate.strategy} | score {candidate.score} | {reason} | risk: {risk}"
            )

    if detail_level == "detailed":
        if language == "zh":
            lines.extend(["", "3. Strategy Plan", "仓位建议: 分批小仓位试错，优先高评分标的。", "失效条件: 核心入场逻辑被破坏或波动急剧放大。"])
        else:
            lines.extend(["", "3. Strategy Plan", "Positioning: Start small and scale only on confirmation.", "Invalidation: Exit if core setup logic breaks."])
    return "\n".join(lines)


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
    schedule: str = "daily",
    language: str = "en",
) -> str:
    snapshot = build_global_summary_response(schedule=schedule, language=language).market_data
    lookup = {point.ticker: point for point in snapshot.values()}

    def _change_value(ticker: str) -> float | None:
        point = lookup.get(ticker)
        if not point or point.change_pct is None:
            return None
        return float(point.change_pct)

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
        if language == "zh":
            tone_map = {"risk-on": "风险偏好上行", "risk-off": "风险偏好下降", "mixed": "分化"}
            return (
                "🎯 大盘复盘\n"
                f"标普500 {change_for('^GSPC')} | 纳指 {change_for('^IXIC')} | 道指 {change_for('^DJI')}\n"
                f"黄金 {change_for('GC=F')} | 原油 {change_for('CL=F')} | 比特币 {change_for('BTC-USD')}\n"
                f"市场情绪: {tone_map.get(risk_tone, risk_tone)}"
            )
        return (
            "🎯 US Market Recap\n"
            f"S&P 500 {change_for('^GSPC')} | Nasdaq {change_for('^IXIC')} | Dow {change_for('^DJI')}\n"
            f"Gold {change_for('GC=F')} | Oil {change_for('CL=F')} | Bitcoin {change_for('BTC-USD')}\n"
            f"Tone: {risk_tone}"
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

    if language == "zh":
        lines = [
            "🛢 商品复盘",
            f"黄金 {change_for('GC=F')} | 原油 {change_for('CL=F')} | 白银 {change_for('SI=F')} | 铜 {change_for('HG=F')}",
        ]
        if detail_level == "detailed":
            lines.extend(["", "1. Market Summary", summary.summary[:220], "", "2. Top Commodity Setups"])
        else:
            lines.extend(["", "重点机会:"])
        if not candidates:
            lines.append("- 暂无高质量商品机会。")
        for idx, candidate in enumerate(candidates, 1):
            reason = candidate.evidence[0] if candidate.evidence else candidate.entry_logic
            lines.append(f"{idx}. {candidate.symbol} | 评分 {candidate.score} | {reason}")
        return "\n".join(lines)

    lines = [
        "🛢 Commodity Recap",
        f"Gold {change_for('GC=F')} | Oil {change_for('CL=F')} | Silver {change_for('SI=F')} | Copper {change_for('HG=F')}",
    ]
    if detail_level == "detailed":
        lines.extend(["", "1. Market Summary", summary.summary[:220], "", "2. Top Commodity Setups"])
    else:
        lines.extend(["", "Top ideas:"])
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
