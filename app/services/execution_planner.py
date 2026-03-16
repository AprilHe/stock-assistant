"""Execution planning and proposal assembly for portfolio decisions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_tz

from app.services.proposal_validity_service import apply_proposal_validity
from domain.schemas.portfolio import PortfolioDecision, UserProfile
from domain.schemas.proposal import (
    EntryRange,
    ExecutionPlan,
    ProposalResponse,
    ProposalSignalSummary,
    ProposedAction,
)
from domain.schemas.signals import AggregatedCandidate, StrategySignal


def _signals_by_ticker(signals: list[StrategySignal]) -> dict[str, list[StrategySignal]]:
    grouped: dict[str, list[StrategySignal]] = {}
    for signal in signals:
        grouped.setdefault(signal.ticker, []).append(signal)
    return grouped


def _candidate_map(candidates: list[AggregatedCandidate]) -> dict[str, AggregatedCandidate]:
    return {candidate.ticker: candidate for candidate in candidates}


def _primary_signal(signals: list[StrategySignal]) -> StrategySignal | None:
    if not signals:
        return None
    return max(signals, key=lambda item: (item.score_normalized, item.confidence))


def _entry_style(candidate: AggregatedCandidate, primary_signal: StrategySignal | None) -> str:
    strategy_id = primary_signal.strategy_id if primary_signal else str(candidate.metadata.get("primary_strategy_id", ""))
    if strategy_id in {"breakout", "donchian_breakout"}:
        return "breakout_confirmation"
    if strategy_id in {"pullback", "mean_reversion"}:
        return "buy_on_pullback"
    if candidate.agreement_level == "high":
        return "starter_size_with_add_on_confirmation"
    return "measured_entry"


def _entry_range(candidate: AggregatedCandidate, primary_signal: StrategySignal | None) -> EntryRange:
    strategy_id = primary_signal.strategy_id if primary_signal else str(candidate.metadata.get("primary_strategy_id", ""))
    last_price = candidate.metadata.get("last_price")
    notes: list[str] = []

    if primary_signal and primary_signal.entry_logic:
        notes.append(primary_signal.entry_logic)

    if isinstance(last_price, (int, float)):
        price = float(last_price)
        if strategy_id in {"breakout", "donchian_breakout"}:
            return EntryRange(
                lower_bound=round(price * 0.995, 2),
                upper_bound=round(price * 1.01, 2),
                reference="tight range around live breakout confirmation",
                notes=notes,
            )
        if strategy_id in {"pullback", "mean_reversion"}:
            return EntryRange(
                lower_bound=round(price * 0.985, 2),
                upper_bound=round(price * 1.0, 2),
                reference="buy only near support / pullback zone",
                notes=notes,
            )
        return EntryRange(
            lower_bound=round(price * 0.99, 2),
            upper_bound=round(price * 1.01, 2),
            reference="measured range around current market price",
            notes=notes,
        )

    if strategy_id in {"breakout", "donchian_breakout"}:
        return EntryRange(
            reference="enter only near breakout confirmation, not on extended price action",
            notes=notes,
        )
    if strategy_id in {"pullback", "mean_reversion"}:
        return EntryRange(
            reference="enter only near pullback / reversion support, avoid chasing strength",
            notes=notes,
        )
    return EntryRange(
        reference="use a measured starter entry while the signal remains valid",
        notes=notes,
    )


def _valid_until(now: datetime, candidate: AggregatedCandidate, primary_signal: StrategySignal | None) -> str:
    template = ""
    if primary_signal and primary_signal.validity_template:
        template = primary_signal.validity_template
    elif "primary_validity_template" in candidate.metadata:
        template = str(candidate.metadata["primary_validity_template"])

    trading_days = 3
    if "2_trading_days" in template:
        trading_days = 2
    elif "5_trading_days" in template:
        trading_days = 5

    return (now + timedelta(days=trading_days)).isoformat()


def build_execution_plan(
    decision: PortfolioDecision,
    candidate: AggregatedCandidate,
    signals: list[StrategySignal],
) -> ExecutionPlan | None:
    """Create an execution plan for actionable portfolio decisions."""
    if decision.action not in {"buy", "add"}:
        return None

    now = datetime.now(dt_tz.utc)
    primary_signal = _primary_signal(signals)

    entry_condition = (
        primary_signal.entry_logic
        if primary_signal and primary_signal.entry_logic
        else "Enter only while the merged signal remains valid and market conditions are stable"
    )
    stop_condition = (
        primary_signal.exit_logic
        if primary_signal and primary_signal.exit_logic
        else "Exit if the setup invalidates or portfolio risk limits are breached"
    )
    take_profit_condition = (
        "Scale out into strength if the move becomes extended versus the setup horizon, "
        "or take partial profits near 1.5-2.0R."
    )
    add_condition = (
        "Add only after follow-through confirms the thesis and no new conflicts appear."
        if decision.action == "buy"
        else "Add incrementally only if the existing position remains in trend and risk budget allows."
    )

    notes: list[str] = [
        f"Use {decision.target_weight:.2%} as the total target weight ceiling for this idea.",
        f"Agreement level is {candidate.agreement_level}; size already reflects profile constraints.",
    ]
    if candidate.conflicts:
        notes.append("Conflicts are present, so prefer a measured entry rather than chasing price.")
    asset_type = str(candidate.metadata.get("asset_type", "stock"))
    if asset_type == "commodity":
        notes.append("Monitor macro drivers closely because commodities can reprice quickly on USD/rates moves.")

    invalidate_if = list(candidate.conflicts)
    if primary_signal and primary_signal.validity_template:
        invalidate_if.append(primary_signal.validity_template)
    elif "primary_validity_template" in candidate.metadata:
        invalidate_if.append(str(candidate.metadata["primary_validity_template"]))

    valid_until = _valid_until(now, candidate, primary_signal)

    return ExecutionPlan(
        ticker=decision.ticker,
        entry_style=_entry_style(candidate, primary_signal),
        entry_range=_entry_range(candidate, primary_signal),
        entry_condition=entry_condition,
        add_condition=add_condition,
        stop_condition=stop_condition,
        take_profit_condition=take_profit_condition,
        execution_notes=notes,
        issued_at=now.isoformat(),
        valid_until=valid_until,
        review_after=valid_until,
        invalidate_if=invalidate_if,
    )


def build_proposal_response(
    *,
    profile: UserProfile,
    decisions: list[PortfolioDecision],
    candidates: list[AggregatedCandidate],
    signals: list[StrategySignal],
) -> ProposalResponse:
    """Assemble actionable portfolio decisions into a proposal payload."""
    by_ticker_candidate = _candidate_map(candidates)
    by_ticker_signals = _signals_by_ticker(signals)
    generated_at = datetime.now(dt_tz.utc).isoformat()

    proposed_actions: list[ProposedAction] = []
    portfolio_notes: list[str] = []
    risk_summary: list[str] = []

    for decision in decisions:
        candidate = by_ticker_candidate.get(decision.ticker)
        if candidate is None:
            continue
        ticker_signals = by_ticker_signals.get(decision.ticker, [])
        execution_plan = build_execution_plan(decision, candidate, ticker_signals)

        if decision.eligible:
            portfolio_notes.append(
                f"{decision.ticker} ranked for action with target weight {decision.target_weight:.2%}."
            )
        elif decision.rejection_reasons:
            risk_summary.append(
                f"{decision.ticker} was not actionable: {', '.join(decision.rejection_reasons)}."
            )

        proposed_actions.append(
            ProposedAction(
                ticker=decision.ticker,
                action=decision.action,
                target_weight=decision.target_weight,
                issued_at=generated_at,
                valid_until=execution_plan.valid_until if execution_plan else None,
                conviction=candidate.agreement_level,
                reason="; ".join(decision.portfolio_rationale or decision.rejection_reasons),
                signal_summary=ProposalSignalSummary(
                    aggregate_score=candidate.aggregate_score,
                    agreement_level=candidate.agreement_level,
                ),
                execution_plan=execution_plan,
            )
        )

    response = ProposalResponse(
        generated_at=generated_at,
        profile_id=profile.profile_id,
        proposed_actions=proposed_actions,
        portfolio_notes=portfolio_notes,
        risk_summary=risk_summary,
    )
    return apply_proposal_validity(response)
