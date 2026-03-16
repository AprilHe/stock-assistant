"""
core/preferences.py
Per-user preferences stored in a SQLite database.

Schema per chat_id:
{
    "watchlist": ["AAPL", "TSLA", "^GSPC"],
    "strategies": ["breakout"],
    "report_sections": ["watchlist"],
    "report_mode": "summary" | "ideas" | "summary+ideas",
    "schedule": "daily" | "twice" | "weekly" | "off",
    "timezone": "UTC",          # IANA timezone name
    "push_time": "08:00",       # 24-hour local time for scheduled pushes
    "language": "en",           # "en" or "zh"
    "push_mode": "simple"       # "simple" | "full" (legacy: brief | detailed)
}

Storage: SQLite with WAL mode for concurrent-safe writes.
Migration: on first use, any existing preferences.json is imported automatically.
"""

import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from core.strategy_registry import list_strategies_by_capability

_DATA_DIR = Path(__file__).parent.parent / "data"
_DB_FILE = _DATA_DIR / "preferences.db"
_LEGACY_JSON = _DATA_DIR / "preferences.json"

DEFAULT_WATCHLIST = ["^GSPC", "^IXIC", "BTC-USD"]
try:
    STRATEGY_OPTIONS = tuple(item["id"] for item in list_strategies_by_capability("screen"))
except Exception:
    STRATEGY_OPTIONS = ("breakout", "pullback", "commodity_macro")
REPORT_SECTION_OPTIONS = ("watchlist", "market", "commodity")
REPORT_MODE_OPTIONS = ("summary", "ideas", "summary+ideas")
SCHEDULE_OPTIONS = ("daily", "twice", "weekly", "off")
LANGUAGE_OPTIONS = ("en", "zh")
PUSH_MODE_OPTIONS = ("simple", "full")

_TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")

# ---------------------------------------------------------------------------
# Database bootstrap
# ---------------------------------------------------------------------------

@contextmanager
def _db():
    """Context manager that yields a connected, WAL-mode SQLite connection.

    A new connection is opened per operation so every call is naturally
    isolated. WAL mode allows concurrent readers alongside a single writer
    without the whole-file lock that a JSON write would require.
    """
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_FILE))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS preferences (
            chat_id TEXT PRIMARY KEY,
            data    TEXT NOT NULL
        )
        """
    )
    conn.commit()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _migrate_from_json() -> None:
    """One-time import of legacy preferences.json into SQLite.

    Called once at module load. Renames the source file to
    preferences.json.migrated so it is never imported twice.
    """
    if not _LEGACY_JSON.exists():
        return
    try:
        with open(_LEGACY_JSON, encoding="utf-8") as f:
            legacy: dict = json.load(f)
        if not legacy:
            _LEGACY_JSON.rename(_LEGACY_JSON.with_suffix(".json.migrated"))
            return
        with _db() as conn:
            for chat_id, prefs in legacy.items():
                conn.execute(
                    "INSERT OR IGNORE INTO preferences (chat_id, data) VALUES (?, ?)",
                    (str(chat_id), json.dumps(prefs)),
                )
        _LEGACY_JSON.rename(_LEGACY_JSON.with_suffix(".json.migrated"))
    except Exception:
        # Migration failure must never break normal operation.
        pass


# Run migration at import time (no-op if already done or no legacy file).
_migrate_from_json()

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _default_prefs() -> dict:
    return {
        "watchlist": list(DEFAULT_WATCHLIST),
        "strategies": ["breakout"],
        "report_sections": ["watchlist"],
        "report_mode": "summary",
        "schedule": "weekly",
        "timezone": "UTC",
        "push_time": "08:00",
        "language": "en",
        "push_mode": "simple",
    }


def _normalize_prefs(prefs: dict) -> dict:
    """Fill missing keys with defaults so old records stay compatible."""
    defaults = _default_prefs()
    for key, val in defaults.items():
        prefs.setdefault(key, val)
    prefs["push_mode"] = _normalize_push_mode(prefs.get("push_mode", "simple"))
    return prefs


def _normalize_push_mode(push_mode: str | None) -> str:
    normalized = str(push_mode or "").lower().strip()
    if normalized in {"simple", "brief"}:
        return "simple"
    if normalized in {"full", "detailed"}:
        return "full"
    return "simple"


def _read(chat_id: str) -> dict:
    """Read a single user's raw prefs dict from the DB (or empty dict)."""
    with _db() as conn:
        row = conn.execute(
            "SELECT data FROM preferences WHERE chat_id = ?", (chat_id,)
        ).fetchone()
    return json.loads(row[0]) if row else {}


def _write(chat_id: str, prefs: dict) -> None:
    """Persist a single user's prefs dict atomically."""
    with _db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO preferences (chat_id, data) VALUES (?, ?)",
            (chat_id, json.dumps(prefs)),
        )

# ---------------------------------------------------------------------------
# Public API  (identical surface to the old JSON-based module)
# ---------------------------------------------------------------------------

def get_prefs(chat_id: str) -> dict:
    key = str(chat_id)
    raw = _read(key)
    if not raw:
        prefs = _default_prefs()
        _write(key, prefs)
        return prefs
    return _normalize_prefs(raw)


def add_ticker(chat_id: str, ticker: str) -> bool:
    """Returns True if added, False if already present."""
    key = str(chat_id)
    raw = _read(key)
    prefs = _normalize_prefs(raw if raw else _default_prefs())
    if ticker in prefs["watchlist"]:
        return False
    prefs["watchlist"].append(ticker)
    _write(key, prefs)
    return True


def remove_ticker(chat_id: str, ticker: str) -> bool:
    """Returns True if removed, False if not found."""
    key = str(chat_id)
    raw = _read(key)
    prefs = _normalize_prefs(raw if raw else _default_prefs())
    if ticker not in prefs["watchlist"]:
        return False
    prefs["watchlist"].remove(ticker)
    _write(key, prefs)
    return True


def set_schedule(chat_id: str, schedule: str) -> bool:
    if schedule not in SCHEDULE_OPTIONS:
        return False
    key = str(chat_id)
    raw = _read(key)
    prefs = _normalize_prefs(raw if raw else _default_prefs())
    prefs["schedule"] = schedule
    _write(key, prefs)
    return True


def set_timezone(chat_id: str, tz_name: str) -> bool:
    import pytz
    if tz_name not in pytz.all_timezones_set:
        return False
    key = str(chat_id)
    raw = _read(key)
    prefs = _normalize_prefs(raw if raw else _default_prefs())
    prefs["timezone"] = tz_name
    _write(key, prefs)
    return True


def set_push_time(chat_id: str, time_str: str) -> bool:
    if not _TIME_RE.match(time_str):
        return False
    h, m = int(time_str.split(":")[0]), int(time_str.split(":")[1])
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return False
    key = str(chat_id)
    raw = _read(key)
    prefs = _normalize_prefs(raw if raw else _default_prefs())
    prefs["push_time"] = f"{h:02d}:{m:02d}"
    _write(key, prefs)
    return True


def set_language(chat_id: str, lang: str) -> bool:
    if lang not in LANGUAGE_OPTIONS:
        return False
    key = str(chat_id)
    raw = _read(key)
    prefs = _normalize_prefs(raw if raw else _default_prefs())
    prefs["language"] = lang
    _write(key, prefs)
    return True


def set_push_mode(chat_id: str, push_mode: str) -> bool:
    normalized = _normalize_push_mode(push_mode)
    raw_input = (push_mode or "").lower().strip()
    if raw_input not in {"simple", "full", "brief", "detailed"}:
        return False
    key = str(chat_id)
    raw = _read(key)
    prefs = _normalize_prefs(raw if raw else _default_prefs())
    prefs["push_mode"] = normalized
    _write(key, prefs)
    return True


def set_strategies(chat_id: str, strategies: list[str]) -> bool:
    normalized = [s.lower().strip() for s in strategies if s.strip()]
    if not normalized:
        return False
    if any(s not in STRATEGY_OPTIONS for s in normalized):
        return False
    deduped = list(dict.fromkeys(normalized))
    key = str(chat_id)
    raw = _read(key)
    prefs = _normalize_prefs(raw if raw else _default_prefs())
    prefs["strategies"] = deduped
    _write(key, prefs)
    return True


def set_report_mode(chat_id: str, report_mode: str) -> bool:
    normalized = report_mode.lower().strip()
    if normalized not in REPORT_MODE_OPTIONS:
        return False
    key = str(chat_id)
    raw = _read(key)
    prefs = _normalize_prefs(raw if raw else _default_prefs())
    prefs["report_mode"] = normalized
    _write(key, prefs)
    return True


def set_report_sections(chat_id: str, report_sections: list[str]) -> bool:
    normalized = [section.lower().strip() for section in report_sections if section.strip()]
    if not normalized:
        return False
    if "watchlist" not in normalized:
        normalized.insert(0, "watchlist")
    if any(section not in REPORT_SECTION_OPTIONS for section in normalized):
        return False
    deduped = list(dict.fromkeys(normalized))
    key = str(chat_id)
    raw = _read(key)
    prefs = _normalize_prefs(raw if raw else _default_prefs())
    prefs["report_sections"] = deduped
    _write(key, prefs)
    return True


def update_prefs(
    chat_id: str,
    watchlist: list[str],
    strategies: list[str],
    report_sections: list[str],
    report_mode: str,
    schedule: str,
    language: str,
    timezone: str,
    push_time: str,
    push_mode: str = "simple",
) -> dict:
    """Validates and persists a full preference payload."""
    import pytz

    normalized_watchlist = [ticker.upper().strip() for ticker in watchlist if ticker.strip()]
    normalized_watchlist = list(dict.fromkeys(normalized_watchlist))
    normalized_strategies = [strategy.lower().strip() for strategy in strategies if strategy.strip()]
    normalized_strategies = list(dict.fromkeys(normalized_strategies))
    normalized_report_sections = [section.lower().strip() for section in report_sections if section.strip()]
    normalized_report_sections = list(dict.fromkeys(normalized_report_sections))
    normalized_report_mode = report_mode.lower().strip()
    normalized_schedule = schedule.lower().strip()
    normalized_language = language.lower().strip()
    normalized_timezone = timezone.strip()
    normalized_push_time = push_time.strip()
    normalized_push_mode = _normalize_push_mode(push_mode)

    if not normalized_watchlist:
        raise ValueError("watchlist must contain at least one ticker.")
    if any(not re.fullmatch(r"^[A-Z0-9.\-=\^]+$", ticker) for ticker in normalized_watchlist):
        raise ValueError("watchlist contains an invalid ticker symbol.")
    if not normalized_strategies:
        raise ValueError("strategies must contain at least one strategy.")
    if any(strategy not in STRATEGY_OPTIONS for strategy in normalized_strategies):
        raise ValueError(f"strategies must be chosen from: {', '.join(STRATEGY_OPTIONS)}")
    if not normalized_report_sections:
        raise ValueError("report_sections must contain at least one section.")
    if "watchlist" not in normalized_report_sections:
        normalized_report_sections.insert(0, "watchlist")
    if any(section not in REPORT_SECTION_OPTIONS for section in normalized_report_sections):
        raise ValueError(f"report_sections must be chosen from: {', '.join(REPORT_SECTION_OPTIONS)}")
    if normalized_report_mode not in REPORT_MODE_OPTIONS:
        raise ValueError(f"report_mode must be chosen from: {', '.join(REPORT_MODE_OPTIONS)}")
    if normalized_schedule not in SCHEDULE_OPTIONS:
        raise ValueError(f"schedule must be chosen from: {', '.join(SCHEDULE_OPTIONS)}")
    if normalized_language not in LANGUAGE_OPTIONS:
        raise ValueError(f"language must be chosen from: {', '.join(LANGUAGE_OPTIONS)}")
    if str(push_mode or "").lower().strip() not in {"simple", "full", "brief", "detailed"}:
        raise ValueError("push_mode must be chosen from: simple, full")
    if normalized_timezone not in pytz.all_timezones_set:
        raise ValueError("timezone must be a valid IANA timezone.")
    if not _TIME_RE.match(normalized_push_time):
        raise ValueError("push_time must be in HH:MM format.")
    hour, minute = map(int, normalized_push_time.split(":"))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("push_time must be a valid 24-hour time.")

    key = str(chat_id)
    raw = _read(key)
    prefs = _normalize_prefs(raw if raw else _default_prefs())
    prefs["watchlist"] = normalized_watchlist
    prefs["strategies"] = normalized_strategies
    prefs["report_sections"] = normalized_report_sections
    prefs["report_mode"] = normalized_report_mode
    prefs["schedule"] = normalized_schedule
    prefs["language"] = normalized_language
    prefs["push_mode"] = normalized_push_mode
    prefs["timezone"] = normalized_timezone
    prefs["push_time"] = f"{hour:02d}:{minute:02d}"
    _write(key, prefs)
    return prefs


def all_users() -> dict:
    """Returns the full preferences dict keyed by chat_id string."""
    with _db() as conn:
        rows = conn.execute("SELECT chat_id, data FROM preferences").fetchall()
    return {row[0]: json.loads(row[1]) for row in rows}
