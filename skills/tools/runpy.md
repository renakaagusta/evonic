# runpy — Python Code Execution

Execute Python code in the same Docker container as bash. Container is shared — Python-written files are accessible to bash and vice versa.

**Usage:** `runpy(script="python code here")`

**When to use:**
- Running Python scripts, data processing, analysis
- Operations that are more natural in Python than bash
- Complex logic that requires Python libraries

**When to use `bash` instead:**
- Shell commands (git, npm, pip, curl)
- Simple file operations (mkdir, cp, mv)
