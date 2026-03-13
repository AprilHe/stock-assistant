"""Report composition, archival, and delivery formatting."""

from __future__ import annotations

import json
from datetime import datetime, timezone as dt_tz
from pathlib import Path

from app.services.research_service import (
    DEFAULT_COMMODITY_UNIVERSE,
    _is_commodity_ticker,
    _strategy_asset_types,
    build_global_summary_response,
    build_screen_response,
    build_watchlist_summary_response,
    format_screen_response,
)

REPORTS_DIR = Path(__file__).resolve().parents[2] / "reports"
REPORT_SECTION_OPTIONS = ("watchlist", "market", "commodity")


def _normalize_sections(sections: list[str] | None) -> list[str]:
    requested = [section.lower().strip() for section in (sections or []) if section.strip()]
    if "watchlist" not in requested:
        requested.insert(0, "watchlist")
    deduped = list(dict.fromkeys(requested))
    return [section for section in deduped if section in REPORT_SECTION_OPTIONS]


def _safe_profile_id(profile_id: str) -> str:
    return "".join(ch for ch in profile_id if ch.isalnum() or ch in {"-", "_", "."}) or "default"


def _report_id() -> str:
    return datetime.now(dt_tz.utc).strftime("%Y%m%dT%H%M%SZ")


def _profile_dir(profile_id: str) -> Path:
    path = REPORTS_DIR / _safe_profile_id(profile_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _watchlist_brief_message(watchlist: list[str], strategies: list[str]) -> str:
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
    top = candidates[:3]
    if not top:
        return "Watchlist summary\nNo strong watchlist setups right now. Stay selective and manage risk."

    lines = ["Watchlist summary"]
    for idx, candidate in enumerate(top, 1):
        reason = candidate.evidence[0] if candidate.evidence else candidate.entry_logic
        risk = candidate.risk_flags[0] if candidate.risk_flags else "none"
        lines.append(
            f"{idx}. {candidate.symbol} | {candidate.strategy} | score {candidate.score} | {reason} | risk: {risk}"
        )
    return "\n".join(lines)


def _market_brief_message() -> str:
    snapshot = build_global_summary_response(schedule="daily", language="en").market_data
    lookup = {point.ticker: point for point in snapshot.values()}

    def change_for(ticker: str) -> str:
        point = lookup.get(ticker)
        if not point or point.change_pct is None:
            return "n/a"
        sign = "+" if point.change_pct >= 0 else "-"
        return f"{sign}{abs(point.change_pct):.1f}%"

    spx = lookup.get("^GSPC")
    ndx = lookup.get("^IXIC")
    risk_tone = "mixed"
    if spx and ndx and spx.change_pct is not None and ndx.change_pct is not None:
        if spx.change_pct > 0 and ndx.change_pct > 0:
            risk_tone = "risk-on"
        elif spx.change_pct < 0 and ndx.change_pct < 0:
            risk_tone = "risk-off"

    return (
        "US market summary\n"
        f"S&P 500 {change_for('^GSPC')} | Nasdaq {change_for('^IXIC')} | Dow {change_for('^DJI')}\n"
        f"Gold {change_for('GC=F')} | Oil {change_for('CL=F')} | Bitcoin {change_for('BTC-USD')}\n"
        f"Tone: {risk_tone}"
    )


def _commodity_brief_message() -> str:
    response = build_screen_response(
        strategy="commodity_macro",
        asset_type="commodity",
        tickers=DEFAULT_COMMODITY_UNIVERSE,
        top_n=3,
    )
    if not response.candidates:
        return "Commodity summary\nNo strong commodity macro setups right now."

    lines = ["Commodity summary"]
    for idx, candidate in enumerate(response.candidates, 1):
        risk = candidate.risk_flags[0] if candidate.risk_flags else "none"
        reason = candidate.evidence[0] if candidate.evidence else candidate.entry_logic
        lines.append(f"{idx}. {candidate.symbol} | score {candidate.score} | {reason} | risk: {risk}")
    return "\n".join(lines)


def build_push_messages(
    watchlist: list[str],
    strategies: list[str],
    report_sections: list[str] | None,
) -> list[str]:
    sections = _normalize_sections(report_sections)
    messages = [_watchlist_brief_message(watchlist, strategies)]
    if "market" in sections:
        messages.append(_market_brief_message())
    if "commodity" in sections:
        messages.append(_commodity_brief_message())
    return messages


def build_detailed_report_payload(profile_id: str, prefs: dict) -> dict:
    watchlist = prefs["watchlist"]
    strategies = prefs.get("strategies", ["breakout"])
    schedule = prefs.get("schedule", "weekly")
    language = prefs.get("language", "en")

    watchlist_summary = build_watchlist_summary_response(
        watchlist=watchlist,
        schedule=schedule,
        language=language,
    ).summary
    market_summary = build_global_summary_response(schedule=schedule, language=language).summary

    strategy_reports = []
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

    commodity_summary = build_screen_response(
        strategy="commodity_macro",
        asset_type="commodity",
        tickers=DEFAULT_COMMODITY_UNIVERSE,
        top_n=5,
    ).model_dump()

    created_at = datetime.now(dt_tz.utc).isoformat()
    report_id = _report_id()
    return {
        "report_id": report_id,
        "profile_id": profile_id,
        "created_at": created_at,
        "preferences": prefs,
        "sections": {
            "watchlist_summary": watchlist_summary,
            "market_summary": market_summary,
            "commodity_summary": commodity_summary,
            "strategy_reports": strategy_reports,
        },
    }


def render_detailed_report_markdown(payload: dict) -> str:
    sections = payload["sections"]
    lines = [
        f"# Stock Assistant Report",
        "",
        f"- Profile: {payload['profile_id']}",
        f"- Generated: {payload['created_at']}",
        "",
        "## Watchlist Summary",
        sections["watchlist_summary"],
        "",
        "## US Market Summary",
        sections["market_summary"],
        "",
        "## Commodity Summary",
        format_screen_response_obj(sections["commodity_summary"]),
    ]

    for report in sections["strategy_reports"]:
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
