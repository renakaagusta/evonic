# save_artifact — Save Artifact File

Save a file to the agent's artifacts directory for web UI access.

**Usage:** `save_artifact(filename="report.md", content="...content...")`
- Optional: `mime_type` for MIME type hint
- Optional: `mode="base64"` for binary files

**When to use:**
- After completing analysis → save as report
- After generating output → save as artifact
- Any file the user or other agents may reference later
