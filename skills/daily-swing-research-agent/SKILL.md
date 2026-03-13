---
name: daily-swing-research-agent
description: Use this skill when working on the stock-assistant project as a daily or swing research assistant for stocks and commodities. Applies when designing or implementing screener logic, factor pipelines, strategy modules, ranking, risk controls, watchlist reports, research APIs, or LLM explanation layers without adding trade execution.
---

# Daily Swing Research Agent

Use this skill for changes in this repository that should preserve the product as a daily/swing research assistant rather than a generic chat bot or an auto-trading system.

Read [docs/daily-swing-research-architecture.md](../../docs/daily-swing-research-architecture.md) before making substantial design changes. Read only the sections relevant to the request.

## What This Project Is

- A research assistant delivered through FastAPI and Telegram
- Focused on stocks and commodities
- Intended for daily and swing horizons
- Built around structured signals, ranking, and human-readable explanations

## What This Project Is Not

- Not an execution bot
- Not an intraday or order-book system
- Not a prompt-only recommendation engine
- Not a place to let the LLM invent data or scores

## Workflow

1. Inspect the current request path first.
   - API requests usually start in `main.py`.
   - Telegram flows start in `channels/telegram/bot.py`.
   - User preferences and schedules live in `core/preferences.py` and `core/scheduler.py`.
2. Decide whether the change belongs to `app`, `infra`, `research`, `domain`, or existing `core` compatibility code.
3. Keep collection, scoring, risk, and explanation separated.
4. Produce or preserve structured research outputs before rendering text.
5. Verify that the LLM layer only explains existing evidence.

## Target Module Boundaries

- `infra/market_data`
  - External providers, caching, normalization
- `research/features`
  - Deterministic factor computation
- `research/strategies`
  - Reusable strategy scoring modules
- `research/risk`
  - Guardrails and penalties
- `research/ranking`
  - Cross-strategy ranking and confidence
- `research/agents`
  - Thin orchestration across the pipeline
- `app/services`
  - Request-facing orchestration for API and Telegram
- `infra/llm`
  - Explanation-only LLM client

If the repository has not yet been refactored into these modules, prefer incremental extraction instead of a large rewrite.

## Required Output Shape

Whenever a feature returns a recommendation, preserve these fields if possible:

- `symbol`
- `asset_type`
- `direction`
- `confidence`
- `holding_period`
- `strategy_tags`
- `factor_scores`
- `entry_logic`
- `exit_logic`
- `risk_flags`
- `evidence`

Render text after these fields exist, not before.

## Strategy Guidance

Default strategies for this project:
- Stock trend following
- Stock breakout
- Pullback in trend
- Earnings revision or event support
- Commodity macro trend

For early implementations, prioritize:
- One stock strategy
- One commodity strategy
- One shared ranking model

Do not add many strategies before there is a stable schema and testable scoring path.

## Data Guidance

Minimum viable daily/swing inputs:
- Daily OHLCV history
- Rolling volume context
- Moving averages
- ATR or realized volatility
- Relative strength
- Recent news and event tags

Preferred interpretation:
- Numerical features drive scores
- News and LLMs provide context and explanation
- Missing data lowers confidence or blocks recommendation

## LLM Rules

- LLMs may summarize, compare evidence, and explain risks.
- LLMs may not fabricate market data, indicator values, or strategy scores.
- LLM prompts should consume structured evidence, not raw unbounded context where avoidable.
- If a recommendation is weak or conflicting, the output should say so explicitly.

## Delivery Rules

- Telegram responses should remain concise and readable.
- API responses should keep structured fields available for future UI work.
- Web and Telegram should call shared services instead of duplicating research logic.

## Implementation Bias

Prefer these types of changes:
- Extract orchestration from handlers into service modules
- Introduce Pydantic schemas before expanding prompt complexity
- Add pure functions for indicators and strategy scoring
- Add tests for ranking, confidence, and risk gating

Avoid these types of changes:
- Embedding all business logic in route handlers
- Mixing data fetch and LLM rendering in one function
- Returning plain prose without machine-readable fields
- Treating free-form LLM output as truth

## When To Read More

- For architecture and migration guidance, read [docs/daily-swing-research-architecture.md](../../docs/daily-swing-research-architecture.md).
- For current app behavior, inspect `main.py`, `channels/telegram/bot.py`, `core/preferences.py`, and `core/scheduler.py`.

## Done Criteria

A change is aligned with this skill when:
- The system remains a daily/swing research assistant
- Structured scoring and risk are clearer than before
- Delivery layers call shared services
- The LLM role is narrower and safer than before
