# read_file — File Reader with Pagination

Reads text files with 1-based line numbering. Large files auto-paginate — check the footer for the next offset.

**Usage:** `read_file(file_path="/workspace/path/to/file")`
- Optional: `offset` (integer, 1-based) for pagination
- Max file size: 400KB

**When to use:**
- Reading source code, configs, logs, project files
- ANY file outside the agent's KB directory
- Use `offset` param to paginate through large files

**Line format:** `10: line content` — line numbers help with patching later.

**Important:** NEVER use `read` for project files — `read` is only for KB files.
