# str_replace — Exact String Replacement

Surgical text replacement — safer than patch for single changes. Replace an exact string with another.

**Usage:** `str_replace(file_path="...", old_str="exact text to find", new_str="replacement text")`

**Rules:**
1. **ALWAYS read the file first** — never guess `old_str` from memory
2. Include 1-2 lines of context in `old_str` to make the match unambiguous
3. If you get "not found" → re-read the file (content changed)
4. If you get "found N times" → make `old_str` more specific

**When to use:**
- Changing a function body, a value, or a single line
- Any edit where you can identify the target text uniquely

**When to use `patch` instead:**
- Inserting/deleting blocks of many lines at once
- Making many changes across a file in one shot
