# patch — Unified Diff Patcher

Apply a unified diff (unidiff) to a file. Line-number-based — good for multi-hunk changes.

**Usage:** `patch(file_path="...", patch="@@ -3,4 +3,4 @@\n context line\n-old\n+new\n...")`

**Rules:**
1. **ALWAYS read the file first** — line numbers shift after each patch
2. Include 2-3 context lines copied verbatim from the file
3. After each patch, re-read the file before applying the next one
4. Context lines are indent-tolerant but +/- lines must match exactly

**When to use:**
- Inserting/deleting multiple blocks at once
- Many changes across a file in one shot

**When to use `str_replace` instead:**
- Single targeted edits — str_replace is simpler and safer
