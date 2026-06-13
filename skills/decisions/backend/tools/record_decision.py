"""record_decision — write one structured decision row.

Agents call this once per asset evaluated, before turn_complete.
Helpers inlined to avoid Evonic cross-skill tools.* namespace collisions.
"""
import json
import sqlite3
from datetime import datetime

DB_PATH = "/root/evonic/shared/db/evonic.db"
RETENTION_DAYS = 30

_SCHEMA_STMTS = [
    """CREATE TABLE IF NOT EXISTS decision_log (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ts TEXT NOT NULL,
      agent_id TEXT NOT NULL,
      cycle_id TEXT,
      asset_mint TEXT,
      asset_symbol TEXT,
      pool_address TEXT,
      phase TEXT NOT NULL,
      decision TEXT NOT NULL,
      confidence REAL,
      primary_reason TEXT NOT NULL,
      data_snapshot TEXT,
      rules_evaluated TEXT,
      next_step TEXT,
      reasoning_text TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_decision_log_asset ON decision_log(asset_mint, ts DESC)",
    "CREATE INDEX IF NOT EXISTS idx_decision_log_agent ON decision_log(agent_id, ts DESC)",
    "CREATE INDEX IF NOT EXISTS idx_decision_log_cycle ON decision_log(cycle_id)",
    "CREATE INDEX IF NOT EXISTS idx_decision_log_ts ON decision_log(ts DESC)",
    "CREATE INDEX IF NOT EXISTS idx_decision_log_decision ON decision_log(decision, ts DESC)",
]


def _ensure_schema(con):
    for stmt in _SCHEMA_STMTS:
        con.execute(stmt)
    con.execute(
        "DELETE FROM decision_log WHERE ts < datetime('now', ?)",
        (f"-{RETENTION_DAYS} days",),
    )
    con.commit()


VALID_PHASES = {"screen", "verdict", "manage", "deploy", "close", "exit", "tp", "sl", "skip", "veto"}
VALID_DECISIONS = {"PROCEED", "VETO", "SKIP", "HOLD", "DEPLOY", "CLOSE", "RECENTER", "DEFER", "BUY", "SELL"}


def execute(agent: dict, args: dict) -> dict:
    agent_id = ((agent or {}).get("id") or (agent or {}).get("agent_id") or args.get("agent_id") or "unknown")
    phase = (args.get("phase") or "").strip().lower()
    decision = (args.get("decision") or "").strip().upper()
    reason = (args.get("primary_reason") or "").strip()

    if phase not in VALID_PHASES:
        return {"status": "error", "error": f"phase must be one of {sorted(VALID_PHASES)}"}
    if decision not in VALID_DECISIONS:
        return {"status": "error", "error": f"decision must be one of {sorted(VALID_DECISIONS)}"}
    if not reason or len(reason) > 1000:
        return {"status": "error", "error": "primary_reason required, max 1000 chars"}

    confidence = args.get("confidence")
    if confidence is not None:
        try:
            confidence = float(confidence)
            confidence = max(0.0, min(1.0, confidence))
        except Exception:
            confidence = None

    data_snapshot = args.get("data_snapshot")
    if data_snapshot is not None and not isinstance(data_snapshot, str):
        try:
            data_snapshot = json.dumps(data_snapshot, default=str)[:20000]
        except Exception:
            data_snapshot = str(data_snapshot)[:20000]

    rules_evaluated = args.get("rules_evaluated")
    if rules_evaluated is not None and not isinstance(rules_evaluated, str):
        try:
            rules_evaluated = json.dumps(rules_evaluated, default=str)[:10000]
        except Exception:
            rules_evaluated = str(rules_evaluated)[:10000]

    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    con = sqlite3.connect(DB_PATH, timeout=10.0)
    try:
        _ensure_schema(con)
        cur = con.execute(
            """INSERT INTO decision_log
            (ts, agent_id, cycle_id, asset_mint, asset_symbol, pool_address,
             phase, decision, confidence, primary_reason, data_snapshot,
             rules_evaluated, next_step, reasoning_text)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                ts,
                agent_id,
                (args.get("cycle_id") or args.get("session_id") or "")[:80],
                (args.get("asset_mint") or "")[:80] or None,
                (args.get("asset_symbol") or "")[:40] or None,
                (args.get("pool_address") or "")[:80] or None,
                phase,
                decision,
                confidence,
                reason[:1000],
                data_snapshot,
                rules_evaluated,
                (args.get("next_step") or "")[:200] or None,
                (args.get("reasoning_text") or "")[:4000] or None,
            ),
        )
        decision_id = cur.lastrowid
        con.commit()
    finally:
        con.close()

    return {
        "status": "success",
        "decision_id": decision_id,
        "ts": ts,
        "asset": args.get("asset_symbol") or (args.get("asset_mint") or "")[:14],
        "decision": decision,
    }
