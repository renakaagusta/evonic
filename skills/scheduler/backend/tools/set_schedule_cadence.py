"""Update an existing schedule's cron cadence or enabled state.

Used by Atlas (orchestrator) to scale agent cadence based on portfolio state.
"""
from backend.scheduler import scheduler
from models.db import db


def _find_schedule_by_owner_or_name(owner_id: str | None, name_substring: str | None) -> dict | None:
    schedules = scheduler.list_schedules()
    for s in schedules:
        if owner_id and s.get("owner_id") == owner_id:
            return s
        if name_substring and name_substring.lower() in (s.get("name") or "").lower():
            return s
    return None


def execute(agent: dict, args: dict) -> dict:
    target = args.get("agent_id") or args.get("schedule_name") or args.get("schedule_id")
    if not target:
        return {"status": "error", "error": "agent_id, schedule_name, or schedule_id required"}

    minutes = args.get("minutes_interval")
    cron_minute = args.get("cron_minute")
    enabled = args.get("enabled")

    # Find schedule
    sched = None
    if args.get("schedule_id"):
        sched = scheduler.get_schedule(args["schedule_id"])
    if not sched:
        sched = _find_schedule_by_owner_or_name(
            args.get("agent_id"),
            args.get("schedule_name"),
        )
    if not sched:
        return {"status": "error", "error": f"No schedule found for target {target!r}"}

    sched_id = sched["id"]
    changes = {}

    # Build new trigger_config if cadence change requested
    if minutes is not None or cron_minute is not None:
        if minutes is not None:
            try:
                m = max(1, int(minutes))
            except Exception:
                return {"status": "error", "error": "minutes_interval must be integer"}
            new_trigger = {"trigger_type": "interval", "trigger_config": {"minutes": m}}
        else:
            new_trigger = {"trigger_type": "cron", "trigger_config": {"minute": str(cron_minute)}}
        # Update DB row
        db.update_schedule(sched_id, **new_trigger)
        changes.update(new_trigger)
        # Re-register the job in APScheduler with new trigger
        scheduler._register_job(sched_id, new_trigger["trigger_type"], new_trigger["trigger_config"])
        scheduler._update_next_run(sched_id)

    # Toggle enabled if requested
    if enabled is not None:
        want_on = bool(enabled)
        if sched.get("enabled") != (1 if want_on else 0):
            scheduler.toggle_schedule(sched_id)
            changes["enabled"] = want_on

    if not changes:
        return {"status": "noop", "schedule_id": sched_id, "name": sched.get("name"),
                "message": "No changes requested"}

    updated = scheduler.get_schedule(sched_id)
    return {
        "status": "success",
        "schedule_id": sched_id,
        "name": updated.get("name") if updated else sched.get("name"),
        "owner_id": updated.get("owner_id") if updated else sched.get("owner_id"),
        "applied": changes,
        "next_run_at": updated.get("next_run_at") if updated else None,
    }
