# remember — Long-term Memory Store

Store a fact in persistent long-term memory across future conversations.

**Usage:** `remember(content="fact to remember", category="preference|user_info|decision|context|instruction|general")`

**When to use:**
- User shares something worth remembering (name, preferences, decisions)
- Important context that should persist across sessions

**Do NOT use for:**
- Temporary data that only matters this session
- Reference documents → use `write_file` to KB
