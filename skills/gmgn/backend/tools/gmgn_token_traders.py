"""gmgn_token_traders — gmgn-cli token traders"""
import json
import os
import subprocess

GMGN_CLI = "/root/.local/share/mise/installs/node/24.11.0/bin/gmgn-cli"
ENV_FILE = "/root/.config/gmgn/.env"
DEFAULT_TIMEOUT = 30


def _env():
    env = os.environ.copy()
    try:
        for line in open(ENV_FILE):
            if "=" in line and not line.lstrip().startswith("#"):
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:
        pass
    return env


def _run(args):
    try:
        proc = subprocess.run(
            [GMGN_CLI, *args],
            capture_output=True, text=True, timeout=DEFAULT_TIMEOUT, env=_env(),
        )
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "gmgn-cli timed out"}
    if proc.returncode != 0:
        return {"status": "error", "error": (proc.stderr or proc.stdout)[:1000]}
    try:
        return {"status": "success", "data": json.loads(proc.stdout)}
    except json.JSONDecodeError:
        return {"status": "error", "error": "non-json gmgn-cli stdout", "raw": proc.stdout[:800]}


def execute(agent: dict, args: dict) -> dict:
    a = args or {}
    address = a.get("address")
    if not address:
        return {"status": "error", "error": "address required"}
    chain = a.get("chain", "sol")
    cmd = ["token", "traders"]
    limit = a.get("limit")
    if limit is not None:
        cmd += ["--limit", str(int(limit))]
    return _run(cmd + ["--chain", chain, "--address", address])
