# unload_skill — Unload a Skill

Remove a previously loaded skill's tools from the current context.

**Usage:** `unload_skill(id="skill_id")`

**When to use:**
- After you're done with a skill
- To keep context clean and reduce token usage

**Only works for lazy-loaded skills** — eager skills' tools are always available.
