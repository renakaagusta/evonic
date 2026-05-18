# update_tasks — Task List Manager

Manage the agent's internal task list for implementation progress tracking.

**Usage:** `update_tasks(action="set|add|done|in_progress|remove", ...)`
- `set`: replace entire task list
- `add`: append a single task
- `done` / `in_progress`: update task status by ID
- `remove`: delete a task

**When to use:**
- Breaking down a complex task into subtasks
- Tracking implementation progress
