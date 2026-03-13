#!/usr/bin/env python3
"""
scripts/run_report.py

Standalone CLI entrypoint for GitHub Actions / cron-triggered report generation.
Runs without a running FastAPI server.

Usage (run from stock-assistant/ directory):
    python scripts/run_report.py
    python scripts/run_report.py --watchlist "AAPL,NVDA,^GSPC" --send-telegram

Environment variables (set as GitHub Secrets/Variables or in .env):
    LLM_MODEL              — e.g. gemini/gemini-1.5-flash
    GEMINI_API_KEY         — Google Gemini
    ANTHROPIC_API_KEY      — Anthropic Claude
    OPENAI_API_KEY         — OpenAI
    GROQ_API_KEY           — Groq

    NEWS_API_KEY           — NewsAPI.org

    TELEGRAM_BOT_TOKEN     — required for --send-telegram
    TELEGRAM_CHAT_ID       — required for --send-telegram

    WATCHLIST              — comma-separated tickers (default: ^GSPC,^IXIC,BTC-USD)
    STRATEGIES             — comma-separated strategy IDs (default: breakout)
    REPORT_LANGUAGE        — en or zh (default: en)
    REPORT_SECTIONS        — comma-separated: watchlist,market,commodity (default: watchlist,market)
    SEND_TELEGRAM          — 1/true/yes to enable (default: false)
"""

import argparse
import os
import sys
from datetime import datetime, timezone as dt_tz
from pathlib import Path

# Ensure project modules are importable when script is run from stock-assistant/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
load_dotenv()

_TELEGRAM_MAX_CHARS = 4000  # Telegram API limit is 4096; keep a small margin


def _send_telegram(token: str, chat_id: str, text: str) -> None:
    """Send text to a Telegram chat, splitting into chunks if needed."""
    import requests

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for i in range(0, len(text), _TELEGRAM_MAX_CHARS):
        chunk = text[i : i + _TELEGRAM_MAX_CHARS]
        resp = requests.post(
            url,
            json={"chat_id": chat_id, "text": chunk},
            timeout=30,
        )
        if not resp.ok:
            print(
                f"[WARN] Telegram send failed: {resp.status_code} {resp.text}",
                file=sys.stderr,
            )


def _write_github_summary(report_md: str, report_id: str) -> None:
    """Append the report to GitHub Actions step summary if running in CI."""
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_file:
        return
    with open(summary_file, "a", encoding="utf-8") as f:
        f.write(f"## Stock Assistant Report — `{report_id}`\n\n")
        f.write(report_md)
        f.write("\n")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a stock market report and optionally notify via Telegram."
    )
    parser.add_argument(
        "--watchlist",
        default=os.environ.get("WATCHLIST", "^GSPC,^IXIC,BTC-USD"),
        help="Comma-separated tickers (default: ^GSPC,^IXIC,BTC-USD)",
    )
    parser.add_argument(
        "--strategies",
        default=os.environ.get("STRATEGIES", "breakout"),
        help="Comma-separated strategy IDs (default: breakout)",
    )
    parser.add_argument(
        "--language",
        default=os.environ.get("REPORT_LANGUAGE", "en"),
        choices=["en", "zh"],
        help="Report language: en or zh (default: en)",
    )
    parser.add_argument(
        "--sections",
        default=os.environ.get("REPORT_SECTIONS", "watchlist,market"),
        help="Report sections: watchlist,market,commodity (default: watchlist,market)",
    )
    parser.add_argument(
        "--schedule",
        default="weekly",
        choices=["daily", "twice", "weekly", "off"],
        help="Schedule label used in LLM prompt context (default: weekly)",
    )
    parser.add_argument(
        "--send-telegram",
        action="store_true",
        default=os.environ.get("SEND_TELEGRAM", "").lower() in ("1", "true", "yes"),
        help="Send report to Telegram (requires TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID)",
    )
    parser.add_argument(
        "--chat-id",
        default=os.environ.get("TELEGRAM_CHAT_ID", ""),
        help="Telegram chat/channel ID (overrides TELEGRAM_CHAT_ID env var)",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    watchlist = [t.strip() for t in args.watchlist.split(",") if t.strip()]
    strategies = [s.strip() for s in args.strategies.split(",") if s.strip()]
    sections = [s.strip() for s in args.sections.split(",") if s.strip()]

    if not watchlist:
        print("[ERROR] Watchlist is empty.", file=sys.stderr)
        sys.exit(1)

    prefs = {
        "watchlist": watchlist,
        "strategies": strategies,
        "report_sections": sections,
        "report_mode": "summary+ideas",
        "schedule": args.schedule,
        "timezone": "UTC",
        "push_time": "08:00",
        "language": args.language,
    }

    ts = datetime.now(dt_tz.utc).isoformat()
    print(f"[{ts}] Generating report...")
    print(f"  Watchlist  : {', '.join(watchlist)}")
    print(f"  Strategies : {', '.join(strategies)}")
    print(f"  Sections   : {', '.join(sections)}")
    print(f"  Language   : {args.language}")
    print(f"  Telegram   : {'yes' if args.send_telegram else 'no'}")

    from app.services.report_service import generate_and_save_report

    result = generate_and_save_report("github-actions", prefs)
    report_md = result["report"]
    report_id = result["report_id"]
    saved_files = result["files"]

    print(f"\nReport ID  : {report_id}")
    print(f"Saved MD   : {saved_files['markdown_path']}")
    print(f"Saved JSON : {saved_files['json_path']}")

    # Write to GitHub Actions job summary
    _write_github_summary(report_md, report_id)

    # Print full report to Actions log
    print("\n" + "=" * 60)
    print(report_md)
    print("=" * 60)

    # Telegram delivery
    if args.send_telegram:
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        chat_id = args.chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")
        if not token:
            print("[ERROR] TELEGRAM_BOT_TOKEN is not set.", file=sys.stderr)
            sys.exit(1)
        if not chat_id:
            print(
                "[ERROR] TELEGRAM_CHAT_ID is not set (use --chat-id or env var).",
                file=sys.stderr,
            )
            sys.exit(1)
        print(f"\nSending to Telegram chat {chat_id}...")
        _send_telegram(token, chat_id, report_md)
        print("Telegram notification sent.")


if __name__ == "__main__":
    main()
