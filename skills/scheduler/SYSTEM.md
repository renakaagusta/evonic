# Scheduler Skill

You have access to a global scheduler that lets you create timed jobs: one-shot reminders, recurring tasks, and cron-based triggers.

## Action Types

| Action Type | Behaviour |
|-------------|-----------|
| `static_message` | Deliver a pre-composed message directly to the user, bypassing the LLM. Use this for simple reminders/nudges. |
| `session_prompt` | Send a prompt through the user's real session, triggering full LLM processing with tool access. Use this when you need the agent to run code, query data, or make decisions at execution time. |
| `emit_event` | Emit a system event. |

> **Deprecated:** `agent_message` is a deprecated alias for `static_message`. It still works but prefer `static_message` in new code.

## Quick Reference

### Static message — one-shot reminder (fire once at a specific time)
```json
{
  "name": "Remind about meeting",
  "trigger_type": "date",
  "trigger_config": {"run_date": "2026-04-21T14:00:00"},
  "action_type": "static_message",
  "action_config": {"message": "Reminder: team meeting in 15 minutes!"}
}
```

### Static message — recurring interval (every N minutes/hours)
```json
{
  "name": "Check deploy status",
  "trigger_type": "interval",
  "trigger_config": {"minutes": 30},
  "action_type": "static_message",
  "action_config": {"message": "Please check the deployment status."}
}
```

### Static message — cron schedule (e.g. weekdays at 9 AM)
```json
{
  "name": "Daily standup reminder",
  "trigger_type": "cron",
  "trigger_config": {"day_of_week": "mon-fri", "hour": 9, "minute": 0},
  "action_type": "static_message",
  "action_config": {"message": "Good morning! Time for the daily standup."}
}
```

### Session prompt — LLM-driven scheduled task
```json
{
  "name": "Check and summarise PR status",
  "trigger_type": "interval",
  "trigger_config": {"hours": 4},
  "action_type": "session_prompt",
  "action_config": {"message": "List all open pull requests, summarise their current state, and report any conflicts or stale reviews."}
}
```

## Notes
- When using `static_message` or `session_prompt`, if you omit `agent_id` in `action_config`, the message is sent to you (the calling agent).
- `static_message` delivers text as-is — it will never invoke the LLM or tools.
- `session_prompt` always goes through `handle_message()` — the agent's full LLM pipeline runs with tool access. Use this when the task needs fresh data or decisions.
- Use `list_schedules` to see your active schedules and their IDs.
- Use `cancel_schedule` with the schedule ID to stop a recurring job.
- All times are in server local time unless otherwise specified.
- `date` triggers automatically set `max_runs=1`.
