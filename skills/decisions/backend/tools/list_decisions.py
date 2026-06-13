"""list_decisions — query the decision ledger.

Helpers inlined to avoid cross-skill tools.* namespace collisions.
"""
import json
import sqlite3

DB_PATH = "/root/evonic/shared/db/evonic.db"


def _ensure_table(con):
    con.execute(
        """CREATE TABLE IF NOT EXISTS decision_log (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          ts TEXT NOT NULL, agent_id TEXT NOT NULL, cycle_id TEXT,
          asset_mint TEXT, asset_symbol TEXT, pool_address TEXT,
          phase TEXT NOT NULL, decision TEXT NOT NULL,
          confidence REAL, primary_reason TEXT NOT NULL,
          data_snapshot TEXT, rules_evaluated TEXT,
          next_step TEXT, reasoning_text TEXT
        )"""
    )
    con.commit()


def _row_to_dict(row):
    d = dict(row)
    for k in ("data_snapshot", "rules_evaluated"):
        if d.get(k):
            try:
                d[k] = json.loads(d[k])
            except Exception:
                pass
    return d


def execute(agent: dict, args: dict) -> dict:
    a = args or {}
    where, params = [], []

    if a.get("asset_mint"):
        where.append("asset_mint = ?"); params.append(a["asset_mint"])
    if a.get("agent_id"):
        where.append("agent_id = ?"); params.append(a["agent_id"])
    if a.get("decision"):
        where.append("decision = ?"); params.append(str(a["decision"]).upper())
    if a.get("since_minutes_ago") is not None:
        try:
            mins = float(a["since_minutes_ago"])
            where.append("ts > datetime('now', ?)"); params.append(f"-{int(mins)} minutes")
        except Exception:
            pass

    limit = 20
    if a.get("limit"):
        try:
            limit = max(1, min(200, int(a["limit"])))
        except Exception:
            pass

    sql = "SELECT * FROM decision_log"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY ts DESC LIMIT ?"
    params.append(limit)

    con = sqlite3.connect(DB_PATH, timeout=10.0)
    con.row_factory = sqlite3.Row
    try:
        _ensure_table(con)
        rows = con.execute(sql, tuple(params)).fetchall()
    finally:
        con.close()

    return {
        "status": "success",
        "count": len(rows),
        "decisions": [_row_to_dict(r) for r in rows],
    }
