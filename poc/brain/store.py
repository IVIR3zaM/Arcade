"""Persistent SQLite store — the arcade's memory.

This is the deterministic system of record the LLM manager reads and writes
through tools: who has a profile, the free-form context the assistant has learned
about each person ("plays evenings after 5pm"), privacy schedules an admin set,
and a log of what got played. It lives in a mounted volume so it survives
restarts — that's what makes "next time it just knows you" real.

Matches Phase 8's choice of SQLite. Kept to plain functions over one connection.
"""

import os
import sqlite3
from datetime import datetime, timezone

DB_PATH = os.environ.get("ARCADE_DB", "/data/arcade.db")

# Known family seeded on first init. Guests/new people are created at runtime by
# the assistant via create_profile.
_SEED = [
    {"name": "Leo", "language": "en", "is_admin": 0},
    {"name": "Mia", "language": "de", "is_admin": 0},
    {"name": "Reza", "language": "en", "is_admin": 1},  # the admin (privacy controls)
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init(conn: sqlite3.Connection) -> None:
    """Create tables and seed the known family the first time."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS profiles (
            id         INTEGER PRIMARY KEY,
            name       TEXT NOT NULL UNIQUE,
            language   TEXT NOT NULL DEFAULT 'en',
            is_guest   INTEGER NOT NULL DEFAULT 0,
            is_admin   INTEGER NOT NULL DEFAULT 0,
            notes      TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS privacy_schedules (
            id         INTEGER PRIMARY KEY,
            start_hm   TEXT NOT NULL,   -- "20:00"
            end_hm     TEXT NOT NULL,   -- "09:00" (may wrap past midnight)
            reason     TEXT NOT NULL DEFAULT '',
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS plays (
            id         INTEGER PRIMARY KEY,
            player     TEXT NOT NULL,
            game       TEXT NOT NULL,
            played_at  TEXT NOT NULL
        );
        """
    )
    for p in _SEED:
        conn.execute(
            "INSERT OR IGNORE INTO profiles (name, language, is_admin, created_at) "
            "VALUES (?, ?, ?, ?)",
            (p["name"], p["language"], p["is_admin"], _now()),
        )
    conn.commit()


def get_profile(conn: sqlite3.Connection, name: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM profiles WHERE lower(name) = lower(?)", (name,)
    ).fetchone()
    return dict(row) if row else None


def list_profile_names(conn: sqlite3.Connection) -> list[str]:
    return [r["name"] for r in conn.execute("SELECT name FROM profiles ORDER BY name")]


def create_profile(
    conn: sqlite3.Connection, name: str, language: str = "en", is_guest: int = 0
) -> dict:
    conn.execute(
        "INSERT OR IGNORE INTO profiles (name, language, is_guest, created_at) "
        "VALUES (?, ?, ?, ?)",
        (name, language, is_guest, _now()),
    )
    conn.commit()
    return get_profile(conn, name)


def delete_profile(conn: sqlite3.Connection, name: str) -> bool:
    cur = conn.execute("DELETE FROM profiles WHERE lower(name) = lower(?)", (name,))
    conn.commit()
    return cur.rowcount > 0


def set_language(conn: sqlite3.Connection, name: str, language: str) -> bool:
    """Persist a person's preferred language; False if they have no profile."""
    cur = conn.execute(
        "UPDATE profiles SET language = ? WHERE lower(name) = lower(?)",
        (language, name),
    )
    conn.commit()
    return cur.rowcount > 0


def append_note(conn: sqlite3.Connection, name: str, note: str) -> str | None:
    """Append a learned context note to a person's memory; returns the full memory."""
    prof = get_profile(conn, name)
    if prof is None:
        return None
    combined = (prof["notes"] + "\n" if prof["notes"] else "") + note
    conn.execute("UPDATE profiles SET notes = ? WHERE id = ?", (combined, prof["id"]))
    conn.commit()
    return combined


def add_schedule(
    conn: sqlite3.Connection, start_hm: str, end_hm: str, reason: str, created_by: str
) -> dict:
    cur = conn.execute(
        "INSERT INTO privacy_schedules (start_hm, end_hm, reason, created_by, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (start_hm, end_hm, reason, created_by, _now()),
    )
    conn.commit()
    return {
        "id": cur.lastrowid,
        "start_hm": start_hm,
        "end_hm": end_hm,
        "reason": reason,
        "created_by": created_by,
    }


def list_schedules(conn: sqlite3.Connection) -> list[dict]:
    return [
        dict(r) for r in conn.execute("SELECT * FROM privacy_schedules ORDER BY id")
    ]


def log_play(conn: sqlite3.Connection, player: str, game: str) -> None:
    conn.execute(
        "INSERT INTO plays (player, game, played_at) VALUES (?, ?, ?)",
        (player, game, _now()),
    )
    conn.commit()
