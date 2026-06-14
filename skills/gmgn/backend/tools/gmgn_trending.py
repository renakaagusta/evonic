"""gmgn_trending — wraps `gmgn-cli market trending`."""
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
    # gmgn-cli sometimes exits non-zero while still emitting a valid `code:0`
    # payload on stdout. Trust the payload over the process exit code so we
    # don't discard good candidates (was: "error wrapper broken" for 25+ cycles).
    out = (proc.stdout or "").strip()
    if out:
        try:
            payload = json.loads(out)
            if payload.get("code") == 0:
                return {"status": "success", "data": payload}
            return {"status": "error", "error": f"gmgn code {payload.get('code')}", "raw": out[:800]}
        except json.JSONDecodeError:
            pass
    if proc.returncode != 0:
        return {"status": "error", "error": (proc.stderr or proc.stdout or "gmgn-cli failed")[:1000]}
    return {"status": "error", "error": "non-json gmgn-cli stdout", "raw": out[:800]}


def execute(agent: dict, args: dict) -> dict:
    a = args or {}
    chain = a.get("chain", "sol")
    interval = a.get("interval", "1h")
    limit = int(a.get("limit", 10) or 10)
    return _run([
        "market", "trending",
        "--chain", chain,
        "--interval", interval,
        "--limit", str(limit),
    ])
