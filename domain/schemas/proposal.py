"""Schemas for execution plans and final proposal payloads."""

from __future__ import annotations

from pydantic import BaseModel, Field


class EntryRange(BaseModel):
    lower_bound: float | None = None
    upper_bound: float | None = None
    reference: str = ""
    notes: list[str] = Field(default_factory=list)


class ExecutionPlan(BaseModel):
    ticker: str
    entry_style: str = ""
    entry_range: EntryRange | None = None
    entry_condition: str = ""
    add_condition: str = ""
    stop_condition: str = ""
    take_profit_condition: str = ""
    execution_notes: list[str] = Field(default_factory=list)
    issued_at: str | None = None
    valid_until: str | None = None
    review_after: str | None = None
    invalidate_if: list[str] = Field(default_factory=list)


class ProposalSignalSummary(BaseModel):
    aggregate_score: float
    agreement_level: str = ""


class ProposalValidity(BaseModel):
    ticker: str
    status: str = ""
    is_valid_now: bool = False
    checked_at: str | None = None
    reason: str = ""


class ProposedAction(BaseModel):
    ticker: str
    action: str
    target_weight: float = Field(default=0.0)
    issued_at: str | None = None
    valid_until: str | None = None
    conviction: str = ""
    reason: str = ""
    signal_summary: ProposalSignalSummary | None = None
    proposal_validity: ProposalValidity | None = None
    execution_plan: ExecutionPlan | None = None


class ProposalMarketContext(BaseModel):
    regime: str = ""
    risk_tone: str = ""


class ProposalResponse(BaseModel):
    generated_at: str
    profile_id: str = Field(default="default")
    market_context: ProposalMarketContext | None = None
    proposed_actions: list[ProposedAction] = Field(default_factory=list)
    portfolio_notes: list[str] = Field(default_factory=list)
    risk_summary: list[str] = Field(default_factory=list)
