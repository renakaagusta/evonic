# reset_active_model — Clear Fallback Model

Clears the active fallback model flag from agent state. After calling this, the agent uses its configured primary model on the next turn.

**Usage:** `reset_active_model()` — no parameters

**When to use:**
- After a fallback model was activated and you want to return to the primary model
