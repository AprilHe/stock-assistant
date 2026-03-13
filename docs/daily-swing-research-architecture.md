# Daily/Swing Research Assistant Architecture

## Goal

Turn the current "price + news + LLM summary" app into a daily/swing research assistant for stocks and commodities.

Scope:
- Research and recommendation support only
- Daily and swing horizons, not intraday execution
- Structured signals, ranking, and explanations
- Telegram and web remain the delivery channels

Out of scope:
- Autonomous order execution
- Tick-level or order-book strategies
- Unbounded LLM decision making

## Design Principles

- Keep LLMs in the explanation layer, not the scoring core.
- Prefer deterministic factors and strategy modules over prompt-only logic.
- Produce structured outputs first, then render them for humans.
- Separate data collection, feature engineering, strategy scoring, ranking, and delivery.
- Make every recommendation traceable to evidence and risk flags.

## Proposed Directory Layout

```text
stock-assistant/
├── main.py
├── requirements.txt
├── README.md
├── docs/
│   └── daily-swing-research-architecture.md
├── data/
│   ├── preferences.json
│   ├── cache/
│   └── universe/
│       ├── equities.json
│       └── commodities.json
├── app/
│   ├── api/
│   │   ├── routes_market.py
│   │   ├── routes_research.py
│   │   └── routes_screen.py
│   ├── services/
│   │   ├── research_service.py
│   │   ├── report_service.py
│   │   └── watchlist_service.py
│   └── settings.py
├── domain/
│   ├── schemas/
│   │   ├── market.py
│   │   ├── factors.py
│   │   ├── signals.py
│   │   └── research.py
│   ├── universe/
│   │   └── definitions.py
│   └── enums.py
├── infra/
│   ├── market_data/
│   │   ├── price_provider.py
│   │   ├── fundamentals_provider.py
│   │   ├── news_provider.py
│   │   └── commodity_provider.py
│   ├── cache/
│   │   └── store.py
│   └── llm/
│       └── explanation_client.py
├── research/
│   ├── features/
│   │   ├── trend.py
│   │   ├── momentum.py
│   │   ├── volatility.py
│   │   ├── volume_flow.py
│   │   ├── fundamentals.py
│   │   └── news_sentiment.py
│   ├── strategies/
│   │   ├── base.py
│   │   ├── trend_following.py
│   │   ├── pullback.py
│   │   ├── breakout.py
│   │   ├── earnings_revision.py
│   │   └── commodity_macro.py
│   ├── ranking/
│   │   └── scorer.py
│   ├── risk/
│   │   ├── guardrails.py
│   │   └── portfolio_limits.py
│   └── agents/
│       ├── planner.py
│       ├── screener_agent.py
│       ├── strategy_agent.py
│       ├── risk_agent.py
│       └── explanation_agent.py
├── core/
│   ├── preferences.py
│   └── scheduler.py
├── channels/
│   └── telegram/
│       └── bot.py
└── web/
    └── index.html
```

## Migration Map From Current Files

- `core/market_data.py` -> split into `infra/market_data/price_provider.py` and reusable feature inputs
- `core/news.py` -> `infra/market_data/news_provider.py`
- `core/ai_analysis.py` -> split into `infra/llm/explanation_client.py`, `app/services/report_service.py`, and `research/agents/explanation_agent.py`
- `main.py` -> keep as entrypoint, move business logic into `app/api` and `app/services`
- `core/preferences.py` and `core/scheduler.py` can remain for now
- `channels/telegram/bot.py` should call `app/services/research_service.py` instead of orchestrating research directly

## Agent Pipeline

```text
User Request / Scheduled Job
        |
        v
Planner Agent
        |
        +--> choose scope: market overview | watchlist report | ticker deep dive | screener
        |
        v
Screener Agent
        |
        +--> fetch universe
        +--> pull OHLCV, volume, basic fundamentals, news, commodity context
        +--> compute features
        |
        v
Strategy Agent
        |
        +--> run strategy modules
        +--> produce per-strategy scores and evidence
        |
        v
Risk Agent
        |
        +--> remove low-liquidity or high-event-risk ideas
        +--> apply exposure and volatility penalties
        |
        v
Ranking Layer
        |
        +--> combine factor and strategy scores
        +--> return top candidates with confidence and holding period
        |
        v
Explanation Agent
        |
        +--> convert structured output into Chinese/English report
        +--> must not invent facts outside structured evidence
        |
        v
Telegram / API / Web
```

## Responsibilities By Agent

### Planner Agent

Input:
- User intent
- User watchlist
- Request mode (`summary`, `report`, `analyze`, `screen`)

Output:
- Research plan with universe, horizon, strategies, and render mode

Rules:
- Default horizon is daily/swing
- Never invoke execution logic
- Prefer watchlist mode for Telegram reports

### Screener Agent

Input:
- Universe definition
- Research plan

Output:
- Normalized market dataset and feature set

Core tasks:
- Load tickers for stocks or commodities
- Fetch daily OHLCV history
- Compute trend, breakout, relative strength, ATR, rolling volume, drawdown
- Attach recent headlines and optional fundamental snapshots

### Strategy Agent

Input:
- Features per symbol

Output:
- Strategy cards per symbol

Recommended first-pass strategy set:
- `trend_following`: 20/50 day trend, relative strength, ATR-normalized momentum
- `pullback`: trend intact but price retraced to moving average with volume contraction
- `breakout`: 20 day or 55 day high breakout with volume expansion
- `earnings_revision`: positive revisions, supportive news, stable trend
- `commodity_macro`: trend + dollar/rates/inventory/news context for gold, oil, copper

Each strategy should emit:
- `direction`
- `strategy_score`
- `holding_period`
- `entry_logic`
- `exit_logic`
- `evidence`

### Risk Agent

Input:
- Strategy cards
- Volatility and liquidity metrics

Output:
- Approved or penalized research candidates

Guardrails:
- Reject symbols with missing or stale data
- Penalize extreme volatility and illiquidity
- Flag earnings, CPI, Fed, inventory, and geopolitical event risk
- Cap confidence when evidence is thin or conflicting

### Explanation Agent

Input:
- Structured ranked recommendations only

Output:
- Human-readable summary
- Per-symbol recommendation card
- Clear caveats and validity window

Rules:
- No new facts beyond provided evidence
- Mention both positive setup and primary risk
- Keep advice framed as research, not orders

## Feature Set For Daily/Swing Research

Minimum viable features:
- Daily returns over 5d, 20d, 60d
- Relative strength vs benchmark
- 20/50/200 day moving averages
- ATR and realized volatility
- 20 day breakout or breakdown distance
- Volume vs 20 day average
- Drawdown from 20 day and 52 week highs
- Headline sentiment or event tags

Second wave features:
- Earnings date proximity
- Analyst estimate revisions
- Sector and regime context
- Commodity inventory and macro tags

## Standard Output Schema

Every candidate should normalize to a single schema:

```json
{
  "symbol": "NVDA",
  "asset_type": "stock",
  "direction": "long",
  "confidence": 0.74,
  "holding_period": "days_to_weeks",
  "strategy_tags": ["breakout", "earnings_revision"],
  "factor_scores": {
    "trend": 82,
    "momentum": 78,
    "volume_flow": 76,
    "fundamental": 84,
    "news": 63,
    "risk_penalty": -18
  },
  "entry_logic": "Breakout above 20-day high with 1.8x volume",
  "exit_logic": "Exit below 10-day EMA or 2 ATR stop",
  "risk_flags": ["earnings_within_7d"],
  "evidence": [
    "Price above 20/50/200 day averages",
    "20 day breakout confirmed by volume expansion",
    "Positive estimate revision trend"
  ]
}
```

## API Evolution

Keep the current endpoints, but move them to structured services:

- `GET /api/market`
  - Raw market snapshot and regime context
- `GET /api/summary`
  - Market overview built from ranked major assets
- `GET /api/analyze/{ticker}`
  - Single-symbol research card plus explanation
- `GET /api/screen?asset_type=stock&strategy=breakout`
  - Ranked candidates for a strategy
- `POST /api/report/watchlist`
  - Structured watchlist report for Telegram or web

## Telegram Evolution

Keep current commands and extend them:

- `/report`
  - Watchlist research dashboard
- `/summary`
  - Global regime summary
- `/analyze TICKER`
  - Structured deep dive
- `/ideas`
  - Top ranked daily/swing opportunities
- `/strategy breakout`
  - Ranked opportunities for a specific strategy

## Recommended Build Order

1. Move orchestration out of `channels/telegram/bot.py` and `main.py` into service modules.
2. Introduce Pydantic schemas for research outputs.
3. Replace prompt-only analysis with feature computation plus structured ranking.
4. Add one stock strategy (`breakout`) and one commodity strategy (`commodity_macro`) first.
5. Add explanation rendering on top of structured outputs.
6. Add historical validation and backtests before expanding strategy count.

## Non-Negotiable Constraints

- No direct brokerage or execution integration in this phase.
- No recommendation without evidence and explicit risk flags.
- No LLM-only scoring.
- No intraday assumptions when using daily data.
- Every new feature module must be usable without Telegram or web.
