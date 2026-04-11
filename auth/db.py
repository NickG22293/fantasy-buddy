"""SQLite persistence for multi-user token storage."""

import os
import secrets
import sqlite3
import time
from contextlib import contextmanager

DB_PATH = os.environ.get("DB_PATH", "hockeybot.db")


@contextmanager
def _conn():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init_db() -> None:
    with _conn() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                yahoo_guid    TEXT    UNIQUE NOT NULL,
                api_key       TEXT    UNIQUE NOT NULL,
                league_id     TEXT,
                access_token  TEXT    NOT NULL,
                refresh_token TEXT    NOT NULL,
                token_time    REAL    NOT NULL,
                created_at    REAL    NOT NULL
            )
        """)


def upsert_user(yahoo_guid: str, access_token: str, refresh_token: str, token_time: float) -> dict:
    """Insert or update a user's tokens. Returns the full user row."""
    with _conn() as con:
        existing = con.execute(
            "SELECT * FROM users WHERE yahoo_guid = ?", (yahoo_guid,)
        ).fetchone()

        if existing:
            con.execute(
                """UPDATE users
                   SET access_token = ?, refresh_token = ?, token_time = ?
                   WHERE yahoo_guid = ?""",
                (access_token, refresh_token, token_time, yahoo_guid),
            )
            row = con.execute(
                "SELECT * FROM users WHERE yahoo_guid = ?", (yahoo_guid,)
            ).fetchone()
        else:
            api_key = secrets.token_urlsafe(32)
            con.execute(
                """INSERT INTO users
                   (yahoo_guid, api_key, access_token, refresh_token, token_time, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (yahoo_guid, api_key, access_token, refresh_token, token_time, time.time()),
            )
            row = con.execute(
                "SELECT * FROM users WHERE yahoo_guid = ?", (yahoo_guid,)
            ).fetchone()

    return dict(row)


def get_user_by_id(user_id: int) -> dict | None:
    with _conn() as con:
        row = con.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def get_user_by_api_key(api_key: str) -> dict | None:
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM users WHERE api_key = ?", (api_key,)
        ).fetchone()
    return dict(row) if row else None


def update_user_tokens(user_id: int, access_token: str, refresh_token: str, token_time: float) -> None:
    with _conn() as con:
        con.execute(
            """UPDATE users SET access_token = ?, refresh_token = ?, token_time = ?
               WHERE id = ?""",
            (access_token, refresh_token, token_time, user_id),
        )


def update_user_league(user_id: int, league_id: str) -> None:
    with _conn() as con:
        con.execute(
            "UPDATE users SET league_id = ? WHERE id = ?",
            (league_id, user_id),
        )
