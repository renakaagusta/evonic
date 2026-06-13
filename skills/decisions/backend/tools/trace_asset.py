"""trace_asset — chronological decision timeline for one mint across all agents."""
import json
import sqlite3

DB_PATH = "/root/evonic/shared/db/evonic.db"


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
    mint = (args or {}).get("asset_mint")
    if not mint:
        return {"status": "error", "error": "asset_mint required"}

    con = sqlite3.connect(DB_PATH, timeout=10.0)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT * FROM decision_log WHERE asset_mint = ? ORDER BY ts ASC",
            (mint,),
        ).fetchall()
    finally:
        con.close()

    decisions = [_row_to_dict(r) for r in rows]
    agents_seen = sorted({d.get("agent_id", "?") for d in decisions})
    decision_counts = {}
    for d in decisions:
        k = d.get("decision", "?")
        decision_counts[k] = decision_counts.get(k, 0) + 1

    return {
        "status": "success",
        "asset_mint": mint,
        "total_decisions": len(decisions),
        "agents_seen": agents_seen,
        "decision_counts": decision_counts,
        "timeline": decisions,
    }
