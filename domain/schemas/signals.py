"""Schemas for deterministic strategy signals and merged candidates."""

from __future__ import annotations

from pydantic import BaseModel, Field


class StrategySignal(BaseModel):
    ticker: str
    strategy_id: str
    direction: str = Field(default="long")
    score_raw: float
    score_normalized: float
    confidence: float
    horizon: str
    validity_template: str | None = None
    entry_logic: str = ""
    exit_logic: str = ""
    risk_flags: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    metadata: dict[str, float | int | str | bool] = Field(default_factory=dict)


class SignalRunRequest(BaseModel):
    tickers: list[str] = Field(default_factory=list)
    strategies: list[str] = Field(default_factory=list)
    asset_type: str = Field(default="stock")


class SignalRunResponse(BaseModel):
    generated_at: str
    signals: list[StrategySignal] = Field(default_factory=list)


class CandidateSignalView(BaseModel):
    strategy_id: str
    score_normalized: float
    direction: str


class AggregatedCandidate(BaseModel):
    ticker: str
    aggregate_direction: str
    aggregate_score: float
    aggregate_confidence: float
    strategy_signals: list[CandidateSignalView] = Field(default_factory=list)
    agreement_level: str = ""
    conflicts: list[str] = Field(default_factory=list)
    preliminary_rank: int | None = None


class SignalSynthesis(BaseModel):
    ticker: str
    overall_direction: str
    conviction: str
    signal_alignment: dict[str, float] = Field(default_factory=dict)
    summary: str
    key_supports: list[str] = Field(default_factory=list)
    key_risks: list[str] = Field(default_factory=list)
