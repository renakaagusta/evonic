# bash — Shell Command Execution

Execute bash scripts in an isolated Docker container. Container persists across calls (state survives).

**Usage:** `bash(script="your bash commands here")`
- Optional: `timeout` (seconds, default 60, max 300)
- Optional: `env` (dict of environment variables)
- Optional: `action="destroy"` to tear down the container

**When to use:**
- Running shell commands, git, npm, pip, etc.
- File system operations (mkdir, cp, mv, rm, find, grep)
- Building, compiling, testing
- Any command-line tool

**The working directory is /workspace.** Use absolute paths.
