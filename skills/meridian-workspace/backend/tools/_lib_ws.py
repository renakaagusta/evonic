"""Shared SQLite helpers for the meridian-workspace skill."""

import os
import sqlite3
from typing import Optional

DB_PATH = "/root/evonic/shared/db/evonic.db"


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=10.0)
    con.row_factory = sqlite3.Row
    return con


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "key": row["key"],
        "value": row["value"],
        "category": row["category"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "expires_at": row["expires_at"],
    }


def _purge_expired(con: sqlite3.Connection) -> None:
    """Best-effort: delete rows whose expires_at is in the past."""
    con.execute(
        "DELETE FROM meridian_shared_memory "
        "WHERE expires_at IS NOT NULL AND expires_at < datetime('now')"
    )
