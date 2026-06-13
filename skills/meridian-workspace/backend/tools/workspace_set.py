"""workspace_set — upsert a fact into the shared Meridian workspace."""

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
        "WHERE expires_at IS NOT NULL AND expires_at < datetime('now') AND key NOT LIKE 'trade:%'"
    )

from datetime import datetime, timedelta


def execute(agent: dict, args: dict) -> dict:
    key = args.get("key")
    value = args.get("value")
    category = args.get("category")
    ttl = args.get("ttl_seconds")

    if not key or not isinstance(key, str):
        return {"status": "error", "error": "key (string) is required"}
    if value is None:
        return {"status": "error", "error": "value is required"}
    value = str(value)
    if len(key) > 200:
        return {"status": "error", "error": "key too long (max 200 chars)"}
    if len(value) > 20000:
        return {"status": "error", "error": "value too long (max 20000 chars)"}

    expires_at = None
    if ttl is not None:
        try:
            ttl_s = float(ttl)
            if ttl_s > 0:
                expires_at = (datetime.utcnow() + timedelta(seconds=ttl_s)).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return {"status": "error", "error": "ttl_seconds must be numeric"}

    con = _connect()
    try:
        _purge_expired(con)
        existing = con.execute(
            "SELECT key FROM meridian_shared_memory WHERE key = ?", (key,)
        ).fetchone()
        if existing:
            con.execute(
                "UPDATE meridian_shared_memory SET value = ?, category = ?, "
                "updated_at = datetime('now'), expires_at = ? WHERE key = ?",
                (value, category, expires_at, key),
            )
            action = "updated"
        else:
            con.execute(
                "INSERT INTO meridian_shared_memory (key, value, category, expires_at) "
                "VALUES (?, ?, ?, ?)",
                (key, value, category, expires_at),
            )
            action = "inserted"
        con.commit()
    finally:
        con.close()

    return {
        "status": "success",
        "key": key,
        "action": action,
        "category": category,
        "expires_at": expires_at,
    }
