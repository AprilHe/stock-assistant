"""
core/ai_analysis.py
Builds prompts and calls the configured LLM via LiteLLM.
Switch providers by changing LLM_MODEL in .env — no code changes needed.

generate_market_summary() returns a structured decision dashboard
rendered from a JSON response from the LLM.
"""

import json
import os
from datetime import datetime, timedelta, timezone as dt_tz

import yfinance as yf
from litellm import completion
from dotenv import load_dotenv

from core.news import get_market_news

load_dotenv()

LLM_MODEL = os.getenv("LLM_MODEL", "gemini/gemini-1.5-flash")

DISCLAIMER = (
    "\n\n⚠️ For informational purposes only. "
    "Not financial advice. Always do your own research."
)

_SIGNAL_EMOJI_EN = {"Buy": "🟢", "Hold": "🟡", "Sell": "🔴"}
_SIGNAL_EMOJI_ZH = {"买入": "🟢", "观望": "🟡", "卖出": "🔴"}

_VALIDITY_HOURS = {"daily": 24, "twice": 12, "weekly": 168, "off": 24}


# ── LLM call ──────────────────────────────────────────────────────────────────

def _call_llm(prompt: str) -> str:
    """Calls the configured LLM and returns the text response."""
    response = completion(
        model=LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content.strip()


# ── News helpers ───────────────────────────────────────────────────────────────

def _news_age_label(published_at_str: str, language: str = "en") -> str:
    """Returns a recency label like [Today] / [昨天] based on publishedAt."""
    if not published_at_str:
        return ""
    try:
        pub = datetime.fromisoformat(published_at_str.replace("Z", "+00:00"))
        hours_ago = (datetime.now(dt_tz.utc) - pub).total_seconds() / 3600
        if language == "zh":
            if hours_ago < 24:
                return "[今日]"
            elif hours_ago < 48:
                return "[昨天]"
            return f"[{int(hours_ago / 24)}天前]"
        else:
            if hours_ago < 24:
                return "[Today]"
            elif hours_ago < 48:
                return "[Yesterday]"
            return f"[{int(hours_ago / 24)}d ago]"
    except (ValueError, TypeError):
        return ""


# ── Dashboard renderer ────────────────────────────────────────────────────────

def _validity_note(schedule: str, generated_at: datetime, language: str) -> str:
    hours = _VALIDITY_HOURS.get(schedule, 24)
    valid_until = generated_at + timedelta(hours=hours)
    valid_str = valid_until.strftime("%Y-%m-%d %H:%M")
    period = f"{hours}h" if hours < 48 else f"{hours // 24} days"
    if language == "zh":
        period_zh = f"{hours}小时" if hours < 48 else f"{hours // 24}天"
        return f"⏳ 有效期: {period_zh}（至 {valid_str} UTC）"
    return f"⏳ Valid for {period} (until {valid_str} UTC)"


def _render_dashboard(
    llm_json_str: str,
    market_data: dict,
    generated_at: datetime,
    schedule: str,
    language: str,
) -> str:
    """
    Parses the LLM JSON response and renders a structured decision dashboard.
    Falls back to raw LLM text if JSON parsing fails.
    """
    # Strip accidental markdown fences the LLM might add
    cleaned = (
        llm_json_str.strip()
        .removeprefix("```json")
        .removeprefix("```")
        .removesuffix("```")
        .strip()
    )

    try:
        parsed = json.loads(cleaned)
        tickers = parsed["tickers"]
    except (json.JSONDecodeError, KeyError):
        return llm_json_str  # graceful fallback

    emoji_map = _SIGNAL_EMOJI_ZH if language == "zh" else _SIGNAL_EMOJI_EN

    # Signal counts
    counts: dict[str, int] = {}
    for t in tickers:
        sig = t.get("signal", "")
        counts[sig] = counts.get(sig, 0) + 1

    date_str = generated_at.strftime("%Y-%m-%d")
    time_str = generated_at.strftime("%Y-%m-%d %H:%M")
    n = len(tickers)

    if language == "zh":
        buy_k, hold_k, sell_k = "买入", "观望", "卖出"
        header = f"🎯 {date_str} 决策仪表盘"
        count_line = (
            f"共分析 {n} 只 | "
            f"🟢买入:{counts.get(buy_k, 0)} "
            f"🟡观望:{counts.get(hold_k, 0)} "
            f"🔴卖出:{counts.get(sell_k, 0)}"
        )
        summary_label = "📊 摘要"
        score_label, risk_label, validity_label = "评分", "⚠️ 风险", "⏰ 时效性"
        decision_label = "一句话决策"
        time_label = f"报告生成时间: {time_str}"
    else:
        buy_k, hold_k, sell_k = "Buy", "Hold", "Sell"
        header = f"🎯 {date_str} Market Dashboard"
        count_line = (
            f"Analysed {n} ticker(s) | "
            f"🟢 Buy:{counts.get(buy_k, 0)} "
            f"🟡 Hold:{counts.get(hold_k, 0)} "
            f"🔴 Sell:{counts.get(sell_k, 0)}"
        )
        summary_label = "📊 Summary"
        score_label, risk_label, validity_label = "Score", "⚠️ Risk", "⏰ Validity"
        decision_label = "Decision"
        time_label = f"Report generated: {time_str}"

    lines = [header, count_line, "", summary_label]

    # Summary table — one line per ticker
    for t in tickers:
        sym = t.get("symbol", "?")
        sig = t.get("signal", "")
        score = t.get("score", 50)
        one_line = t.get("one_line", "")
        emoji = emoji_map.get(sig, "🟡")
        # Append live % change if available
        price_info = ""
        md = market_data.get(sym, {})
        if not md.get("error") and md.get("change_pct") is not None:
            chg = md["change_pct"]
            arrow = "▲" if chg >= 0 else "▼"
            price_info = f" | {arrow}{abs(chg):.1f}%"
        lines.append(f"{emoji} {sym}: {sig} | {score_label} {score}{price_info} | {one_line}")

    lines += ["", "---"]

    # Detail card per ticker
    for t in tickers:
        sym = t.get("symbol", "?")
        sig = t.get("signal", "")
        score = t.get("score", 50)
        one_line = t.get("one_line", "")
        validity = t.get("validity", "")
        risk = t.get("risk", "")
        emoji = emoji_map.get(sig, "🟡")

        lines.append(f"\n{emoji} {sym}")
        lines.append(f"📌 {sig} | {score_label} {score}")
        lines.append(f"> {decision_label}: {one_line}")
        if validity:
            lines.append(f"{validity_label}: {validity}")
        if risk:
            lines.append(f"{risk_label}: {risk}")

    lines += ["", "---", time_label, _validity_note(schedule, generated_at, language)]

    return "\n".join(lines)


# ── Public API ────────────────────────────────────────────────────────────────

def generate_market_summary(
    market_data: dict,
    news: list,
    schedule: str = "daily",
    language: str = "en",
) -> str:
    """
    Builds a structured decision dashboard from price data + news.
    The LLM returns a JSON object; Python renders it into a formatted message.
    """
    # Format price data
    price_lines = []
    for name, data in market_data.items():
        if data.get("error"):
            price_lines.append(f"  {name}: data unavailable")
        else:
            direction = "▲" if data["change_pct"] >= 0 else "▼"
            price_lines.append(
                f"  {name} ({data['ticker']}): ${data['price']:,.2f}"
                f"  {direction} {abs(data['change_pct']):.2f}%"
            )

    # Format news with age labels
    news_lines = []
    for i, article in enumerate(news[:5], 1):
        age = _news_age_label(article.get("published_at", ""), language)
        news_lines.append(f"  {i}. {age} {article['title']}")

    if language == "zh":
        signal_vals = "买入 / 观望 / 卖出"
        validity_vals = "今日内 | 3天内 | 本周内"
        validity_guide = "|change|>3% → 今日内; 1-3% → 3天内; <1% → 本周内"
        score_guide = "买入=60-100, 观望=35-65, 卖出=0-40"
        lang_instruction = "All text fields (one_line, validity, risk) must be in Chinese."
    else:
        signal_vals = "Buy / Hold / Sell"
        validity_vals = "Today | 3 days | This week"
        validity_guide = "|change|>3% → Today; 1-3% → 3 days; <1% → This week"
        score_guide = "Buy=60-100, Hold=35-65, Sell=0-40"
        lang_instruction = "All text fields must be in English."

    # Build ticker list for the prompt (use ticker symbols from market_data)
    ticker_symbols = [v.get("ticker", k) for k, v in market_data.items() if not v.get("error")]

    prompt = f"""You are a financial analyst. Analyze the market data and news below.
Output raw JSON only — no markdown, no code fences, no explanation.

MARKET DATA:
{chr(10).join(price_lines)}

RECENT NEWS (past 48h):
{chr(10).join(news_lines)}

Output a JSON object with this exact structure:
{{
  "tickers": [
    {{
      "symbol": "<ticker symbol from market data>",
      "signal": "<{signal_vals}>",
      "score": <integer 0-100>,
      "one_line": "<brief decision rationale, ≤12 words>",
      "validity": "<{validity_vals}>",
      "risk": "<key risk factor, ≤10 words>"
    }}
  ]
}}

Include one entry for each of these tickers: {', '.join(ticker_symbols)}
Score guide: {score_guide}
Validity guide: {validity_guide}
{lang_instruction}
Output only the JSON object, nothing else."""

    generated_at = datetime.now(dt_tz.utc)
    raw = _call_llm(prompt)
    return _render_dashboard(raw, market_data, generated_at, schedule, language) + DISCLAIMER


def _clean_json_text(raw: str) -> str:
    return (
        raw.strip()
        .removeprefix("```json")
        .removeprefix("```")
        .removesuffix("```")
        .strip()
    )


def _normalize_ticker_analysis(parsed: dict) -> dict:
    proposal = str(parsed.get("proposal", "Hold")).strip().title()
    if proposal not in {"Buy", "Hold", "Sell"}:
        proposal = "Hold"
    horizon = str(parsed.get("horizon", "weeks_to_months")).strip().lower()
    confidence = parsed.get("confidence", 50)
    try:
        confidence = int(confidence)
    except (TypeError, ValueError):
        confidence = 50
    confidence = max(0, min(100, confidence))
    summary = str(parsed.get("summary", "")).strip()
    reasoning = [str(x).strip() for x in parsed.get("reasoning", []) if str(x).strip()][:4]
    risks = [str(x).strip() for x in parsed.get("risks", []) if str(x).strip()][:4]
    triggers = [str(x).strip() for x in parsed.get("triggers", []) if str(x).strip()][:4]
    return {
        "proposal": proposal,
        "horizon": horizon,
        "confidence": confidence,
        "summary": summary,
        "reasoning": reasoning,
        "risks": risks,
        "triggers": triggers,
    }


def _format_ticker_analysis(analysis: dict, ticker: str) -> str:
    lines = [
        f"Ticker: {ticker.upper()}",
        f"Proposal: {analysis['proposal']}",
        f"Horizon: {analysis['horizon']}",
        f"Confidence: {analysis['confidence']}/100",
    ]
    if analysis["summary"]:
        lines.extend(["", f"Summary: {analysis['summary']}"])
    if analysis["reasoning"]:
        lines.append("")
        lines.append("Reasoning:")
        lines.extend([f"- {item}" for item in analysis["reasoning"]])
    if analysis["risks"]:
        lines.append("")
        lines.append("Risks:")
        lines.extend([f"- {item}" for item in analysis["risks"]])
    if analysis["triggers"]:
        lines.append("")
        lines.append("Watch Triggers:")
        lines.extend([f"- {item}" for item in analysis["triggers"]])
    return "\n".join(lines)


def analyze_ticker_structured(
    ticker: str,
    company_name: str = "",
    strategy_context: str = "",
) -> dict:
    """
    Fetches 1-month price history and recent news for a single ticker,
    then returns a structured analysis payload.
    """
    try:
        tk = yf.Ticker(ticker.upper())
        df = tk.history(period="1mo")
        if df.empty:
            price_summary = f"No price data available for {ticker.upper()}."
        else:
            start_price = df["Close"].iloc[0]
            end_price = df["Close"].iloc[-1]
            month_change = ((end_price - start_price) / start_price) * 100
            high = df["High"].max()
            low = df["Low"].min()
            price_summary = (
                f"Current price: ${end_price:,.2f}\n"
                f"1-month change: {month_change:+.2f}%\n"
                f"1-month high: ${high:,.2f} | low: ${low:,.2f}"
            )
    except Exception as e:
        price_summary = f"Price data fetch failed: {e}"

    query = company_name if company_name else ticker
    news = get_market_news(query=query, num_articles=5)
    news_lines = [f"  {i}. {a['title']}" for i, a in enumerate(news[:5], 1)]

    display_name = f"{company_name} ({ticker.upper()})" if company_name else ticker.upper()

    strategy_section = (
        f"\nSTRATEGY GUIDANCE:\n{strategy_context}\n\n"
        if strategy_context.strip()
        else ""
    )

    prompt = f"""You are a concise stock analyst. Analyze {display_name} based on the data below.
Output valid raw JSON only. No markdown, no code fences.

PRICE DATA (1 month):
{price_summary}

RECENT NEWS:
{chr(10).join(news_lines) if news_lines else "  No recent news found."}
{strategy_section}

Return JSON with this exact structure:
{{
  "proposal": "<Buy|Hold|Sell>",
  "horizon": "<days_to_weeks|weeks_to_months|months_plus>",
  "confidence": <integer 0-100>,
  "summary": "<one concise paragraph, <=45 words>",
  "reasoning": ["<point 1>", "<point 2>", "<point 3>"],
  "risks": ["<risk 1>", "<risk 2>", "<risk 3>"],
  "triggers": ["<what to monitor next 1>", "<what to monitor next 2>"]
}}

Keep each reasoning/risk/trigger item <=14 words.
Be factual and balanced. Do not include investment advice disclaimers in JSON."""

    raw = _call_llm(prompt)
    cleaned = _clean_json_text(raw)
    try:
        parsed = json.loads(cleaned)
        return _normalize_ticker_analysis(parsed)
    except (json.JSONDecodeError, TypeError):
        return {
            "proposal": "Hold",
            "horizon": "weeks_to_months",
            "confidence": 50,
            "summary": "Model returned unstructured output. Please retry for a cleaner structured analysis.",
            "reasoning": [cleaned[:220] if cleaned else "No model output available."],
            "risks": ["Model output format mismatch."],
            "triggers": ["Retry analysis.", "Review price action manually."],
        }


def analyze_ticker(
    ticker: str,
    company_name: str = "",
    strategy_context: str = "",
) -> str:
    """
    Backward-compatible text analysis built from structured output.
    """
    structured = analyze_ticker_structured(
        ticker=ticker,
        company_name=company_name,
        strategy_context=strategy_context,
    )
    return render_ticker_analysis_text(structured, ticker)


def render_ticker_analysis_text(structured: dict, ticker: str) -> str:
    return _format_ticker_analysis(structured, ticker) + DISCLAIMER


if __name__ == "__main__":
    from core.market_data import get_market_snapshot

    print(f"Using LLM model: {LLM_MODEL}\n")

    print("--- Market Dashboard (EN) ---")
    market_data = get_market_snapshot()
    news = get_market_news()
    print(generate_market_summary(market_data, news, schedule="daily", language="en"))

    print("\n--- Market Dashboard (ZH) ---")
    print(generate_market_summary(market_data, news, schedule="daily", language="zh"))
