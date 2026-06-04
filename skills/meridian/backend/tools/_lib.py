"""Shared subprocess bridge for Meridian CLI tools.

Each tool handler delegates to call(tool_name, args, agent). This module owns:
- subprocess invocation with --env-file so Meridian/.env is loaded
- argument mapping (LLM-visible names -> CLI flags)
- JSON parsing of stdout / stderr error surfacing
- cross-stack swap guard (Hands/Hunter own trade:* mints; nobody else may swap them)
"""

import json
import os
import sqlite3
import subprocess
from pathlib import Path

MERIDIAN_DIR = "/root/meridian"
NODE = "/root/.local/share/mise/installs/node/24.11.0/bin/node"
CLI = f"{MERIDIAN_DIR}/cli.js"
ENV_FILE = f"{MERIDIAN_DIR}/.env"
DEFAULT_TIMEOUT_SEC = 180

# Per-tool timeout overrides
TIMEOUTS = {
    "get_top_candidates": 240,
    "get_momentum_candidates": 180,
    "study_top_lpers": 180,
    "estimate_close_slippage": 30,
    "deploy_position": 180,
    "close_position": 180,
    "claim_fees": 120,
    "swap_token": 120,
}


def _flag(name, value):
    """Emit [name, str(value)] if value not None/empty; else []."""
    if value is None or value == "":
        return []
    return [name, str(value)]


def _argv_for(tool: str, args: dict) -> list[str]:
    """Map LLM-visible args to the CLI subcommand + flags."""
    a = args or {}

    if tool == "deploy_position":
        argv = ["deploy"]
        argv += _flag("--pool", a.get("pool_address"))
        amount = a.get("amount_y") if a.get("amount_y") is not None else a.get("amount_sol")
        argv += _flag("--amount", amount)
        if a.get("amount_x") not in (None, 0, 0.0):
            argv += _flag("--amount-x", a["amount_x"])
        argv += _flag("--bins-below", a.get("bins_below"))
        argv += _flag("--bins-above", a.get("bins_above"))
        argv += _flag("--strategy", a.get("strategy"))
        if a.get("confidence") is not None:
            argv += _flag("--confidence", a.get("confidence"))
        return argv

    if tool == "close_position":
        argv = ["close"]
        argv += _flag("--position", a.get("position_address"))
        argv += _flag("--reason", a.get("reason"))
        if a.get("skip_swap"):
            argv.append("--skip-swap")
        return argv

    if tool == "claim_fees":
        return ["claim", *_flag("--position", a.get("position_address"))]

    if tool == "swap_token":
        argv = ["swap"]
        argv += _flag("--from", a.get("input_mint"))
        argv += _flag("--to", a.get("output_mint"))
        argv += _flag("--amount", a.get("amount"))
        return argv

    if tool == "add_pool_note":
        return [
            "pool-note",
            *_flag("--pool", a.get("pool_address")),
            *_flag("--text", a.get("note")),
        ]

    if tool == "list_smart_wallets":
        return ["smart-wallet-list"]

    if tool == "add_smart_wallet":
        argv = ["smart-wallet-add"]
        argv += _flag("--address", a.get("address"))
        argv += _flag("--name", a.get("name"))
        argv += _flag("--category", a.get("category"))
        argv += _flag("--type", a.get("type"))
        return argv

    if tool == "remove_smart_wallet":
        return ["smart-wallet-remove", *_flag("--address", a.get("address"))]

    if tool == "estimate_close_slippage":
        return ["estimate-close-slippage", *_flag("--position", a.get("position_address"))]

    if tool == "get_my_positions":
        return ["positions"]

    if tool == "get_position_pnl":
        return ["pnl", *_flag("--position", a.get("position_address"))]

    if tool == "set_position_note":
        return [
            "note",
            *_flag("--position", a.get("position_address")),
            *_flag("--text", a.get("instruction") or ""),
        ]

    if tool == "get_top_candidates":
        return ["candidates", *_flag("--limit", a.get("limit"))]

    if tool == "get_momentum_candidates":
        argv = ["momentum-candidates", *_flag("--limit", a.get("limit"))]
        argv += _flag("--min-change", a.get("min_price_change"))
        argv += _flag("--max-change", a.get("max_price_change"))
        argv += _flag("--min-tvl", a.get("min_tvl"))
        argv += _flag("--min-volume", a.get("min_volume"))
        return argv


    if tool == "get_token_holders":
        return [
            "token-holders",
            *_flag("--mint", a.get("mint")),
            *_flag("--limit", a.get("limit")),
        ]

    if tool == "check_smart_wallets_on_pool":
        return ["smart-wallets", *_flag("--pool", a.get("pool_address"))]

    if tool == "get_token_info":
        return ["token-info", *_flag("--query", a.get("query"))]

    if tool == "get_wallet_balance":
        return ["balance"]

    if tool == "study_top_lpers":
        return [
            "study",
            *_flag("--pool", a.get("pool_address")),
            *_flag("--limit", a.get("limit")),
        ]

    if tool == "get_pool_detail":
        return [
            "pool-detail",
            *_flag("--pool", a.get("pool_address")),
            *_flag("--timeframe", a.get("timeframe")),
        ]

    if tool == "get_active_bin":
        return ["active-bin", *_flag("--pool", a.get("pool_address"))]

    if tool == "recenter_position":
        argv = ["recenter"]
        argv += _flag("--position", a.get("position_address"))
        if a.get("bins_below") is not None:
            argv += _flag("--bins-below", a["bins_below"])
        argv += _flag("--strategy", a.get("strategy"))
        argv += _flag("--reason", a.get("reason"))
        return argv

    if tool == "get_token_narrative":
        return ["token-narrative", *_flag("--mint", a.get("mint"))]

    if tool == "search_pools":
        return [
            "search-pools",
            *_flag("--query", a.get("query")),
            *_flag("--limit", a.get("limit")),
        ]

    if tool == "get_pool_memory":
        return ["pool-memory", *_flag("--pool", a.get("pool_address"))]

    if tool == "evaluator":
        return ["evaluator", *_flag("--trigger", a.get("trigger") or "evonic_agent")]

    if tool == "evaluator_apply":
        argv = ["evaluator-apply"]
        if a.get("id"):
            argv += _flag("--id", a["id"])
        return argv

    if tool == "compressor":
        argv = ["compressor"]
        if a.get("role"):
            argv += _flag("--role", a["role"])
        if a.get("force"):
            argv.append("--force")
        return argv

    if tool == "get_dex_velocity":
        return ["dex", *_flag("--pool", a.get("pool_address"))]

    if tool == "get_rugcheck_report":
        return ["rugcheck", *_flag("--mint", a.get("mint"))]

    if tool == "get_pumpfun_status":
        return ["pumpfun", *_flag("--mint", a.get("mint"))]

    if tool == "get_birdeye_ohlcv":
        argv = ["birdeye-ohlcv", *_flag("--mint", a.get("mint"))]
        argv += _flag("--res", a.get("res"))
        argv += _flag("--count", a.get("count"))
        return argv

    if tool == "get_agent_health":
        return ["agent-health"]

    if tool == "send_alert":
        return ["notify", *_flag("--text", a.get("message") or a.get("text"))]

    if tool == "get_birdeye_token_stats":
        argv = ["birdeye-token-stats", *_flag("--mint", a.get("mint"))]
        argv += _flag("--timeframe", a.get("timeframe"))
        return argv

    if tool == "get_birdeye_holders":
        argv = ["birdeye-holders", *_flag("--mint", a.get("mint"))]
        argv += _flag("--size", a.get("size"))
        return argv

    if tool == "get_birdeye_markets":
        return ["birdeye-markets", *_flag("--mint", a.get("mint"))]

    if tool == "get_gmgn_wallet_tags":
        return ["gmgn-wallet-tags", *_flag("--mint", a.get("mint"))]

    if tool == "get_gmgn_top_buyers":
        return ["gmgn-top-buyers", *_flag("--mint", a.get("mint"))]

    if tool == "get_gmgn_pool_fee":
        return ["gmgn-pool-fee", *_flag("--mint", a.get("mint"))]

    if tool == "get_birdeye_velocity":
        return ["birdeye-velocity", *_flag("--mint", a.get("mint"))]

    if tool == "get_birdeye_security":
        return ["birdeye-security", *_flag("--mint", a.get("mint"))]

    if tool == "get_birdeye_gems":
        argv = ["birdeye-gems"]
        argv += _flag("--type", a.get("type"))
        argv += _flag("--limit", a.get("limit"))
        argv += _flag("--sort", a.get("sort_by"))
        argv += _flag("--tf", a.get("shown_time_frame"))
        return argv

    if tool == "get_lp_cohort":
        argv = ["lp-cohort", *_flag("--pool", a.get("pool_address"))]
        if a.get("max_owners_sampled") is not None:
            argv += _flag("--max-owners", a["max_owners_sampled"])
        return argv

    if tool == "update_config":
        # CLI is `config set <key> <value>`. LLM passes {"changes": {k: v, ...}}.
        # We return a sentinel — the caller (call()) loops over changes.
        return ["__update_config__"]

    raise ValueError(f"Unknown tool: {tool}")


def _run_once(subcommand_argv: list[str], timeout: int) -> dict:
    """Run one CLI invocation and return a parsed result dict."""
    try:
        proc = subprocess.run(
            [NODE, f"--env-file={ENV_FILE}", CLI, *subcommand_argv],
            cwd=MERIDIAN_DIR,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": f"meridian cli timed out after {timeout}s",
                "argv": subcommand_argv}
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        # Try parse last line as a structured error first
        try:
            parsed = json.loads(err.splitlines()[-1])
            return {"status": "error", **parsed, "argv": subcommand_argv, "exit_code": proc.returncode}
        except Exception:
            pass
        # Fall back to a clear diagnostic with both stdout and stderr snippets
        stdout_tail = (proc.stdout or "").strip()[-600:]
        stderr_tail = (proc.stderr or "").strip()[-600:]
        return {
            "status": "error",
            "error": f"meridian cli failed (exit={proc.returncode})",
            "stdout_tail": stdout_tail,
            "stderr_tail": stderr_tail,
            "argv": subcommand_argv,
            "exit_code": proc.returncode,
        }
    out = (proc.stdout or "").strip()
    if not out:
        return {"status": "success", "data": None}
    # Meridian's CLI may prepend `[TIMESTAMP] [LEVEL] msg` log lines and may also
    # have lines appended AFTER the JSON if a late console.log fires. Use a
    # JSONDecoder.raw_decode walk: scan each `{` position, decode the first
    # *complete* JSON object that parses cleanly, ignore everything after it.
    decoder = json.JSONDecoder()
    search_from = 0
    while True:
        brace = out.find("{", search_from)
        if brace < 0:
            break
        try:
            data, end = decoder.raw_decode(out[brace:])
            # Sanity: require a non-empty dict/list with at least one key/elem
            if isinstance(data, (dict, list)) and len(data) > 0:
                return {"status": "success", "data": data}
            # Empty result is still a valid response (e.g. no candidates)
            return {"status": "success", "data": data}
        except json.JSONDecodeError:
            search_from = brace + 1
            continue
    # Fall through: no valid JSON found. Provide diagnostic stdout snippet.
    stdout_head = out[:600]
    stdout_tail = out[-800:] if len(out) > 1400 else ""
    stderr_snippet = (proc.stderr or "").strip()[-600:]
    return {
        "status": "error",
        "error": "non-json stdout — CLI ran successfully but output was unparseable",
        "stdout_head": stdout_head,
        "stdout_tail": stdout_tail,
        "stderr_tail": stderr_snippet,
        "argv": subcommand_argv,
    }


# ── Cross-stack swap guard ──────────────────────────────────────────────────
# trade:<mint> workspace entries are written by Hunter (meridian_trader_screener)
# at trade entry and deleted by Hands (meridian_trader_manager) at exit. They
# represent active spot positions owned by the trader stack. Any swap_token call
# on those mints by another agent (Helm post-close cleanup; orchestrator;
# concierge) destroys an in-flight trade and is blocked here.
_EVONIC_DB = "/root/evonic/shared/db/evonic.db"
_TRADER_AGENT_IDS = {"meridian_trader_screener", "meridian_trader_manager"}


def _is_mint_locked_by_trade(mint: str) -> bool:
    """Return True iff a non-expired trade:<mint> workspace entry exists."""
    if not mint or not isinstance(mint, str):
        return False
    try:
        con = sqlite3.connect(_EVONIC_DB, timeout=5)
        row = con.execute(
            "SELECT 1 FROM meridian_shared_memory WHERE key = ? LIMIT 1",
            (f"trade:{mint}",),
        ).fetchone()
        con.close()
        return row is not None
    except Exception:
        # On DB error, fail-open (don't block real swaps). The prompt-level rule
        # in Helm's SYSTEM.md is the first line of defense; this is belt+suspenders.
        return False


def _check_swap_trade_lock(args: dict, agent_id: str) -> dict | None:
    """If swap_token would touch a mint owned by a trader-stack trade, block it
    unless the caller is in the trader stack. Returns an error dict to short-
    circuit the call, or None to proceed."""
    if agent_id in _TRADER_AGENT_IDS:
        return None
    input_mint = (args or {}).get("input_mint")
    if not _is_mint_locked_by_trade(input_mint):
        return None
    return {
        "status": "error",
        "blocked": True,
        "error": (
            f"swap_token blocked: mint {input_mint} has an active trade:<mint> "
            f"workspace entry owned by the trader stack (Hunter/Hands). "
            f"This is a SPOT TRADE BAG, not LP residue from a close. "
            f"If you genuinely need to exit on Hands' behalf, first send Hands a "
            f"message via send_agent_message(target=meridian_trader_manager, ...) "
            f"asking her to either exit or release the lock."
        ),
        "input_mint": input_mint,
        "caller_agent_id": agent_id,
    }


def call(tool: str, args: dict, agent: dict | None = None) -> dict:
    """Public entrypoint used by every handler in this skill."""
    timeout = TIMEOUTS.get(tool, DEFAULT_TIMEOUT_SEC)
    agent_id = (agent or {}).get("id") or (agent or {}).get("agent_id") or ""

    # Cross-stack swap guard
    if tool == "swap_token":
        block = _check_swap_trade_lock(args or {}, agent_id)
        if block is not None:
            return block

    # update_config is special: loop over changes dict
    if tool == "update_config":
        changes = (args or {}).get("changes") or {}
        if not isinstance(changes, dict) or not changes:
            return {"status": "error", "error": "update_config requires non-empty changes dict"}
        results = {}
        for k, v in changes.items():
            results[k] = _run_once(["config", "set", str(k), str(v)], timeout)
        any_err = any(r.get("status") == "error" for r in results.values())
        return {"status": "error" if any_err else "success", "results": results}

    argv = _argv_for(tool, args)
    return _run_once(argv, timeout)
