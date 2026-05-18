# save_plan — Save Plan File

Save a markdown plan file and link it to agent state for persistent context injection.

**Usage:** `save_plan(filename="plan-name.md", content="markdown content")`

**When to use:**
- After creating a detailed implementation plan
- The plan is re-injected into context on every turn

**Call this BEFORE switching to execute mode.**
