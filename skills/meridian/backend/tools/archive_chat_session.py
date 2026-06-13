"""archive_chat_session — backup + trim chat_messages for a long-running agent session.

Safety contract:
- Backup is written and fsync'd BEFORE any deletion.
- If backup write fails, no rows are deleted.
- Only messages OLDER than the keep_last window are deleted; memories table is never touched.
- Retention cleanup (old backup files) runs after the trim, never before.
- dry_run=True returns what WOULD happen without modifying anything.
"""

import gzip
import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

EVONIC_AGENTS_DIR = "/root/evonic/agents"
BACKUP_DIR = "/root/evonic-backups/chat-history"
RETENTION_DAYS = 30

# Keep-last defaults per agent (messages, not turns)
KEEP_LAST_DEFAULTS = {
    "meridian": 150,               # Atlas: ticks every 5m, ~3-5 msgs/tick → ~30-50 ticks
    "meridian_screener": 300,      # Scout: heavier cycles, more tool calls
    "meridian_trader_screener": 200,
    "meridian_manager": 200,
    "meridian_trader_manager": 150,
}
KEEP_LAST_FALLBACK = 200
ARCHIVE_THRESHOLD = 500  # don't archive if session has fewer messages than this


def execute(agent: dict, args: dict) -> dict:
    agent_id = (args or {}).get("agent_id", "").strip()
    keep_last = int((args or {}).get("keep_last") or KEEP_LAST_DEFAULTS.get(agent_id, KEEP_LAST_FALLBACK))
    dry_run = bool((args or {}).get("dry_run", False))

    if not agent_id:
        return {"status": "error", "error": "agent_id is required"}

    db_path = os.path.join(EVONIC_AGENTS_DIR, agent_id, "chat.db")
    if not os.path.exists(db_path):
        return {"status": "error", "error": f"chat.db not found for agent {agent_id}"}

    try:
        con = sqlite3.connect(db_path, timeout=10)
        con.row_factory = sqlite3.Row

        # Find the largest active session (most messages, most recent activity)
        session_row = con.execute("""
            SELECT session_id, COUNT(*) AS n, MAX(created_at) AS last_ts
            FROM chat_messages
            GROUP BY session_id
            ORDER BY n DESC
            LIMIT 1
        """).fetchone()

        if not session_row:
            con.close()
            return {"status": "ok", "skipped": True, "reason": "no sessions found"}

        session_id = session_row["session_id"]
        total_messages = session_row["n"]
        last_ts = session_row["last_ts"]

        if total_messages < ARCHIVE_THRESHOLD:
            con.close()
            return {
                "status": "ok",
                "skipped": True,
                "session_id": session_id,
                "reason": f"only {total_messages} messages, below threshold {ARCHIVE_THRESHOLD}",
            }

        # How many rows to delete = total - keep_last
        to_delete = max(0, total_messages - keep_last)
        if to_delete == 0:
            con.close()
            return {
                "status": "ok",
                "skipped": True,
                "session_id": session_id,
                "reason": f"total {total_messages} <= keep_last {keep_last}, nothing to trim",
            }

        if dry_run:
            con.close()
            return {
                "status": "ok",
                "dry_run": True,
                "agent_id": agent_id,
                "session_id": session_id,
                "total_messages": total_messages,
                "would_delete": to_delete,
                "would_keep": keep_last,
            }

        # 1. Export rows that will be deleted to backup
        rows_to_backup = con.execute("""
            SELECT id, session_id, role, content, tool_calls, tool_call_id, metadata, created_at
            FROM chat_messages
            WHERE session_id = ?
            ORDER BY id ASC
            LIMIT ?
        """, (session_id, to_delete)).fetchall()

        backup_data = {
            "agent_id": agent_id,
            "session_id": session_id,
            "archived_at": datetime.now(timezone.utc).isoformat(),
            "total_messages_at_archive": total_messages,
            "messages_archived": len(rows_to_backup),
            "messages_retained": keep_last,
            "messages": [dict(r) for r in rows_to_backup],
        }

        # 2. Write backup (gzipped JSON)
        os.makedirs(BACKUP_DIR, exist_ok=True)
        ts_tag = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        backup_filename = f"{agent_id}_{session_id[:12]}_{ts_tag}.json.gz"
        backup_path = os.path.join(BACKUP_DIR, backup_filename)

        with gzip.open(backup_path, "wt", encoding="utf-8") as f:
            json.dump(backup_data, f, ensure_ascii=False, default=str)
        os.fsync(open(backup_path, "rb").fileno())  # ensure flush to disk

        # 3. Verify backup is readable
        with gzip.open(backup_path, "rt", encoding="utf-8") as f:
            verify = json.load(f)
        assert verify["messages_archived"] == len(rows_to_backup), "backup verification failed"

        # 4. Delete old messages (keep the most recent keep_last rows)
        max_id_to_delete = rows_to_backup[-1]["id"]
        con.execute(
            "DELETE FROM chat_messages WHERE session_id = ? AND id <= ?",
            (session_id, max_id_to_delete),
        )

        # 5. Also clear the summary so it gets rebuilt fresh from remaining messages
        con.execute("DELETE FROM chat_summaries WHERE session_id = ?", (session_id,))

        con.commit()
        con.close()

        # 6. Retention cleanup — delete backups older than RETENTION_DAYS
        deleted_backups = _cleanup_old_backups(agent_id)

        return {
            "status": "success",
            "agent_id": agent_id,
            "session_id": session_id,
            "messages_before": total_messages,
            "messages_archived": len(rows_to_backup),
            "messages_retained": keep_last,
            "backup_path": backup_path,
            "backup_size_kb": round(os.path.getsize(backup_path) / 1024, 1),
            "old_backups_deleted": deleted_backups,
        }

    except Exception as e:
        return {"status": "error", "error": str(e), "agent_id": agent_id}


def _cleanup_old_backups(agent_id: str) -> int:
    """Delete backup files for agent_id older than RETENTION_DAYS. Returns count deleted."""
    if not os.path.isdir(BACKUP_DIR):
        return 0
    cutoff = time.time() - RETENTION_DAYS * 86400
    deleted = 0
    for fname in os.listdir(BACKUP_DIR):
        if not fname.startswith(agent_id + "_") or not fname.endswith(".json.gz"):
            continue
        fpath = os.path.join(BACKUP_DIR, fname)
        if os.path.getmtime(fpath) < cutoff:
            os.remove(fpath)
            deleted += 1
    return deleted
