"""explain_cycle — show what happened in one agent's cycle."""
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
    a = args or {}
    agent_id = a.get("agent_id")
    cycle_id = a.get("cycle_id") or "latest"
    if not agent_id:
        return {"status": "error", "error": "agent_id required"}

    con = sqlite3.connect(DB_PATH, timeout=10.0)
    con.row_factory = sqlite3.Row
    try:
        if cycle_id == "latest":
            row = con.execute(
                "SELECT cycle_id FROM decision_log WHERE agent_id = ? "
                "AND cycle_id IS NOT NULL AND cycle_id != '' "
                "ORDER BY ts DESC LIMIT 1",
                (agent_id,),
            ).fetchone()
            if not row:
                return {"status": "success", "agent_id": agent_id, "cycle_id": None,
                        "decisions": [], "note": "No cycle decisions yet for this agent."}
            cycle_id = row["cycle_id"]

        rows = con.execute(
            "SELECT * FROM decision_log WHERE agent_id = ? AND cycle_id = ? ORDER BY ts ASC",
            (agent_id, cycle_id),
        ).fetchall()
    finally:
        con.close()

    decisions = [_row_to_dict(r) for r in rows]
    assets_evaluated = [d.get("asset_symbol") or (d.get("asset_mint") or "?")[:12]
                        for d in decisions if d.get("asset_mint")]
    decision_counts = {}
    for d in decisions:
        k = d.get("decision", "?")
        decision_counts[k] = decision_counts.get(k, 0) + 1

    return {
        "status": "success",
        "agent_id": agent_id,
        "cycle_id": cycle_id,
        "total_decisions": len(decisions),
        "assets_evaluated": assets_evaluated,
        "decision_counts": decision_counts,
        "decisions": decisions,
    }
