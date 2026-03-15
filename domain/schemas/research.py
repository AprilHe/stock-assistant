"""Domain schemas for research-focused API and bot responses."""

from pydantic import BaseModel, Field


class MarketPoint(BaseModel):
    ticker: str
    price: float | None = None
    change_pct: float | None = None
    error: str | None = None


class MarketSnapshotResponse(BaseModel):
    market_data: dict[str, MarketPoint]


class SummaryResponse(BaseModel):
    summary: str
    market_data: dict[str, MarketPoint]
    schedule: str = Field(default="daily")
    language: str = Field(default="en")
    requested_tickers: list[str] = Field(default_factory=list)


class TickerAnalysisStructured(BaseModel):
    proposal: str
    horizon: str
    confidence: int
    summary: str
    reasoning: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    triggers: list[str] = Field(default_factory=list)


class TickerAnalysisResponse(BaseModel):
    ticker: str
    analysis: str
    analysis_structured: TickerAnalysisStructured | None = None
    strategy_id: str | None = None
    strategy_name: str | None = None


class ScreenCandidate(BaseModel):
    symbol: str
    asset_type: str
    strategy: str
    direction: str
    score: int
    confidence: float
    holding_period: str
    entry_logic: str
    exit_logic: str
    risk_flags: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)


class ScreenResponse(BaseModel):
    strategy: str
    asset_type: str
    generated_at: str
    requested_tickers: list[str] = Field(default_factory=list)
    candidates: list[ScreenCandidate] = Field(default_factory=list)


class BacktestTrade(BaseModel):
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    shares: float
    pnl: float
    return_pct: float
    exit_reason: str


class BacktestMetrics(BaseModel):
    initial_cash: float
    final_equity: float
    total_return_pct: float
    annualized_return_pct: float
    annualized_volatility_pct: float = 0.0
    max_drawdown_pct: float
    sharpe_ratio: float
    sortino_ratio: float = 0.0
    win_rate_pct: float
    trades: int
    exposure_pct: float
    turnover_pct: float = 0.0
    benchmark_return_pct: float = 0.0
    alpha_vs_benchmark_pct: float = 0.0


class EquityPoint(BaseModel):
    date: str
    equity: float


class BacktestResponse(BaseModel):
    ticker: str
    strategy: str
    start_date: str
    end_date: str
    parameters: dict[str, float | int]
    metrics: BacktestMetrics
    trades: list[BacktestTrade] = Field(default_factory=list)
    equity_curve: list[EquityPoint] = Field(default_factory=list)


class StrategyItem(BaseModel):
    id: str
    name: str
    summary: str
    tags: list[str] = Field(default_factory=list)
    asset_types: list[str] = Field(default_factory=list)
    capabilities: dict[str, bool] = Field(default_factory=dict)


class StrategyListResponse(BaseModel):
    strategies: list[StrategyItem] = Field(default_factory=list)


class StrategyDetailResponse(BaseModel):
    id: str
    name: str
    summary: str
    tags: list[str] = Field(default_factory=list)
    asset_types: list[str] = Field(default_factory=list)
    capabilities: dict[str, bool] = Field(default_factory=dict)
    python_impl: str | None = None
    config: dict = Field(default_factory=dict)
    documentation_md: str = ""
