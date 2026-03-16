import sys
from datetime import datetime, timedelta, timezone as dt_tz
from types import SimpleNamespace

from app.services.proposal_validity_service import evaluate_proposed_action_validity
from domain.schemas.proposal import ExecutionPlan, ProposedAction


def test_proposal_validity_marks_expired_actions():
    now = datetime.now(dt_tz.utc)
    action = ProposedAction(
        ticker="XOM",
        action="buy",
        execution_plan=ExecutionPlan(
            ticker="XOM",
            issued_at=(now - timedelta(days=2)).isoformat(),
            valid_until=(now - timedelta(hours=1)).isoformat(),
            review_after=(now - timedelta(hours=1)).isoformat(),
        ),
    )

    validity = evaluate_proposed_action_validity(action, as_of=now)

    assert validity.status == "expired"
    assert validity.is_valid_now is False


def test_proposal_validity_marks_stale_market_context(monkeypatch):
    now = datetime(2026, 3, 15, 12, 0, tzinfo=dt_tz.utc)
    fake_market_data = SimpleNamespace(get_last_trading_date=lambda: "2026-03-15")
    monkeypatch.setitem(sys.modules, "core.market_data", fake_market_data)

    action = ProposedAction(
        ticker="XOM",
        action="buy",
        issued_at="2026-03-14T08:00:00+00:00",
        execution_plan=ExecutionPlan(
            ticker="XOM",
            issued_at="2026-03-14T08:00:00+00:00",
            valid_until="2026-03-18T08:00:00+00:00",
            review_after="2026-03-18T08:00:00+00:00",
        ),
    )

    validity = evaluate_proposed_action_validity(action, as_of=now)

    assert validity.status == "stale_market_context"
    assert validity.is_valid_now is False

