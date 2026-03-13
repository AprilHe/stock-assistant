# Stock Assistant

AI-powered market analysis that delivers pre-market reports and trade ideas every trading day — via **Telegram**, **web dashboard**, **CLI**, or **GitHub Actions**.

---

## Table of Contents

1. [What It Does](#what-it-does)
2. [Start Here](#start-here)
3. [Option A — GitHub Actions (default, no local setup)](#option-a--github-actions-default-no-local-setup)
4. [Option B — Web Dashboard & API Server](#option-b--web-dashboard--api-server)
5. [Option C — Telegram Bot (interactive)](#option-c--telegram-bot-interactive)
6. [Option D — CLI / Cron](#option-d--cli--cron)
7. [Environment Setup (local only)](#environment-setup-local-only)
8. [API Reference](#api-reference)
9. [Telegram Bot Commands](#telegram-bot-commands)
10. [Strategies](#strategies)
11. [Switching LLM Providers](#switching-llm-providers)
12. [Project Structure](#project-structure)
13. [API Keys](#api-keys)
14. [Disclaimer](#disclaimer)

---

## What It Does

- Fetches live prices (indices, commodities, crypto) via **yfinance**
- Pulls recent financial headlines from **NewsAPI**
- Feeds both into an **LLM** (Gemini, Claude, GPT-4o, Llama) to generate analysis and trade ideas
- Screens your watchlist for setups using configurable strategies
- Delivers to your **Telegram**, a **web dashboard**, a **CLI**, or **GitHub Actions artifacts**

---

## Start Here

Choose a run option first.

- If you want the easiest setup, use **Option A: GitHub Actions**. You can configure notifications and report settings entirely in the GitHub web UI.
- If you want a browser dashboard or interactive bot, use **Option B/C** and then do **Environment Setup**.
- If you want terminal or cron usage, use **Option D** and then do **Environment Setup**.

## Option A — GitHub Actions (default, no local setup)

> **Recommended for most users.** Fork the repo, add your API keys in the GitHub UI, and get a daily Telegram report every trading day at 8:30 AM New York time — no terminal, no server, no code changes needed.

### Step 1 — Fork the repository

Click **Fork** at the top of this page to create your own copy.

### Step 2 — Add API keys as Secrets

In your forked repo: **Settings → Secrets and variables → Actions → Secrets → New repository secret**

Add these secrets:

| Secret name | Where to get it | Required? |
|-------------|-----------------|-----------|
| `GEMINI_API_KEY` | [aistudio.google.com](https://aistudio.google.com) — free | One LLM key required |
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) | _(or)_ |
| `OPENAI_API_KEY` | [platform.openai.com](https://platform.openai.com) | _(or)_ |
| `GROQ_API_KEY` | [console.groq.com](https://console.groq.com) — free | _(or)_ |
| `NEWS_API_KEY` | [newsapi.org/register](https://newsapi.org/register) — free | Yes |
| `TELEGRAM_BOT_TOKEN` | Message `@BotFather` on Telegram → `/newbot` | For Telegram delivery |
| `TELEGRAM_CHAT_ID` | Message `@userinfobot` on Telegram to find yours | For Telegram delivery |

### Step 3 — Set your watchlist and preferences (optional)

In your forked repo: **Settings → Secrets and variables → Actions → Variables → New repository variable**

| Variable name | Example value | Description |
|---------------|---------------|-------------|
| `WATCHLIST` | `AAPL,NVDA,^GSPC,GC=F` | Tickers to track (default: `^GSPC,^IXIC,BTC-USD,GC=F,CL=F`) |
| `STRATEGIES` | `breakout,pullback` | Screening strategies (default: `breakout`) |
| `REPORT_LANGUAGE` | `zh` | `en` or `zh` (default: `en`) |
| `LLM_MODEL` | `gemini/gemini-1.5-flash` | Which LLM to use (default: `gemini/gemini-1.5-flash`) |

### Step 4 — Enable the workflow

Go to the **Actions** tab of your fork. If prompted, click **"I understand my workflows, enable them"**.

### Step 5 — Run it once manually

Run the workflow once from GitHub to confirm your secrets and settings are correct.

Go to **Actions → Stock Report → Run workflow**. You can override any settings for that one run:

| Input | Description |
|-------|-------------|
| `watchlist` | Comma-separated tickers, e.g. `AAPL,NVDA,^GSPC` |
| `strategies` | e.g. `breakout,pullback,commodity_macro` |
| `language` | `en` or `zh` |
| `sections` | `watchlist` / `watchlist,market` / `watchlist,market,commodity` |
| `send_telegram` | `true` to send to Telegram, `false` to skip |

### Step 6 — Automatic runs continue from your saved settings

After that first manual run, the workflow ([`.github/workflows/stock-report.yml`](/Users/april/Desktop/ai-tools/stock-assisstant/.github/workflows/stock-report.yml)) will keep running automatically based on the repo settings:
- **Every trading day (Mon–Fri) at 8:30 AM New York time**
- Uses your repository secrets and variables by default
- Sends the report to your Telegram chat
- Saves the report as a downloadable artifact in the Actions run

### What the workflow does

1. Checks out your repo
2. Installs Python 3.11 + dependencies
3. Runs the report script with all env vars injected
4. **Writes the report to the GitHub Actions Job Summary** (visible on the run page)
5. **Uploads `.md` + `.json` report files as a downloadable artifact** (kept 30 days)
6. **Sends the report to your Telegram chat**

### Change the schedule

Edit [`.github/workflows/stock-report.yml`](/Users/april/Desktop/ai-tools/stock-assisstant/.github/workflows/stock-report.yml) in the GitHub web editor (click the pencil icon). Change the cron line:

```yaml
schedule:
  - cron: "30 13 * * 1-5"   # Mon–Fri 8:30 AM ET (13:30 UTC)
  # - cron: "0 14 * * 1"    # Weekly — every Monday 9:00 AM ET
  # - cron: "0 13 * * 1-5"  # Mon–Fri 8:00 AM ET
```

> **Note on daylight saving time:** GitHub Actions cron runs in UTC. `13:30 UTC` = 8:30 AM EST (Nov–Mar) and 9:30 AM EDT (Mar–Nov). The report always arrives before or at the opening bell either way.

---

## Option B — Web Dashboard & API Server

A local server with a browser UI and full REST API. Also activates scheduled Telegram pushes and the interactive Telegram bot.

**Requires:** [Local setup](#local-setup) first.

```bash
cd stock-assistant
python main.py
```

| URL | Description |
|-----|-------------|
| `http://localhost:8000` | Web dashboard |
| `http://localhost:8000/docs` | Interactive API explorer (Swagger UI) |

The server also starts:
- **APScheduler** — runs per-user scheduled Telegram pushes
- **Telegram bot** — starts polling if `TELEGRAM_BOT_TOKEN` is set

---

## Option C — Telegram Bot (interactive)

A conversational bot you can message any time to get on-demand reports and manage your watchlist.

**Requires:** The web server running (Option B). The bot starts automatically.

**Setup:**
1. Message `@BotFather` → `/newbot` → copy the token into `TELEGRAM_BOT_TOKEN` in `.env`
2. Message `@userinfobot` on Telegram to get your chat ID → set `TELEGRAM_CHAT_ID`
3. Start the server: `python main.py`
4. Find your bot on Telegram and send `/start`

**How scheduled pushes work:**

Set up your schedule with a few commands:

```
/schedule daily          → every day at your push time
/schedule twice          → twice a day (push time + 8 h)
/schedule weekly         → every Monday at your push time
/pushtime 08:30          → set push time (24h)
/timezone America/New_York
```

Each scheduled push sends messages in order:
1. **Watchlist summary** — trade ideas from your tickers (always included)
2. **US market overview** — indices, gold, oil, Bitcoin (add with `/sections watchlist,market`)
3. **Commodity screen** — top commodity setups (add with `/sections watchlist,market,commodity`)

See all bot commands in the [Telegram Bot Commands](#telegram-bot-commands) section.

---

## Option D — CLI / Cron

Generate a report from the terminal — no server required. Useful for scheduled tasks or quick spot-checks.

**Requires:** [Local setup](#local-setup) first.

```bash
cd stock-assistant
```

**Minimal — print report to stdout:**
```bash
python scripts/run_report.py
```

**Custom watchlist and Telegram notification:**
```bash
python scripts/run_report.py \
  --watchlist "AAPL,NVDA,^GSPC,GC=F" \
  --strategies "breakout,pullback" \
  --language en \
  --sections "watchlist,market" \
  --send-telegram
```

**All flags (each has a matching env var as fallback):**

| Flag | Env var | Default | Description |
|------|---------|---------|-------------|
| `--watchlist` | `WATCHLIST` | `^GSPC,^IXIC,BTC-USD` | Comma-separated tickers |
| `--strategies` | `STRATEGIES` | `breakout` | Comma-separated strategy IDs |
| `--language` | `REPORT_LANGUAGE` | `en` | `en` or `zh` |
| `--sections` | `REPORT_SECTIONS` | `watchlist,market` | `watchlist`, `market`, `commodity` |
| `--schedule` | — | `weekly` | LLM prompt context label |
| `--send-telegram` | `SEND_TELEGRAM=true` | off | Send to Telegram |
| `--chat-id` | `TELEGRAM_CHAT_ID` | — | Override Telegram chat ID |

Reports are saved to `reports/github-actions/<report_id>.md` and `.json`.

**macOS / Linux cron example (every weekday at 8:30 AM local time):**
```bash
30 8 * * 1-5 cd /path/to/stock-assistant && venv/bin/python scripts/run_report.py --send-telegram
```

---

## Environment Setup (local only)

Required for Options B, C, and D.

### 1. Create the virtual environment

```bash
cd stock-assistant

python3 -m venv venv
source venv/bin/activate        # macOS / Linux
# venv\Scripts\activate         # Windows

pip install -r requirements.txt
```

### 2. Configure API keys

```bash
cp .env.example .env
```

Edit `.env`:

```bash
# Pick one LLM and set its key
LLM_MODEL=gemini/gemini-1.5-flash
GEMINI_API_KEY=your_key_here

# News headlines
NEWS_API_KEY=your_key_here

# Telegram (optional)
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

### 3. Smoke-test the core modules

```bash
python -m core.market_data    # prints a live market price snapshot
python -m core.news           # prints recent headlines
python -m core.ai_analysis    # prints an LLM-generated summary
```

---

## API Reference

All endpoints available on the running local server.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Web dashboard |
| `GET` | `/api/market` | Raw market snapshot (no LLM) |
| `GET` | `/api/summary` | AI-generated global market summary |
| `GET` | `/api/analyze/{ticker}` | AI analysis for one ticker. Optional: `?strategy=emotion_cycle` |
| `GET` | `/api/strategies` | List strategies. Optional: `?capability=analysis\|screen\|backtest` |
| `GET` | `/api/strategies/{id}` | Full strategy config + documentation |
| `GET` | `/api/screen` | Screener. Params: `strategy`, `asset_type`, `top_n`, `tickers` |
| `GET` | `/api/backtest` | Daily backtest. Params: `ticker`, `strategy`, `start_date`, `end_date`, cost params |
| `GET` | `/api/report/{profile_id}` | Generate + save a full report for a profile |
| `GET` | `/api/reports/{profile_id}` | List saved reports |
| `GET` | `/api/reports/{profile_id}/{report_id}` | Load a saved report |
| `GET` | `/api/reports/{profile_id}/{report_id}/download` | Download as `?format=md` or `?format=json` |
| `GET` | `/api/preferences/{profile_id}` | Get profile preferences |
| `PUT` | `/api/preferences/{profile_id}` | Update profile preferences |

Interactive docs: `http://localhost:8000/docs`

---

## Telegram Bot Commands

### On-demand

| Command | Description |
|---------|-------------|
| `/start` | Welcome message and command reference |
| `/report` | Full AI dashboard for your watchlist |
| `/summary` | Global market overview (indices, commodities, crypto) |
| `/analyze TICKER` | Deep-dive on one ticker, e.g. `/analyze AAPL` |
| `/ideas [strategy] [asset_type] [top_n]` | Ranked trade ideas, e.g. `/ideas commodity_macro commodity 5` |

### Watchlist management

| Command | Description |
|---------|-------------|
| `/watch TICKER` | Add a ticker, e.g. `/watch NVDA` |
| `/unwatch TICKER` | Remove a ticker |
| `/watchlist` | Show watchlist and all current settings |

### Scheduled push settings

| Command | Description |
|---------|-------------|
| `/schedule daily\|twice\|weekly\|off` | Push frequency |
| `/timezone ZONE` | IANA timezone, e.g. `/timezone America/New_York` |
| `/pushtime HH:MM` | Push time in 24h local time, e.g. `/pushtime 08:30` |
| `/sections watchlist,market,commodity` | Which sections are included in scheduled pushes |
| `/strategy breakout,pullback` | Default strategies used for screening |
| `/reportmode summary\|ideas\|summary+ideas` | What watchlist reports contain |
| `/language en\|zh` | Report language |

---

## Strategies

| ID | Asset types | Capabilities | Description |
|----|-------------|--------------|-------------|
| `breakout` | stock | analysis, screen, backtest | Price breaks above recent range with volume |
| `pullback` | stock | analysis, screen, backtest | Buy the dip in an uptrend |
| `commodity_macro` | commodity | analysis, screen, backtest | Trend + macro filter for commodities |
| `trend_following` | stock, commodity | analysis, screen, backtest | Multi-timeframe trend alignment |
| `mean_reversion` | stock, commodity | analysis, screen, backtest | Oversold bounce in a range |
| `donchian_breakout` | stock, commodity | analysis, screen, backtest | Donchian channel breakout |
| `emotion_cycle` | stock, commodity | analysis only | Sentiment and fear/greed positioning |

Strategy definitions live in `strategies/` — each has a `.yaml` (metadata) and `.md` (LLM prompt documentation). You can add your own by following the same format.

---

## Switching LLM Providers

Change one line in `.env` (local) or the `LLM_MODEL` repository variable (GitHub Actions):

```bash
LLM_MODEL=gemini/gemini-1.5-flash              # Google Gemini (free)
LLM_MODEL=anthropic/claude-sonnet-4-6           # Anthropic Claude
LLM_MODEL=gpt-4o                                # OpenAI GPT-4o
LLM_MODEL=groq/llama-3.3-70b-versatile          # Groq Llama (free, fast)
```

Set the matching API key. All routing is handled by [LiteLLM](https://github.com/BerriAI/litellm) — no code changes needed.

---

## Project Structure

```
stock-assistant/
├── main.py                       # FastAPI app + APScheduler + Telegram bot startup
├── requirements.txt
├── .env.example
├── scripts/
│   └── run_report.py             # Standalone CLI — used by GitHub Actions and cron
├── app/
│   └── services/
│       ├── research_service.py   # Shared orchestration (API, bot, CLI)
│       └── report_service.py     # Report composition, persistence, push messages
├── core/
│   ├── market_data.py            # yfinance price fetching
│   ├── news.py                   # NewsAPI with 1-hour cache
│   ├── ai_analysis.py            # LiteLLM prompt building + LLM calls
│   ├── strategy_registry.py      # Loads YAML + MD strategy definitions
│   ├── scheduler.py              # APScheduler per-user push jobs
│   └── preferences.py            # Per-user preference store (JSON)
├── strategies/                   # Strategy definitions (YAML + Markdown)
├── research/strategies/          # Per-strategy screener implementations
├── backtesting/engine.py         # Deterministic daily backtest engine
├── channels/telegram/bot.py      # Telegram command handlers
├── data/preferences.json         # Persisted user preferences
├── reports/<profile_id>/         # Saved reports (auto-created)
└── web/index.html                # Dashboard frontend

.github/
└── workflows/
    └── stock-report.yml          # GitHub Actions: scheduled + manual delivery
```

---

## API Keys

| Service | URL | Notes |
|---------|-----|-------|
| Google Gemini | [aistudio.google.com](https://aistudio.google.com) | Free, instant |
| Anthropic Claude | [console.anthropic.com](https://console.anthropic.com) | Pay-as-you-go |
| OpenAI | [platform.openai.com](https://platform.openai.com) | Pay-as-you-go |
| Groq | [console.groq.com](https://console.groq.com) | Free tier, fast |
| NewsAPI | [newsapi.org/register](https://newsapi.org/register) | Free, 100 req/day |
| Telegram Bot | Message `@BotFather` on Telegram | Free, instant |

---

## Disclaimer

All AI-generated analysis is for informational purposes only. This is not financial advice. Always do your own research before making any investment decisions.
