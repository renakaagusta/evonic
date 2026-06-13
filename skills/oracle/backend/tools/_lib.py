"""Shared subprocess bridge for Oracle CLI tools (Bun/TS engine).

Mirrors the Meridian bridge: each tool handler delegates to call(tool, args).
The heavy logic lives in the Oracle repo (Bun/TS); this is thin glue that:
- invokes `bun run src/cli.ts <subcommand> --flags` with cwd=ORACLE_DIR
  (Bun auto-loads ORACLE_DIR/.env)
- maps LLM-visible args to CLI flags
- parses JSON stdout (or returns Markdown for report tools)

Oracle is advisory-only: there is no trade/execution tool here by construction.
"""

import json
import os
import subprocess

ORACLE_DIR = os.environ.get("ORACLE_DIR", "/root/oracle")
BUN = os.environ.get("ORACLE_BUN", "bun")
CLI = os.path.join("src", "cli.ts")
DEFAULT_TIMEOUT_SEC = 120

TIMEOUTS = {
    "oracle_candidates": 240,  # pulls + screens a whole universe via the gateway
    "oracle_backtest": 180,
}

# Tools whose stdout is Markdown, not JSON.
MARKDOWN_TOOLS = {"oracle_daily_brief", "oracle_weekly_review"}


def _flag(name, value):
    if value is None or value == "":
        return []
    return [name, str(value)]


def _argv_for(tool: str, args: dict) -> list[str]:
    a = args or {}
    if tool == "oracle_candidates":
        return ["candidates", *_flag("--class", a.get("asset_class")),
                *_flag("--limit", a.get("limit")), *_flag("--session", a.get("session"))]
    if tool == "oracle_publish_stance":
        # Pass the whole structured stance as one JSON arg.
        return ["publish-stance", "--json", json.dumps(a, separators=(",", ":"))]
    if tool == "oracle_grade_due":
        return ["grade-due", *_flag("--now", a.get("now"))]
    if tool == "oracle_scorecard":
        return ["scorecard", *_flag("--class", a.get("asset_class"))]
    if tool == "oracle_backtest":
        return ["backtest", *_flag("--class", a.get("asset_class")), *_flag("--horizon", a.get("horizon"))]
    if tool == "oracle_tick_plan":
        return ["tick-plan", *_flag("--class", a.get("asset_class")), *_flag("--last-run", a.get("last_run"))]
    if tool == "oracle_daily_brief":
        return ["daily-brief"]
    if tool == "oracle_weekly_review":
        return ["weekly-review"]
    if tool == "oracle_tuning":
        return ["tuning"]
    raise ValueError(f"Unknown oracle tool: {tool}")


def call(tool: str, args: dict, agent: dict | None = None) -> dict:
    timeout = TIMEOUTS.get(tool, DEFAULT_TIMEOUT_SEC)
    try:
        argv = _argv_for(tool, args)
    except ValueError as e:
        return {"status": "error", "error": str(e)}

    try:
        proc = subprocess.run(
            [BUN, "run", CLI, *argv],
            cwd=ORACLE_DIR,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return {"status": "error", "error": f"bun not found at '{BUN}' (set ORACLE_BUN)"}
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": f"oracle cli timed out after {timeout}s", "argv": argv}

    if proc.returncode != 0:
        return {
            "status": "error",
            "error": f"oracle cli failed (exit={proc.returncode})",
            "stderr_tail": (proc.stderr or "").strip()[-600:],
            "stdout_tail": (proc.stdout or "").strip()[-600:],
            "argv": argv,
        }

    out = (proc.stdout or "").strip()
    if tool in MARKDOWN_TOOLS:
        return {"status": "success", "markdown": out}
    if not out:
        return {"status": "success", "data": None}
    try:
        return {"status": "success", "data": json.loads(out)}
    except json.JSONDecodeError:
        return {"status": "error", "error": "non-json stdout", "stdout_tail": out[-800:], "argv": argv}
