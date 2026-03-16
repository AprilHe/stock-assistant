"""Evaluate whether proposed actions are still valid at the current time."""

from __future__ import annotations

from datetime import datetime, timezone as dt_tz

from domain.schemas.proposal import ProposalResponse, ProposalValidity, ProposedAction


def _parse_iso_datetime(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def evaluate_proposed_action_validity(
    action: ProposedAction,
    *,
    as_of: datetime | None = None,
) -> ProposalValidity:
    """Return a live validity status for one proposed action."""
    now = as_of or datetime.now(dt_tz.utc)
    checked_at = now.isoformat()

    if action.execution_plan is None:
        return ProposalValidity(
            ticker=action.ticker,
            status="not_actionable",
            is_valid_now=False,
            checked_at=checked_at,
            reason="no execution plan exists for this action",
        )

    valid_until = _parse_iso_datetime(action.execution_plan.valid_until)
    review_after = _parse_iso_datetime(action.execution_plan.review_after)
    issued_at = _parse_iso_datetime(action.execution_plan.issued_at or action.issued_at)

    if valid_until is not None and now > valid_until:
        return ProposalValidity(
            ticker=action.ticker,
            status="expired",
            is_valid_now=False,
            checked_at=checked_at,
            reason="proposal is past its valid_until timestamp",
        )

    if review_after is not None and now >= review_after:
        return ProposalValidity(
            ticker=action.ticker,
            status="review_due",
            is_valid_now=True,
            checked_at=checked_at,
            reason="proposal is still live but has reached its review_after timestamp",
        )

    try:
        from core.market_data import get_last_trading_date

        last_trading_date = get_last_trading_date()
    except Exception:
        last_trading_date = None
    if last_trading_date and issued_at is not None and issued_at.date().isoformat() < last_trading_date:
        return ProposalValidity(
            ticker=action.ticker,
            status="stale_market_context",
            is_valid_now=False,
            checked_at=checked_at,
            reason="newer market data is available than the data used to issue this proposal",
        )

    return ProposalValidity(
        ticker=action.ticker,
        status="active",
        is_valid_now=True,
        checked_at=checked_at,
        reason="proposal remains within its stated validity window",
    )


def apply_proposal_validity(
    proposal: ProposalResponse,
    *,
    as_of: datetime | None = None,
) -> ProposalResponse:
    """Attach live validity status to every proposed action."""
    for action in proposal.proposed_actions:
        action.proposal_validity = evaluate_proposed_action_validity(action, as_of=as_of)
    return proposal
