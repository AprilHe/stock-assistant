"""Schemas for user profiles, holdings, and portfolio decisions."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Holding(BaseModel):
    ticker: str
    weight: float
    sector: str = ""
    beta_bucket: str | None = None


class UserProfile(BaseModel):
    profile_id: str = Field(default="default")
    risk_profile: str = Field(default="moderate")
    target_invested_ratio: float = Field(default=0.7)
    max_single_position: float = Field(default=0.08)
    max_new_position_size: float = Field(default=0.03)
    max_sector_exposure: float = Field(default=0.25)
    max_weekly_turnover: float = Field(default=0.3)
    allow_shorting: bool = Field(default=False)
    allow_options: bool = Field(default=False)
    preferred_horizon: str = Field(default="swing")
    restricted_tickers: list[str] = Field(default_factory=list)
    preferred_sectors: list[str] = Field(default_factory=list)
    avoid_sectors: list[str] = Field(default_factory=list)


class PortfolioSnapshot(BaseModel):
    cash: float = Field(default=0.0)
    equity_value: float = Field(default=0.0)
    current_invested_ratio: float = Field(default=0.0)
    holdings: list[Holding] = Field(default_factory=list)
    sector_exposure: dict[str, float] = Field(default_factory=dict)


class PortfolioDecision(BaseModel):
    ticker: str
    eligible: bool
    action: str
    target_weight: float = Field(default=0.0)
    sizing_method: str = ""
    rank_within_candidates: int | None = None
    portfolio_rationale: list[str] = Field(default_factory=list)
    constraints_applied: list[str] = Field(default_factory=list)
    rejection_reasons: list[str] = Field(default_factory=list)
