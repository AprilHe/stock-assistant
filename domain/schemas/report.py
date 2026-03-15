"""Schemas for structured report sections and featured ideas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PricePlan(BaseModel):
    entry_range: str = ""
    ideal_entry: float | None = None
    take_profit_zone: str = ""
    stop_loss_or_invalidation: str = ""
    valid_until: str | None = None
    invalidate_if: list[str] = Field(default_factory=list)


class WatchlistReportItem(BaseModel):
    ticker: str
    action: str
    confidence: str = ""
    why_now: str = ""
    price_plan: PricePlan = Field(default_factory=PricePlan)


class WatchlistSummaryReport(BaseModel):
    type: str = Field(default="watchlist_summary")
    generated_at: str
    items: list[WatchlistReportItem] = Field(default_factory=list)
    status: str | None = None
    reason: str | None = None


class FeaturedSectorIdea(BaseModel):
    sector_name: str
    reason: str
    representative_tickers: list[str] = Field(default_factory=list)
    entry_style: str = ""
    valid_until: str | None = None


class FeaturedStockIdea(BaseModel):
    ticker: str
    action: str
    why_now: str
    price_plan: PricePlan = Field(default_factory=PricePlan)


class MarketOverviewReport(BaseModel):
    type: str = Field(default="market_overview")
    generated_at: str
    risk_tone: str
    summary: str
    featured_sector: FeaturedSectorIdea | None = None
    featured_stock: FeaturedStockIdea | None = None
    status: str | None = None
    reason: str | None = None


class FeaturedIdeaReport(BaseModel):
    type: str = Field(default="featured_idea")
    idea_kind: str
    generated_at: str
    status: str | None = None
    reason: str | None = None
    featured_sector: FeaturedSectorIdea | None = None
    featured_stock: FeaturedStockIdea | None = None
