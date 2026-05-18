# read — Knowledge Base Reader

Reads files from the agent's knowledge base (KB). For reading workspace/project files, use `read_file` instead.

**Usage:** `read("filename")` — bare filename only, e.g. `'notes.md'`, not `'/kb/notes.md'`.

**When to use:**
- Reading KB reference documents, guides, and specs
- Checking user preferences stored in `notes.md`

**Do NOT use for:**
- Source code or project files → use `read_file`
- Log files → use `read_file`
