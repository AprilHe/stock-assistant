"""
channels/telegram/bot.py
Telegram bot commands:
  /start              — welcome + help
  /report             — AI dashboard for your watchlist right now
  /fullreport         — full saved report markdown for your watchlist
  /summary            — global market summary (AI-generated)
  /analyze TICKER     — AI analysis of a specific stock
  /ideas              — ranked breakout ideas (watchlist universe)
  /watch TICKER       — add a ticker to your personal watchlist
  /unwatch TICKER     — remove a ticker from your watchlist
  /watchlist          — show your watchlist, schedule, timezone, language
  /sections ...       — choose scheduled bot push sections
  /pushmode MODE      — scheduled push style: simple | full
  /schedule FREQ      — set push frequency: daily | twice | weekly | off
  /timezone ZONE      — set your timezone (e.g. Asia/Shanghai)
  /pushtime HH:MM     — set push time in 24h local time (e.g. 09:30)
  /language LANG      — set report language: en | zh
  /risk LEVEL         — set risk profile: conservative | moderate | aggressive
  /maxpos N           — set max single position size (e.g. 5 for 5%)
  /horizon STYLE      — set preferred horizon: swing | day | longterm

Runs in a background thread so it doesn't block FastAPI's event loop.
"""

import asyncio
import logging
import threading
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

from core.preferences import (
    get_prefs, add_ticker, remove_ticker,
    set_schedule, set_timezone, set_push_time, set_language, set_strategies, set_report_mode,
    set_report_sections, set_push_mode,
    REPORT_MODE_OPTIONS, REPORT_SECTION_OPTIONS, SCHEDULE_OPTIONS, STRATEGY_OPTIONS, PUSH_MODE_OPTIONS,
)
from core.portfolio_store import get_user_profile, save_user_profile

logger = logging.getLogger(__name__)

SCHEDULE_LABELS = {
    "daily":  "every day at your push time",
    "twice":  "every day at your push time and +8h",
    "weekly": "every Monday at your push time",
    "off":    "disabled",
}


# ── Commands ───────────────────────────────────────────────────────────────────
_TELEGRAM_MAX_CHARS = 4000


def _chunk_text(text: str, max_chars: int = _TELEGRAM_MAX_CHARS) -> list[str]:
    return [text[i:i + max_chars] for i in range(0, len(text), max_chars)] or [""]


def _log_chat_id(update: Update, source: str) -> None:
    chat = update.effective_chat
    user = update.effective_user
    if not chat:
        return
    logger.info(
        "Telegram update via /%s: chat_id=%s chat_type=%s user_id=%s username=%s",
        source,
        chat.id,
        chat.type,
        user.id if user else "n/a",
        user.username if user else "n/a",
    )


def _parse_ideas_args(args: list[str]) -> tuple[str, str, int]:
    strategy = "breakout"
    asset_type = "stock"
    top_n = 5
    if not args:
        return strategy, asset_type, top_n

    if len(args) >= 1:
        strategy = args[0].lower()
    if len(args) >= 2:
        asset_type = args[1].lower()
    if len(args) >= 3:
        top_n = int(args[2])

    return strategy, asset_type, top_n


def _parse_pct_arg(arg: str) -> float:
    """Parse '5', '5%', or '0.05' → 0.05 (decimal fraction)."""
    val = float(arg.strip().rstrip("%"))
    return val / 100.0 if val > 1.0 else val


def _parse_strategy_args(args: list[str]) -> list[str]:
    raw = ",".join(args)
    strategies = [part.strip().lower() for part in raw.split(",") if part.strip()]
    return list(dict.fromkeys(strategies))


def _parse_sections_args(args: list[str]) -> list[str]:
    raw = ",".join(args)
    sections = [part.strip().lower() for part in raw.split(",") if part.strip()]
    if "watchlist" not in sections:
        sections.insert(0, "watchlist")
    return list(dict.fromkeys(sections))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _log_chat_id(update, "start")
    chat_id = str(update.effective_chat.id)
    prefs = get_prefs(chat_id)
    await update.message.reply_text(
        "👋 Welcome to Stock Assistant!\n\n"
        "On-demand:\n"
        "  /report — AI dashboard for your watchlist\n"
        "  /fullreport — full detailed markdown report\n"
        "  /summary — global market overview\n"
        "  /analyze TICKER — deep-dive on any stock\n\n"
        "  /ideas [strategy] [asset_type] [top_n]\n"
        "          e.g. /ideas commodity_macro commodity 5\n\n"
        "  /strategy breakout,pullback,commodity_macro\n\n"
        "  /reportmode summary+ideas\n\n"
        "  /sections watchlist,market,commodity\n\n"
        "  /pushmode simple | full\n\n"
        "Watchlist:\n"
        "  /watch TICKER — add (e.g. /watch AAPL)\n"
        "  /unwatch TICKER — remove\n"
        "  /watchlist — show watchlist + settings\n\n"
        "Schedule:\n"
        "  /schedule daily | twice | weekly | off\n"
        "  /timezone ZONE — e.g. /timezone Asia/Shanghai\n"
        "  /pushtime HH:MM — e.g. /pushtime 09:30\n\n"
        "Language:\n"
        "  /language en — English (default)\n"
        "  /language zh — Chinese\n\n"
        f"Current schedule: {SCHEDULE_LABELS[prefs['schedule']]} "
        f"| {prefs['push_time']} {prefs['timezone']}"
    )


async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """AI decision dashboard for the user's personal watchlist."""
    _log_chat_id(update, "report")
    chat_id = str(update.effective_chat.id)
    prefs = get_prefs(chat_id)
    watchlist = prefs["watchlist"]

    if not watchlist:
        await update.message.reply_text(
            "Your watchlist is empty. Add tickers with /watch TICKER."
        )
        return

    await update.message.reply_text(
        f"Fetching data for: {', '.join(watchlist)}..."
    )
    try:
        from app.services.report_service import build_telegram_report_text

        result = build_telegram_report_text(chat_id, prefs)
        for chunk in _chunk_text(result):
            await update.message.reply_text(chunk)
    except Exception as e:
        logger.error("/report failed for %s: %s", chat_id, e)
        await update.message.reply_text(f"Error generating report: {e}")


async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Global market overview (fixed set of major indices/assets)."""
    chat_id = str(update.effective_chat.id)
    prefs = get_prefs(chat_id)
    await update.message.reply_text("Fetching global market data...")
    try:
        from app.services.research_service import build_global_summary_response

        result = build_global_summary_response(
            schedule=prefs["schedule"],
            language=prefs["language"],
        )
        await update.message.reply_text(result.summary)
    except Exception as e:
        logger.error("/summary failed: %s", e)
        await update.message.reply_text(f"Error generating summary: {e}")


async def fullreport(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate and send a full detailed report markdown."""
    chat_id = str(update.effective_chat.id)
    prefs = get_prefs(chat_id)
    watchlist = prefs["watchlist"]
    if not watchlist:
        await update.message.reply_text("Your watchlist is empty. Add tickers with /watch TICKER.")
        return

    await update.message.reply_text("Generating full report...")
    try:
        from app.services.report_service import generate_and_save_report

        generated = generate_and_save_report(chat_id, prefs)
        for chunk in _chunk_text(generated["report"]):
            await update.message.reply_text(chunk)
    except Exception as e:
        logger.error("/fullreport failed for %s: %s", chat_id, e)
        await update.message.reply_text(f"Error generating full report: {e}")


async def analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /analyze TICKER\nExample: /analyze META")
        return

    ticker = context.args[0].upper()
    await update.message.reply_text(f"Analyzing {ticker}...")
    try:
        from app.services.research_service import build_ticker_analysis_response
        result = build_ticker_analysis_response(ticker)
        await update.message.reply_text(f"🔍 {result.ticker} Analysis\n\n{result.analysis}")
    except ValueError as e:
        await update.message.reply_text(str(e))
    except Exception as e:
        logger.error("/analyze %s failed: %s", ticker, e)
        await update.message.reply_text(f"Error analyzing {ticker}: {e}")


async def ideas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    prefs = get_prefs(chat_id)
    watchlist = prefs["watchlist"]
    if not watchlist:
        await update.message.reply_text("Your watchlist is empty. Add tickers with /watch TICKER.")
        return

    await update.message.reply_text("Screening ideas...")
    try:
        from app.services.report_service import build_telegram_ideas_text

        if context.args:
            strategy, asset_type, top_n = _parse_ideas_args(context.args)
            scoped_watchlist = [
                symbol for symbol in watchlist
                if symbol.endswith("=F") == (asset_type == "commodity")
            ]
            result = build_telegram_ideas_text(
                profile_id=chat_id,
                watchlist=scoped_watchlist,
                strategies=[strategy],
                top_n=top_n,
            )
            for chunk in _chunk_text(result):
                await update.message.reply_text(chunk)
            return

        result = build_telegram_ideas_text(
            profile_id=chat_id,
            watchlist=watchlist,
            strategies=prefs.get("strategies", ["breakout"]),
            top_n=5,
        )
        for chunk in _chunk_text(result):
            await update.message.reply_text(chunk)
    except ValueError as e:
        await update.message.reply_text(
            f"{e}\nUsage: /ideas [strategy] [asset_type] [top_n]"
        )
    except Exception as e:
        logger.error("/ideas failed for %s: %s", chat_id, e)
        await update.message.reply_text(f"Error generating ideas: {e}")


async def watch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    if not context.args:
        await update.message.reply_text("Usage: /watch TICKER\nExample: /watch AAPL")
        return

    ticker = context.args[0].upper()
    added = add_ticker(chat_id, ticker)
    prefs = get_prefs(chat_id)
    if added:
        await update.message.reply_text(
            f"Added {ticker} to your watchlist.\n"
            f"Current watchlist: {', '.join(prefs['watchlist'])}"
        )
    else:
        await update.message.reply_text(f"{ticker} is already in your watchlist.")


async def unwatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    if not context.args:
        await update.message.reply_text("Usage: /unwatch TICKER\nExample: /unwatch AAPL")
        return

    ticker = context.args[0].upper()
    removed = remove_ticker(chat_id, ticker)
    if removed:
        prefs = get_prefs(chat_id)
        remaining = ', '.join(prefs['watchlist']) if prefs['watchlist'] else "(empty)"
        await update.message.reply_text(f"Removed {ticker}.\nWatchlist: {remaining}")
    else:
        await update.message.reply_text(f"{ticker} wasn't in your watchlist.")


async def watchlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    prefs = get_prefs(chat_id)
    tickers = prefs["watchlist"]
    ticker_str = "\n".join(f"  • {t}" for t in tickers) if tickers else "  (empty)"
    strategies = ", ".join(prefs.get("strategies", ["breakout"]))
    sections = ", ".join(prefs.get("report_sections", ["watchlist"]))
    report_mode = prefs.get("report_mode", "summary")
    push_mode = prefs.get("push_mode", "simple")
    lang_label = "English" if prefs["language"] == "en" else "中文"
    await update.message.reply_text(
        f"📋 Your Watchlist\n{ticker_str}\n\n"
        f"🧠 Strategies: {strategies}\n"
        f"📨 Bot sections: {sections}\n"
        f"📬 Push mode: {push_mode}\n"
        f"📰 Report mode: {report_mode}\n"
        f"📅 Schedule: {SCHEDULE_LABELS[prefs['schedule']]}\n"
        f"🕐 Push time: {prefs['push_time']} ({prefs['timezone']})\n"
        f"🌐 Language: {lang_label}\n\n"
        "Change with /strategy | /sections | /pushmode | /reportmode | /schedule | /timezone | /pushtime | /language"
    )


async def strategy_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    prefs = get_prefs(chat_id)
    current = ", ".join(prefs.get("strategies", ["breakout"]))
    if not context.args:
        await update.message.reply_text(
            f"Current strategies: {current}\n\n"
            f"Usage: /strategy [{', '.join(STRATEGY_OPTIONS)}]\n"
            "Examples:\n"
            "  /strategy breakout\n"
            "  /strategy breakout,pullback\n"
            "  /strategy commodity_macro"
        )
        return

    strategies = _parse_strategy_args(context.args)
    ok = set_strategies(chat_id, strategies)
    if ok:
        updated = ", ".join(get_prefs(chat_id).get("strategies", ["breakout"]))
        await update.message.reply_text(f"Strategies updated: {updated}")
    else:
        await update.message.reply_text(
            f"Choose from: {', '.join(STRATEGY_OPTIONS)}"
        )


async def reportmode_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    prefs = get_prefs(chat_id)
    current = prefs.get("report_mode", "summary")
    if not context.args:
        await update.message.reply_text(
            f"Current report mode: {current}\n\n"
            f"Usage: /reportmode [{' | '.join(REPORT_MODE_OPTIONS)}]"
        )
        return

    report_mode = context.args[0].lower()
    ok = set_report_mode(chat_id, report_mode)
    if ok:
        await update.message.reply_text(f"Report mode updated: {report_mode}")
    else:
        await update.message.reply_text(
            f"Choose from: {' | '.join(REPORT_MODE_OPTIONS)}"
        )


async def sections_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    prefs = get_prefs(chat_id)
    current = ", ".join(prefs.get("report_sections", ["watchlist"]))
    if not context.args:
        await update.message.reply_text(
            f"Current bot push sections: {current}\n\n"
            f"Usage: /sections [{', '.join(REPORT_SECTION_OPTIONS)}]\n"
            "Examples:\n"
            "  /sections watchlist\n"
            "  /sections watchlist,market\n"
            "  /sections watchlist,market,commodity\n\n"
            "Watchlist is always included as the first push."
        )
        return

    sections = _parse_sections_args(context.args)
    ok = set_report_sections(chat_id, sections)
    if ok:
        updated = ", ".join(get_prefs(chat_id).get("report_sections", ["watchlist"]))
        await update.message.reply_text(f"Bot push sections updated: {updated}")
    else:
        await update.message.reply_text(
            f"Choose from: {', '.join(REPORT_SECTION_OPTIONS)}"
        )


async def pushmode_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    prefs = get_prefs(chat_id)
    current = prefs.get("push_mode", "simple")
    if not context.args:
        await update.message.reply_text(
            f"Current push mode: {current}\n\n"
            f"Usage: /pushmode [{' | '.join(PUSH_MODE_OPTIONS)}]\n"
            "  simple — concise section-by-section pushes\n"
            "  full   — expanded section-by-section pushes\n"
            "  (legacy aliases: brief=simple, detailed=full)"
        )
        return

    push_mode = context.args[0].lower()
    ok = set_push_mode(chat_id, push_mode)
    if ok:
        updated_mode = get_prefs(chat_id).get("push_mode", "simple")
        await update.message.reply_text(f"Push mode updated: {updated_mode}")
    else:
        await update.message.reply_text(
            f"Choose from: {' | '.join(PUSH_MODE_OPTIONS)}"
        )


async def schedule_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    if not context.args:
        opts = " | ".join(SCHEDULE_OPTIONS)
        await update.message.reply_text(
            f"Usage: /schedule [{opts}]\n\n"
            "  daily  — every day at your push time\n"
            "  twice  — twice a day (+8h apart)\n"
            "  weekly — every Monday at your push time\n"
            "  off    — disable scheduled pushes"
        )
        return

    freq = context.args[0].lower()
    ok = set_schedule(chat_id, freq)
    if ok:
        from core.scheduler import reschedule_user
        reschedule_user(chat_id)
        await update.message.reply_text(f"Schedule updated: {SCHEDULE_LABELS[freq]}")
    else:
        await update.message.reply_text(
            f"Unknown option. Choose from: {' | '.join(SCHEDULE_OPTIONS)}"
        )


async def timezone_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    if not context.args:
        prefs = get_prefs(chat_id)
        await update.message.reply_text(
            f"Current timezone: {prefs['timezone']}\n\n"
            "Usage: /timezone IANA_TIMEZONE\n"
            "Examples:\n"
            "  /timezone Asia/Shanghai\n"
            "  /timezone America/New_York\n"
            "  /timezone Europe/London\n"
            "  /timezone UTC"
        )
        return

    tz_name = context.args[0]
    ok = set_timezone(chat_id, tz_name)
    if ok:
        from core.scheduler import reschedule_user
        reschedule_user(chat_id)
        prefs = get_prefs(chat_id)
        await update.message.reply_text(
            f"Timezone set to {tz_name}.\n"
            f"Reports will be sent at {prefs['push_time']} {tz_name}."
        )
    else:
        await update.message.reply_text(
            f"Unknown timezone: {tz_name}\n"
            "Use a valid IANA name, e.g. Asia/Shanghai, America/New_York, UTC."
        )


async def pushtime_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    if not context.args:
        prefs = get_prefs(chat_id)
        await update.message.reply_text(
            f"Current push time: {prefs['push_time']} ({prefs['timezone']})\n\n"
            "Usage: /pushtime HH:MM (24-hour)\n"
            "Examples: /pushtime 09:30  |  /pushtime 07:00"
        )
        return

    time_str = context.args[0]
    ok = set_push_time(chat_id, time_str)
    if ok:
        from core.scheduler import reschedule_user
        reschedule_user(chat_id)
        prefs = get_prefs(chat_id)
        await update.message.reply_text(
            f"Push time set to {prefs['push_time']} ({prefs['timezone']})."
        )
    else:
        await update.message.reply_text(
            "Invalid format. Use HH:MM in 24-hour format.\n"
            "Examples: 08:00, 09:30, 14:00"
        )


async def language_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    if not context.args:
        prefs = get_prefs(chat_id)
        lang_label = "English" if prefs["language"] == "en" else "中文"
        await update.message.reply_text(
            f"Current language: {lang_label}\n\n"
            "Usage: /language en | zh\n"
            "  en — English (default)\n"
            "  zh — Chinese (中文)"
        )
        return

    lang = context.args[0].lower()
    ok = set_language(chat_id, lang)
    if ok:
        label = "English" if lang == "en" else "中文"
        await update.message.reply_text(f"Report language set to {label}.")
    else:
        await update.message.reply_text("Choose from: en | zh")


# ── Profile commands ────────────────────────────────────────────────────────────

_RISK_OPTIONS = ("conservative", "moderate", "aggressive")
_HORIZON_OPTIONS = ("swing", "day", "longterm")


async def risk_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set or view risk profile. /risk [conservative|moderate|aggressive]"""
    chat_id = str(update.effective_chat.id)
    profile = get_user_profile(chat_id)

    if not context.args:
        await update.message.reply_text(
            f"Current risk profile: {profile.risk_profile}\n\n"
            "Usage: /risk conservative | moderate | aggressive"
        )
        return

    value = context.args[0].lower()
    if value not in _RISK_OPTIONS:
        await update.message.reply_text(
            f"Invalid value. Choose from: {' | '.join(_RISK_OPTIONS)}"
        )
        return

    profile.risk_profile = value
    save_user_profile(profile)
    await update.message.reply_text(f"Risk profile set to: {value}")


async def maxpos_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set or view max single position size. /maxpos [1-20]"""
    chat_id = str(update.effective_chat.id)
    profile = get_user_profile(chat_id)

    if not context.args:
        pct = round(profile.max_single_position * 100, 1)
        await update.message.reply_text(
            f"Current max single position: {pct}%\n\n"
            "Usage: /maxpos [1\u201320]\n"
            "  Examples: /maxpos 5  or  /maxpos 0.05"
        )
        return

    try:
        value = _parse_pct_arg(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid number. Example: /maxpos 5")
        return

    if not (0.01 <= value <= 0.20):
        await update.message.reply_text("Value must be between 1% and 20%.")
        return

    profile.max_single_position = value
    save_user_profile(profile)
    await update.message.reply_text(
        f"Max single position set to: {round(value * 100, 1)}%"
    )


async def horizon_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set or view preferred trading horizon. /horizon [swing|day|longterm]"""
    chat_id = str(update.effective_chat.id)
    profile = get_user_profile(chat_id)

    if not context.args:
        await update.message.reply_text(
            f"Current horizon: {profile.preferred_horizon}\n\n"
            "Usage: /horizon swing | day | longterm"
        )
        return

    value = context.args[0].lower()
    if value not in _HORIZON_OPTIONS:
        await update.message.reply_text(
            f"Invalid value. Choose from: {' | '.join(_HORIZON_OPTIONS)}"
        )
        return

    profile.preferred_horizon = value
    save_user_profile(profile)
    await update.message.reply_text(f"Preferred horizon set to: {value}")


# ── Bot runner ─────────────────────────────────────────────────────────────────

def run_bot(token: str):
    """
    Builds and starts the Telegram bot in a background thread.
    Uses the async API directly to avoid signal-handler restrictions
    that prevent run_polling() from working outside the main thread.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def _run():
        app = ApplicationBuilder().token(token).build()
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("report", report))
        app.add_handler(CommandHandler("fullreport", fullreport))
        app.add_handler(CommandHandler("summary", summary))
        app.add_handler(CommandHandler("analyze", analyze))
        app.add_handler(CommandHandler("ideas", ideas))
        app.add_handler(CommandHandler("watch", watch))
        app.add_handler(CommandHandler("unwatch", unwatch))
        app.add_handler(CommandHandler("watchlist", watchlist))
        app.add_handler(CommandHandler("strategy", strategy_cmd))
        app.add_handler(CommandHandler("reportmode", reportmode_cmd))
        app.add_handler(CommandHandler("sections", sections_cmd))
        app.add_handler(CommandHandler("pushmode", pushmode_cmd))
        app.add_handler(CommandHandler("schedule", schedule_cmd))
        app.add_handler(CommandHandler("timezone", timezone_cmd))
        app.add_handler(CommandHandler("pushtime", pushtime_cmd))
        app.add_handler(CommandHandler("language", language_cmd))
        app.add_handler(CommandHandler("risk", risk_cmd))
        app.add_handler(CommandHandler("maxpos", maxpos_cmd))
        app.add_handler(CommandHandler("horizon", horizon_cmd))

        logger.info("Telegram bot starting (polling)...")
        async with app:
            await app.start()
            await app.updater.start_polling()
            await asyncio.Event().wait()  # run until the thread is killed

    loop.run_until_complete(_run())


def start_bot_thread(token: str) -> threading.Thread:
    """Starts the Telegram bot in a daemon thread."""
    thread = threading.Thread(target=run_bot, args=(token,), daemon=True)
    thread.start()
    return thread
