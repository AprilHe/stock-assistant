"""SQLite persistence for canonical user profiles and portfolio snapshots."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from domain.schemas.portfolio import PortfolioSnapshot, UserProfile

_DATA_DIR = Path(__file__).resolve().parents[1] / "data"
_DB_FILE = _DATA_DIR / "portfolio.db"


@contextmanager
def _db():
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_FILE))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_profiles (
            profile_id TEXT PRIMARY KEY,
            data       TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS portfolio_snapshots (
            profile_id TEXT PRIMARY KEY,
            data       TEXT NOT NULL
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


def _write(table: str, profile_id: str, payload: dict) -> None:
    with _db() as conn:
        conn.execute(
            f"INSERT OR REPLACE INTO {table} (profile_id, data) VALUES (?, ?)",
            (profile_id, json.dumps(payload)),
        )


def _read(table: str, profile_id: str) -> dict | None:
    with _db() as conn:
        row = conn.execute(
            f"SELECT data FROM {table} WHERE profile_id = ?",
            (profile_id,),
        ).fetchone()
    if not row:
        return None
    return json.loads(row[0])


def get_user_profile(profile_id: str = "default") -> UserProfile:
    payload = _read("user_profiles", profile_id)
    if payload is None:
        profile = UserProfile(profile_id=profile_id)
        save_user_profile(profile)
        return profile
    return UserProfile(**payload)


def save_user_profile(profile: UserProfile) -> UserProfile:
    _write("user_profiles", profile.profile_id, profile.model_dump())
    return profile


def get_portfolio_snapshot(profile_id: str = "default") -> PortfolioSnapshot:
    payload = _read("portfolio_snapshots", profile_id)
    if payload is None:
        snapshot = PortfolioSnapshot()
        save_portfolio_snapshot(profile_id, snapshot)
        return snapshot
    return PortfolioSnapshot(**payload)


def save_portfolio_snapshot(profile_id: str, snapshot: PortfolioSnapshot) -> PortfolioSnapshot:
    _write("portfolio_snapshots", profile_id, snapshot.model_dump())
    return snapshot
