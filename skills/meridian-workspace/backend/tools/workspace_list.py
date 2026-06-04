"""workspace_list — list facts, optionally filtered by category and/or key prefix."""

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
    category = args.get("category")
    key_prefix = args.get("key_prefix")
    try:
        limit = int(args.get("limit") or 50)
    except Exception:
        limit = 50
    limit = max(1, min(200, limit))

    where = []
    params = []
    if category:
        where.append("category = ?")
        params.append(category)
    if key_prefix:
        where.append("key LIKE ?")
        params.append(f"{key_prefix}%")
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    con = _connect()
    try:
        _purge_expired(con)
        rows = con.execute(
            f"SELECT key, value, category, created_at, updated_at, expires_at "
            f"FROM meridian_shared_memory {where_sql} "
            f"ORDER BY updated_at DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
    finally:
        con.close()

    return {
        "status": "success",
        "count": len(rows),
        "entries": [_row_to_dict(r) for r in rows],
    }
