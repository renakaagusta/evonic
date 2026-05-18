# write_file — Create New Files

Creates NEW files only. **REFUSES to overwrite existing files.** When a file already exists, use `str_replace` or `patch` instead.

**Usage:** `write_file(file_path="/workspace/path/to/file", content="content here")`
- Creates parent directories automatically
- For new files only — trying to overwrite fails

**When to use:**
- Creating brand-new files that don't exist yet
- First-time file creation in a project

**Do NOT use for:**
- Editing existing files → use `str_replace` or `patch`
- KB files → use path `/_self/kb/filename`
