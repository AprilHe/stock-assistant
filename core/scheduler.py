"""
core/scheduler.py
APScheduler jobs: send personalised watchlist reports to each user
on their chosen schedule (daily / twice-daily / weekly / off).

Each user's jobs run in their local timezone at their preferred push time.
Call reschedule_user(chat_id) after a user changes any schedule setting
so APScheduler picks up the change immediately without a restart.
"""

import os
import asyncio
import logging
import pytz
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler

load_dotenv()

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Module-level scheduler instance so reschedule_user() can reach it
_scheduler: BackgroundScheduler | None = None


def _env_truthy(raw: str | None) -> bool:
    return str(raw or "").strip().lower() in {"1", "true", "yes", "on"}


DISABLE_BOT_SCHEDULED_PUSH = _env_truthy(os.getenv("DISABLE_BOT_SCHEDULED_PUSH"))


# ── Report sender ──────────────────────────────────────────────────────────────

def _send_report_for(chat_id: str):
    """Generate and send a watchlist report to a single user."""
    if DISABLE_BOT_SCHEDULED_PUSH:
        logger.info(
            "Scheduler: global guard enabled (DISABLE_BOT_SCHEDULED_PUSH=true), skip send for %s",
            chat_id,
        )
        return

    from core.preferences import get_prefs
    from app.services.report_service import build_push_messages, generate_and_save_report

    prefs = get_prefs(chat_id)
    watchlist = prefs.get("watchlist", [])
    strategies = prefs.get("strategies", ["breakout"])
    report_sections = prefs.get("report_sections", ["watchlist"])
    schedule = prefs.get("schedule", "weekly")
    language = prefs.get("language", "en")
    push_mode = prefs.get("push_mode", "simple")

    if not watchlist:
        logger.info("Scheduler: skipping %s — empty watchlist", chat_id)
        return

    logger.info("Scheduler: generating report for %s (%s)", chat_id, watchlist)

    try:
        generate_and_save_report(chat_id, prefs)
        messages = build_push_messages(
            profile_id=chat_id,
            watchlist=watchlist,
            strategies=strategies,
            report_sections=report_sections,
            detail_level=push_mode,
            schedule=schedule,
            language=language,
        )
    except Exception as e:
        logger.error("Scheduler: failed to generate report for %s: %s", chat_id, e)
        messages = [f"Report generation failed: {e}"]

    if not TELEGRAM_BOT_TOKEN:
        logger.warning("Scheduler: TELEGRAM_BOT_TOKEN not set — skipping send.")
        return

    try:
        from telegram import Bot

        async def _send():
            bot = Bot(token=TELEGRAM_BOT_TOKEN)
            for message in messages:
                await bot.send_message(chat_id=chat_id, text=message)

        asyncio.run(_send())
        logger.info("Scheduler: report sent to %s", chat_id)
    except Exception as e:
        logger.error("Scheduler: failed to send message to %s: %s", chat_id, e)


# ── Job management ─────────────────────────────────────────────────────────────

def _job_ids(chat_id: str) -> list[str]:
    return [f"report_{chat_id}_morning", f"report_{chat_id}_afternoon"]


def _remove_user_jobs(chat_id: str):
    for job_id in _job_ids(chat_id):
        if _scheduler and _scheduler.get_job(job_id):
            _scheduler.remove_job(job_id)


def _add_user_jobs(chat_id: str, schedule: str):
    if not _scheduler:
        return
    if DISABLE_BOT_SCHEDULED_PUSH:
        _remove_user_jobs(chat_id)
        return

    _remove_user_jobs(chat_id)

    from core.preferences import get_prefs
    prefs = get_prefs(chat_id)
    tz_name = prefs.get("timezone", "UTC")
    push_time = prefs.get("push_time", "08:00")

    try:
        user_tz = pytz.timezone(tz_name)
    except pytz.UnknownTimeZoneError:
        user_tz = pytz.utc

    h, m = map(int, push_time.split(":"))
    afternoon_h = (h + 8) % 24

    morning_id = f"report_{chat_id}_morning"
    afternoon_id = f"report_{chat_id}_afternoon"

    if schedule == "daily":
        _scheduler.add_job(
            _send_report_for, "cron", args=[chat_id],
            hour=h, minute=m, timezone=user_tz,
            id=morning_id, replace_existing=True,
        )

    elif schedule == "twice":
        _scheduler.add_job(
            _send_report_for, "cron", args=[chat_id],
            hour=h, minute=m, timezone=user_tz,
            id=morning_id, replace_existing=True,
        )
        _scheduler.add_job(
            _send_report_for, "cron", args=[chat_id],
            hour=afternoon_h, minute=m, timezone=user_tz,
            id=afternoon_id, replace_existing=True,
        )

    elif schedule == "weekly":
        _scheduler.add_job(
            _send_report_for, "cron", args=[chat_id],
            day_of_week="mon", hour=h, minute=m, timezone=user_tz,
            id=morning_id, replace_existing=True,
        )

    # "off" → no jobs added


def reschedule_user(chat_id: str):
    """
    Rebuilds a user's APScheduler jobs immediately after they change
    their schedule, timezone, or push time.
    """
    from core.preferences import get_prefs
    prefs = get_prefs(chat_id)
    _add_user_jobs(chat_id, prefs["schedule"])
    logger.info("Scheduler: rescheduled %s → %s @ %s (%s)",
                chat_id, prefs["schedule"], prefs["push_time"], prefs["timezone"])


# ── Scheduler factory ──────────────────────────────────────────────────────────

def create_scheduler() -> BackgroundScheduler:
    """
    Creates, configures, and returns a BackgroundScheduler.
    Loads all existing user preferences and registers their jobs.
    Call scheduler.start() to activate.
    """
    global _scheduler
    _scheduler = BackgroundScheduler(timezone=pytz.utc)

    if DISABLE_BOT_SCHEDULED_PUSH:
        logger.warning(
            "Scheduler: DISABLE_BOT_SCHEDULED_PUSH=true, bot-scheduled pushes are globally disabled."
        )
        return _scheduler

    from core.preferences import all_users
    for chat_id, prefs in all_users().items():
        _add_user_jobs(chat_id, prefs.get("schedule", "weekly"))
        logger.info("Scheduler: registered jobs for %s (%s @ %s %s)",
                    chat_id, prefs.get("schedule"), prefs.get("push_time"), prefs.get("timezone"))

    return _scheduler
