"""
Tests for /risk, /maxpos, /horizon Telegram profile commands.

Each handler is tested in isolation: Telegram Update and context are stubbed
with SimpleNamespace so no real bot token or network is needed.
get_user_profile and save_user_profile are monkeypatched to avoid SQLite I/O.
"""
import asyncio
import sys
from types import SimpleNamespace

# Stub heavy dependencies before any project imports
sys.modules.setdefault("yfinance", SimpleNamespace())
sys.modules.setdefault("litellm", SimpleNamespace(completion=lambda *a, **k: None))
sys.modules.setdefault("dotenv", SimpleNamespace(load_dotenv=lambda: None))
sys.modules.setdefault("telegram", SimpleNamespace(Update=object))
sys.modules.setdefault(
    "telegram.ext",
    SimpleNamespace(
        ApplicationBuilder=object,
        CommandHandler=object,
        ContextTypes=SimpleNamespace(DEFAULT_TYPE=None),
    ),
)

import pytest

import channels.telegram.bot as bot_module
from domain.schemas.portfolio import UserProfile


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_update(chat_id: str = "12345") -> SimpleNamespace:
    """Minimal Telegram Update stub."""
    replies: list[str] = []

    async def reply_text(text: str, **kwargs):
        replies.append(text)

    message = SimpleNamespace(reply_text=reply_text)
    chat = SimpleNamespace(id=int(chat_id))
    return SimpleNamespace(
        effective_chat=chat,
        effective_user=SimpleNamespace(id=1, username="test"),
        message=message,
        _replies=replies,
    )


def _make_context(args: list[str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(args=args or [])


def run(coro):
    """Run an async coroutine synchronously in tests."""
    return asyncio.new_event_loop().run_until_complete(coro)


def _default_profile(profile_id: str = "12345") -> UserProfile:
    return UserProfile(profile_id=profile_id)


# ── /risk ──────────────────────────────────────────────────────────────────────

def test_risk_no_args_shows_current(monkeypatch):
    update = _make_update()
    monkeypatch.setattr(bot_module, "get_user_profile", lambda pid: _default_profile(pid))
    monkeypatch.setattr(bot_module, "save_user_profile", lambda p: p)

    run(bot_module.risk_cmd(update, _make_context()))

    assert len(update._replies) == 1
    assert "moderate" in update._replies[0]
    assert "Usage" in update._replies[0]


def test_risk_valid_value_saves(monkeypatch):
    saved: list[UserProfile] = []
    monkeypatch.setattr(bot_module, "get_user_profile", lambda pid: _default_profile(pid))
    monkeypatch.setattr(bot_module, "save_user_profile", lambda p: saved.append(p) or p)

    update = _make_update()
    run(bot_module.risk_cmd(update, _make_context(["aggressive"])))

    assert len(saved) == 1
    assert saved[0].risk_profile == "aggressive"
    assert "aggressive" in update._replies[0]


def test_risk_invalid_value_no_save(monkeypatch):
    saved: list = []
    monkeypatch.setattr(bot_module, "get_user_profile", lambda pid: _default_profile(pid))
    monkeypatch.setattr(bot_module, "save_user_profile", lambda p: saved.append(p))

    update = _make_update()
    run(bot_module.risk_cmd(update, _make_context(["yolo"])))

    assert saved == []
    assert "Invalid" in update._replies[0]


# ── /maxpos ─────────────────────────────────────────────────────────────────────

def test_maxpos_no_args_shows_current(monkeypatch):
    update = _make_update()
    monkeypatch.setattr(bot_module, "get_user_profile", lambda pid: _default_profile(pid))
    monkeypatch.setattr(bot_module, "save_user_profile", lambda p: p)

    run(bot_module.maxpos_cmd(update, _make_context()))

    assert "8.0%" in update._replies[0]
    assert "Usage" in update._replies[0]


def test_maxpos_integer_percent(monkeypatch):
    saved: list[UserProfile] = []
    monkeypatch.setattr(bot_module, "get_user_profile", lambda pid: _default_profile(pid))
    monkeypatch.setattr(bot_module, "save_user_profile", lambda p: saved.append(p) or p)

    update = _make_update()
    run(bot_module.maxpos_cmd(update, _make_context(["5"])))

    assert saved[0].max_single_position == pytest.approx(0.05)
    assert "5.0%" in update._replies[0]


def test_maxpos_decimal_input(monkeypatch):
    saved: list[UserProfile] = []
    monkeypatch.setattr(bot_module, "get_user_profile", lambda pid: _default_profile(pid))
    monkeypatch.setattr(bot_module, "save_user_profile", lambda p: saved.append(p) or p)

    update = _make_update()
    run(bot_module.maxpos_cmd(update, _make_context(["0.08"])))

    assert saved[0].max_single_position == pytest.approx(0.08)


def test_maxpos_percent_suffix(monkeypatch):
    saved: list[UserProfile] = []
    monkeypatch.setattr(bot_module, "get_user_profile", lambda pid: _default_profile(pid))
    monkeypatch.setattr(bot_module, "save_user_profile", lambda p: saved.append(p) or p)

    update = _make_update()
    run(bot_module.maxpos_cmd(update, _make_context(["5%"])))

    assert saved[0].max_single_position == pytest.approx(0.05)


def test_maxpos_out_of_range_no_save(monkeypatch):
    saved: list = []
    monkeypatch.setattr(bot_module, "get_user_profile", lambda pid: _default_profile(pid))
    monkeypatch.setattr(bot_module, "save_user_profile", lambda p: saved.append(p))

    update = _make_update()
    run(bot_module.maxpos_cmd(update, _make_context(["25"])))

    assert saved == []
    assert "between 1% and 20%" in update._replies[0]


def test_maxpos_non_numeric_no_save(monkeypatch):
    saved: list = []
    monkeypatch.setattr(bot_module, "get_user_profile", lambda pid: _default_profile(pid))
    monkeypatch.setattr(bot_module, "save_user_profile", lambda p: saved.append(p))

    update = _make_update()
    run(bot_module.maxpos_cmd(update, _make_context(["abc"])))

    assert saved == []
    assert "Invalid number" in update._replies[0]


# ── /horizon ──────────────────────────────────────────────────────────────────

def test_horizon_no_args_shows_current(monkeypatch):
    update = _make_update()
    monkeypatch.setattr(bot_module, "get_user_profile", lambda pid: _default_profile(pid))
    monkeypatch.setattr(bot_module, "save_user_profile", lambda p: p)

    run(bot_module.horizon_cmd(update, _make_context()))

    assert "swing" in update._replies[0]
    assert "Usage" in update._replies[0]


def test_horizon_valid_value_saves(monkeypatch):
    saved: list[UserProfile] = []
    monkeypatch.setattr(bot_module, "get_user_profile", lambda pid: _default_profile(pid))
    monkeypatch.setattr(bot_module, "save_user_profile", lambda p: saved.append(p) or p)

    update = _make_update()
    run(bot_module.horizon_cmd(update, _make_context(["longterm"])))

    assert saved[0].preferred_horizon == "longterm"
    assert "longterm" in update._replies[0]


def test_horizon_invalid_value_no_save(monkeypatch):
    saved: list = []
    monkeypatch.setattr(bot_module, "get_user_profile", lambda pid: _default_profile(pid))
    monkeypatch.setattr(bot_module, "save_user_profile", lambda p: saved.append(p))

    update = _make_update()
    run(bot_module.horizon_cmd(update, _make_context(["intraday"])))

    assert saved == []
    assert "Invalid" in update._replies[0]


# ── _parse_pct_arg helper ─────────────────────────────────────────────────────

def test_parse_pct_arg_integer():
    assert bot_module._parse_pct_arg("5") == pytest.approx(0.05)


def test_parse_pct_arg_percent_suffix():
    assert bot_module._parse_pct_arg("5%") == pytest.approx(0.05)


def test_parse_pct_arg_decimal():
    assert bot_module._parse_pct_arg("0.05") == pytest.approx(0.05)
