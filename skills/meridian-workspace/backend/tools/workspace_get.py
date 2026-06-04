"""workspace_get — read a single fact by key."""

import sqlite3
from datetime import datetime, timedelta

DB_PATH = "/root/evonic/shared/db/evonic.db"


def _connect():
    con = sqlite3.connect(DB_PATH, timeout=10.0)
    con.row_factory = sqlite3.Row
    return con


def _row_to_dict(row):
    return {
        "key": row["key"],
        "value": row["value"],
        "category": row["category"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "expires_at": row["expires_at"],
    }


def _purge_expired(con):
    con.execute(
        "DELETE FROM meridian_shared_memory "
        "WHERE expires_at IS NOT NULL AND expires_at < datetime('now')"
    )



def execute(agent: dict, args: dict) -> dict:
    key = args.get("key")
    if not key or not isinstance(key, str):
        return {"status": "error", "error": "key (string) is required"}

    con = _connect()
    try:
        _purge_expired(con)
        row = con.execute(
            "SELECT key, value, category, created_at, updated_at, expires_at "
            "FROM meridian_shared_memory WHERE key = ?",
            (key,),
        ).fetchone()
    finally:
        con.close()

    if not row:
        return {"status": "success", "key": key, "found": False, "value": None}
    return {"status": "success", "key": key, "found": True, **_row_to_dict(row)}
