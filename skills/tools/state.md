# state — Workflow State Manager

Query or transition workflow state. Used for kanban task lifecycle and other state machines.

**Usage:** `state(label="namespace:action", data={...})`
- Call with no args to see all current states

**When to use:**
- Managing kanban task workflow (pick, activate, finish, pause, resume)
- Any state transition registered by the system
