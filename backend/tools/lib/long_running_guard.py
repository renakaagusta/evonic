"""
long_running_guard — Detect build/compile commands that may exceed bash timeout.

When a long-running command is detected, execution is rejected and the caller
receives a ready-to-use tmux/screen wrapper script with log monitoring commands.

Usage:
    from backend.tools.lib.long_running_guard import check_long_running

    result = check_long_running("make -j4")
    if result:
        # result contains run_script, log_file, monitor_script, check_status_script
        ...
"""

import re
import time

# Marker placed at the top of generated wrapper scripts so the guard
# recognises them and does not reject them a second time.
BYPASS_MARKER = "# EVONIC_LR_BYPASS"


# ============================================================================
# Long-Running Command Patterns
# ============================================================================

LONG_RUNNING_PATTERNS: list[dict[str, str]] = [
    # C/C++ build systems
    {"pattern": r"\bcmake\s+", "description": "CMake build"},
    {"pattern": r"\bmake\b(?!\s+-v\b)(?!\s+--version\b)", "description": "Make build"},
    {"pattern": r"\bninja\b(?!\s+-v\b)(?!\s+--version\b)", "description": "Ninja build"},
    {"pattern": r"\bgcc\s+", "description": "GCC compilation"},
    {"pattern": r"\bg\+\+\s+", "description": "G++ compilation"},
    {"pattern": r"\bclang\s+", "description": "Clang compilation"},
    {"pattern": r"\bclang\+\+\s+", "description": "Clang++ compilation"},
    {"pattern": r"\bmsbuild\b", "description": "MSBuild"},
    # Rust
    {"pattern": r"\bcargo\s+build\b", "description": "Cargo build"},
    {"pattern": r"\bcargo\s+test\b", "description": "Cargo test"},
    # Go
    {"pattern": r"\bgo\s+build\b", "description": "Go build"},
    {"pattern": r"\bgo\s+test\b", "description": "Go test"},
    # Java / JVM
    {"pattern": r"\bgradle\b", "description": "Gradle build"},
    {"pattern": r"\bgradlew\b", "description": "Gradle wrapper build"},
    {"pattern": r"\bmvn\s+", "description": "Maven build"},
    # .NET
    {"pattern": r"\bdotnet\s+build\b", "description": "dotnet build"},
    {"pattern": r"\bdotnet\s+publish\b", "description": "dotnet publish"},
    # JavaScript / Node.js
    {"pattern": r"\bnpm\s+run\s+build\b", "description": "npm run build"},
    {"pattern": r"\byarn\s+build\b", "description": "Yarn build"},
    {"pattern": r"\bpnpm\s+build\b", "description": "pnpm build"},
    {"pattern": r"\bwebpack\b", "description": "Webpack build"},
    {"pattern": r"\bvite\s+build\b", "description": "Vite build"},
    {"pattern": r"\bnext\s+build\b", "description": "Next.js build"},
    # Package installation (can be slow from source)
    {"pattern": r"\bnpm\s+install\b", "description": "npm install"},
    {"pattern": r"\bnpm\s+ci\b", "description": "npm ci"},
    {"pattern": r"\byarn\s+install\b", "description": "Yarn install"},
    {"pattern": r"\bpnpm\s+install\b", "description": "pnpm install"},
    {"pattern": r"\bpip\s+install\b", "description": "pip install"},
    {"pattern": r"\bapt-get\s+install\b", "description": "apt-get install"},
    {"pattern": r"\bapt\s+install\b", "description": "apt install"},
    # Docker
    {"pattern": r"\bdocker\s+build\b", "description": "Docker build"},
    {"pattern": r"\bdocker\s+compose\s+build\b", "description": "Docker Compose build"},
    {"pattern": r"\bdocker-compose\s+build\b", "description": "docker-compose build"},
    # Bazel
    {"pattern": r"\bbazel\s+build\b", "description": "Bazel build"},
    {"pattern": r"\bbazel\s+test\b", "description": "Bazel test"},
    # configure + make
    {"pattern": r"\./configure\b", "description": "./configure script"},
]


def check_long_running(script: str) -> dict | None:
    """
    Check if a bash script contains potentially long-running build commands.

    Returns None if no long-running command detected, otherwise returns a dict
    with the matched command info and tmux/screen wrapper scripts for background
    execution with logging.
    """
    # Skip if script is already a generated wrapper (contains bypass marker)
    if script.lstrip().startswith(BYPASS_MARKER):
        return None

    matched = _detect_long_running(script)
    if not matched:
        return None

    ts = str(int(time.time()))
    session_name = f"evonic_build_{ts}"
    log_file = f"/tmp/evonic_build_{ts}.log"

    run_script = _build_wrapper_script(script, session_name, log_file)
    monitor_script = f"tail -f {log_file}"
    check_status_script = (
        f'tmux has-session -t {session_name} 2>/dev/null && echo "RUNNING" || '
        f'(screen -list | grep -q {session_name} && echo "RUNNING" || echo "DONE")'
    )
    check_exit_code_script = f"tail -1 {log_file} | grep -oP '(?<=EXIT_CODE=)\\d+'"

    return {
        "matched_command": matched["description"],
        "suggestion": (
            f"Detected '{matched['description']}' which may take a long time and "
            f"cause a timeout. Run it in a tmux/screen session with logging instead. "
            f"Use the provided run_script to start, monitor_script to watch progress, "
            f"and check_status_script to check completion."
        ),
        "run_script": run_script,
        "log_file": log_file,
        "monitor_script": monitor_script,
        "check_status_script": check_status_script,
        "check_exit_code_script": check_exit_code_script,
    }


def _detect_long_running(script: str) -> dict | None:
    """Return the first matching long-running pattern, or None."""
    for entry in LONG_RUNNING_PATTERNS:
        if re.search(entry["pattern"], script, re.IGNORECASE):
            return entry
    return None


def _build_wrapper_script(
    original_script: str, session_name: str, log_file: str,
) -> str:
    """
    Generate a bash script that wraps the original command in tmux (preferred),
    screen (fallback), or nohup (last resort) with log output.
    """
    # Escape single quotes in the original script for safe embedding
    escaped = original_script.replace("'", "'\\''")

    return f"""\
{BYPASS_MARKER}
LOG_FILE="{log_file}"
SESS="{session_name}"
SCRIPT_CMD='{{ {escaped}; }}; EC=$?; echo ""; echo "EXIT_CODE=$EC"'

if command -v tmux &>/dev/null; then
  tmux new-session -d -s "$SESS" "bash -c \\"$SCRIPT_CMD\\" 2>&1 | tee \\"$LOG_FILE\\""
  echo "Started in tmux session: $SESS"
  echo "Log file: $LOG_FILE"
  echo "Monitor:  tail -f $LOG_FILE"
  echo "Status:   tmux has-session -t $SESS 2>/dev/null && echo RUNNING || echo DONE"
elif command -v screen &>/dev/null; then
  screen -dmS "$SESS" bash -c "$SCRIPT_CMD 2>&1 | tee \\"$LOG_FILE\\""
  echo "Started in screen session: $SESS"
  echo "Log file: $LOG_FILE"
  echo "Monitor:  tail -f $LOG_FILE"
  echo "Status:   screen -list | grep -q $SESS && echo RUNNING || echo DONE"
else
  nohup bash -c "$SCRIPT_CMD" > "$LOG_FILE" 2>&1 &
  echo "Started as background process (PID: $!)"
  echo "Log file: $LOG_FILE"
  echo "Monitor:  tail -f $LOG_FILE"
  echo "Status:   kill -0 $! 2>/dev/null && echo RUNNING || echo DONE"
fi"""


# ---------------------------------------------------------------------------
# Self-tests (run with: python3 -m backend.tools.lib.long_running_guard)
# ---------------------------------------------------------------------------

def _self_test():
    passed = 0

    # Test 1: Detect cmake
    r = check_long_running("cmake -B build -S .")
    assert r is not None, "Should detect cmake"
    assert "CMake" in r["matched_command"]
    assert r["log_file"].startswith("/tmp/evonic_build_")
    assert "tmux" in r["run_script"]
    assert "tail -f" in r["monitor_script"]
    passed += 1
    print(f"Test 1 PASSED: cmake detected")

    # Test 2: Detect make -j4
    r = check_long_running("make -j4")
    assert r is not None, "Should detect make"
    assert "Make" in r["matched_command"]
    passed += 1
    print(f"Test 2 PASSED: make -j4 detected")

    # Test 3: Safe command not detected
    r = check_long_running("echo hello && ls -la")
    assert r is None, "Should not detect simple commands"
    passed += 1
    print(f"Test 3 PASSED: echo/ls not flagged")

    # Test 4: make --version not detected
    r = check_long_running("make --version")
    assert r is None, "Should not detect make --version"
    passed += 1
    print(f"Test 4 PASSED: make --version not flagged")

    # Test 5: npm run build detected
    r = check_long_running("npm run build")
    assert r is not None, "Should detect npm run build"
    passed += 1
    print(f"Test 5 PASSED: npm run build detected")

    # Test 6: cargo build detected
    r = check_long_running("cargo build --release")
    assert r is not None, "Should detect cargo build"
    passed += 1
    print(f"Test 6 PASSED: cargo build detected")

    # Test 7: pip install detected
    r = check_long_running("pip install -r requirements.txt")
    assert r is not None, "Should detect pip install"
    passed += 1
    print(f"Test 7 PASSED: pip install detected")

    # Test 8: docker build detected
    r = check_long_running("docker build -t myapp .")
    assert r is not None, "Should detect docker build"
    passed += 1
    print(f"Test 8 PASSED: docker build detected")

    # Test 9: Wrapper script contains all three fallbacks
    r = check_long_running("make all")
    assert "tmux" in r["run_script"]
    assert "screen" in r["run_script"]
    assert "nohup" in r["run_script"]
    passed += 1
    print(f"Test 9 PASSED: wrapper has tmux/screen/nohup fallbacks")

    # Test 10: Script with single quotes properly escaped
    r = check_long_running("make CFLAGS='-O2 -Wall'")
    assert r is not None
    assert "'\\''" in r["run_script"]  # escaped single quote
    passed += 1
    print(f"Test 10 PASSED: single quotes escaped in wrapper")

    # Test 11: ./configure detected
    r = check_long_running("./configure --prefix=/usr/local")
    assert r is not None, "Should detect ./configure"
    passed += 1
    print(f"Test 11 PASSED: ./configure detected")

    # Test 12: check_status_script present
    r = check_long_running("gradle build")
    assert "check_status_script" in r
    assert "check_exit_code_script" in r
    passed += 1
    print(f"Test 12 PASSED: status/exit_code scripts present")

    # Test 13: Bypass marker — wrapper script not re-flagged
    r = check_long_running("make -j4")
    assert r is not None
    r2 = check_long_running(r["run_script"])
    assert r2 is None, "Wrapper script should bypass guard"
    passed += 1
    print(f"Test 13 PASSED: wrapper script bypasses guard")

    # Test 14: Bypass marker with leading whitespace
    r3 = check_long_running(f"  {BYPASS_MARKER}\nmake -j4")
    assert r3 is None, "Bypass marker with leading space should still work"
    passed += 1
    print(f"Test 14 PASSED: bypass marker with whitespace")

    print(f"\nAll {passed} tests passed!")


if __name__ == "__main__":
    _self_test()
