# set_mode — Agent Mode Switch

Transition the agent between `plan` and `execute` modes.

**Usage:** `set_mode(mode="plan"|"execute", reason="why switching")`

- `plan` mode: write tools blocked, can only read and plan
- `execute` mode: full tool access for implementation

**Present your plan to the user and wait for approval before switching to execute.**
