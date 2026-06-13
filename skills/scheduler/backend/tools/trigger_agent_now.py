"""Trigger an agent's existing scheduled action to fire immediately.

Atlas uses this for urgent reactions (e.g., position PnL hitting -10%, fire Helm now).
Requires the target agent to already have a schedule registered — finds it by owner_id.
"""
from backend.scheduler import scheduler


def execute(agent: dict, args: dict) -> dict:
    target_agent = args.get("agent_id")
    if not target_agent:
        return {"status": "error", "error": "agent_id is required"}

    schedules = scheduler.list_schedules()
    matches = [s for s in schedules if s.get("owner_id") == target_agent]
    if not matches:
        return {"status": "error",
                "error": f"No schedule registered for agent {target_agent!r}. Atlas can only trigger agents that already have a base schedule."}

    # Prefer the enabled one if multiple; else the first
    enabled = [s for s in matches if s.get("enabled")]
    chosen = enabled[0] if enabled else matches[0]

    success = scheduler.run_now(chosen["id"])
    return {
        "status": "success" if success else "error",
        "fired_schedule": chosen["id"],
        "agent_id": target_agent,
        "name": chosen.get("name"),
        "reason_hint": args.get("reason") or "no reason given",
    }
