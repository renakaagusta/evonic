"""cycle_summary — aggregate stats across all agents for a time window."""
import sqlite3

DB_PATH = "/root/evonic/shared/db/evonic.db"


def execute(agent: dict, args: dict) -> dict:
    a = args or {}
    mins = 60
    if a.get("since_minutes_ago") is not None:
        try:
            mins = max(1, int(float(a["since_minutes_ago"])))
        except Exception:
            pass

    where = ["ts > datetime('now', ?)"]
    params = [f"-{mins} minutes"]
    if a.get("agent_id"):
        where.append("agent_id = ?")
        params.append(a["agent_id"])

    where_sql = " AND ".join(where)

    con = sqlite3.connect(DB_PATH, timeout=10.0)
    con.row_factory = sqlite3.Row
    try:
        total = con.execute(
            f"SELECT COUNT(*) AS n FROM decision_log WHERE {where_sql}", tuple(params)
        ).fetchone()["n"]

        by_agent = list(con.execute(
            f"SELECT agent_id, COUNT(*) AS n FROM decision_log "
            f"WHERE {where_sql} GROUP BY agent_id ORDER BY n DESC", tuple(params),
        ))
        by_decision = list(con.execute(
            f"SELECT decision, COUNT(*) AS n FROM decision_log "
            f"WHERE {where_sql} GROUP BY decision ORDER BY n DESC", tuple(params),
        ))
        by_phase = list(con.execute(
            f"SELECT phase, COUNT(*) AS n FROM decision_log "
            f"WHERE {where_sql} GROUP BY phase ORDER BY n DESC", tuple(params),
        ))
        top_assets = list(con.execute(
            f"SELECT asset_symbol, asset_mint, COUNT(*) AS n FROM decision_log "
            f"WHERE {where_sql} AND asset_mint IS NOT NULL "
            f"GROUP BY asset_mint ORDER BY n DESC LIMIT 10", tuple(params),
        ))
        rejected = list(con.execute(
            f"SELECT asset_symbol, asset_mint, COUNT(*) AS n FROM decision_log "
            f"WHERE {where_sql} AND decision IN ('VETO','SKIP') AND asset_mint IS NOT NULL "
            f"GROUP BY asset_mint ORDER BY n DESC LIMIT 10", tuple(params),
        ))
    finally:
        con.close()

    return {
        "status": "success",
        "window_minutes": mins,
        "total_decisions": total,
        "by_agent": [dict(r) for r in by_agent],
        "by_decision": [dict(r) for r in by_decision],
        "by_phase": [dict(r) for r in by_phase],
        "top_assets_evaluated": [dict(r) for r in top_assets],
        "top_assets_rejected": [dict(r) for r in rejected],
    }
