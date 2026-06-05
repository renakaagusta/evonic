"""workspace_delete — remove a fact by exact key.

Issue #15 guard: a `trade:<mint>` entry is a live spot-position bag. Atlas counts
these bags to decide whether to keep Hands (meridian_trader_manager) enabled, and
Hands deletes the bag when it believes a position is "fully exited". If Hands
deletes the bag while tokens are still held on-chain (a partial/failed final
sell), the remainder becomes an orphan: no bag → Atlas sees bags=0 → Hands stays
disabled → the remainder sits unmanaged forever (see issue #15).

So before deleting a `trade:<mint>` bag we verify the on-chain balance is dust.
If a non-dust balance remains we REFUSE the delete and tell the agent to sell the
remainder first. Stale balances (right after a sell, before RPC catches up) read
as still-held → refuse → fail SAFE: the bag persists one extra cycle and Hands
re-checks. Only a confirmed dust/empty balance allows deletion.
"""

import os
import re
import json
import shutil
import sqlite3
import subprocess

DB_PATH = "/root/evonic/shared/db/evonic.db"

# Meridian CLI invocation (mirrors skills/meridian/backend/tools/_lib.py)
MERIDIAN_DIR = os.environ.get("MERIDIAN_DIR", "/root/meridian")
NODE = os.environ.get("MERIDIAN_NODE", "/root/.local/share/mise/installs/node/24.11.0/bin/node")
if not os.path.exists(NODE):
    NODE = shutil.which("node") or "node"
CLI = f"{MERIDIAN_DIR}/cli.js"
ENV_FILE = f"{MERIDIAN_DIR}/.env"

# A bag is safe to delete once the held value is below this (USD). Real exits
# leave ~0; the leftover dust (sub-cent token remainders) is below this floor.
DUST_USD = float(os.environ.get("MERIDIAN_TRADE_DUST_USD", "0.50"))

_TRADE_KEY = re.compile(r"^trade:(.+)$")


def _connect():
    con = sqlite3.connect(DB_PATH, timeout=10.0)
    con.row_factory = sqlite3.Row
    return con


def _held_usd(mint: str):
    """Return (usd, balance) for `mint` from the meridian wallet, or (None, None)
    if the balance could not be determined (CLI error/timeout)."""
    try:
        proc = subprocess.run(
            [NODE, f"--env-file={ENV_FILE}", CLI, "balance"],
            cwd=MERIDIAN_DIR, capture_output=True, text=True, timeout=45,
        )
        if proc.returncode != 0:
            return None, None
        out = (proc.stdout or "").strip()
        brace = out.find("{")
        if brace < 0:
            return None, None
        data, _ = json.JSONDecoder().raw_decode(out[brace:])
        for t in (data.get("tokens") or []):
            if t.get("mint") == mint:
                return float(t.get("usd") or 0), float(t.get("balance") or 0)
        return 0.0, 0.0  # not held → empty
    except Exception:
        return None, None


def execute(agent: dict, args: dict) -> dict:
    key = args.get("key")
    if not key or not isinstance(key, str):
        return {"status": "error", "error": "key (string) is required"}

    # ── Issue #15: never delete a trade bag while a non-dust balance remains ──
    m = _TRADE_KEY.match(key)
    if m:
        mint = m.group(1).strip()
        usd, bal = _held_usd(mint)
        if usd is not None and usd > DUST_USD:
            return {
                "status": "error",
                "error": (
                    f"refusing to delete bag {key}: {bal:g} tokens (~${usd:.2f}) "
                    f"still held on-chain (> ${DUST_USD:.2f} dust floor). Sell the "
                    f"remainder with swap_token first, then delete — otherwise the "
                    f"position is orphaned and Hands gets disabled (issue #15)."
                ),
                "held_usd": round(usd, 4),
                "held_balance": bal,
                "blocked": True,
            }

    con = _connect()
    try:
        cur = con.execute("DELETE FROM meridian_shared_memory WHERE key = ?", (key,))
        con.commit()
        deleted = cur.rowcount
    finally:
        con.close()
    return {"status": "success", "key": key, "deleted": deleted}
