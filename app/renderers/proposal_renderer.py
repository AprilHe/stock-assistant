"""Markdown renderers for canonical proposal-driven sections."""

from __future__ import annotations


def _stringify_entry_range(entry_range) -> str:
    if entry_range is None:
        return "n/a"
    if isinstance(entry_range, dict):
        lower_bound = entry_range.get("lower_bound")
        upper_bound = entry_range.get("upper_bound")
        if lower_bound is not None and upper_bound is not None:
            return f"{lower_bound}-{upper_bound}"
        return entry_range.get("reference") or "n/a"

    lower_bound = getattr(entry_range, "lower_bound", None)
    upper_bound = getattr(entry_range, "upper_bound", None)
    if lower_bound is not None and upper_bound is not None:
        return f"{lower_bound}-{upper_bound}"
    return getattr(entry_range, "reference", "") or "n/a"


def render_market_stock_ideas_markdown(ideas: list[dict]) -> str:
    if not ideas:
        return "No high-conviction market stock setups today."

    lines: list[str] = []
    for idx, candidate in enumerate(ideas, 1):
        signal_summary = candidate.get("signal_summary") or {}
        proposal_validity = candidate.get("proposal_validity") or {}
        execution_plan = candidate.get("execution_plan") or {}
        reason = (
            candidate.get("reason")
            or candidate.get("entry_logic")
            or "setup confirmation"
        )
        lines.append(
            f"{idx}. {candidate.get('ticker') or candidate.get('symbol')} | "
            f"{candidate.get('action', '').upper()} | "
            f"{candidate.get('strategy')} | "
            f"score {candidate.get('score')} | {reason}"
        )
        if signal_summary:
            lines.append(
                f"   agreement={signal_summary.get('agreement_level')} "
                f"aggregate_score={signal_summary.get('aggregate_score')}"
            )
        if proposal_validity:
            lines.append(f"   validity={proposal_validity.get('status')}")
        if execution_plan:
            lines.append(
                f"   entry={_stringify_entry_range(execution_plan.get('entry_range'))} "
                f"valid_until={execution_plan.get('valid_until') or candidate.get('valid_until')}"
            )
    return "\n".join(lines)


def render_strategy_report_markdown(payload: dict) -> str:
    items = payload.get("items") or []
    if not items:
        return payload.get("reason") or "No actionable idea for this strategy."

    lines: list[str] = []
    for idx, item in enumerate(items, start=1):
        validity = item.get("proposal_validity") or {}
        execution_plan = item.get("execution_plan") or {}
        lines.append(
            f"{idx}. {item.get('ticker')} | {str(item.get('action', '')).upper()} | "
            f"aggregate {round(float(item.get('aggregate_score', 0.0)) * 100)} | "
            f"strategy {round(float(item.get('strategy_score', 0.0)) * 100)}"
        )
        lines.append(
            f"   agreement={item.get('agreement_level')} conviction={item.get('conviction')} "
            f"validity={validity.get('status', 'n/a')}"
        )
        if execution_plan:
            lines.append(
                f"   entry={_stringify_entry_range(execution_plan.get('entry_range'))} "
                f"valid_until={execution_plan.get('valid_until') or 'n/a'}"
            )
        if item.get("reason"):
            lines.append(f"   {item.get('reason')}")
    return "\n".join(lines)


def render_strategy_reports_markdown(reports: list[dict]) -> str:
    if not reports:
        return "No actionable idea for the selected strategies."

    blocks: list[str] = []
    for report in reports:
        blocks.append(
            "\n".join(
                [
                    f"## Strategy: {report['strategy']} ({report.get('asset_type', 'stock')})",
                    render_strategy_report_markdown(report),
                ]
            )
        )
    return "\n\n".join(blocks)
