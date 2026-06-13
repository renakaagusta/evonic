"""get_gmgn_token_balance — keyless wallet token balance via gmgn-cli (no Helius needed)."""
import subprocess
import json
import shutil

GMGN_CLI = "/root/.local/share/mise/installs/node/24.11.0/bin/gmgn-cli"

def execute(agent: dict, args: dict) -> dict:
    wallet = args.get("wallet_address") or args.get("wallet")
    token = args.get("mint") or args.get("token_address") or args.get("token")
    chain = args.get("chain", "sol")

    if not wallet:
        return {"found": False, "error": "wallet_address is required"}
    if not token:
        return {"found": False, "error": "mint is required"}

    cli = shutil.which("gmgn-cli") or GMGN_CLI
    try:
        result = subprocess.run(
            [cli, "portfolio", "token-balance",
             "--chain", chain,
             "--wallet", wallet,
             "--token", token,
             "--raw"],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            return {"found": False, "error": result.stderr.strip() or "gmgn-cli error"}

        data = json.loads(result.stdout.strip())
        balances = data.get("balances", [])
        if not balances:
            return {"found": True, "balance": 0, "wallet": wallet, "mint": token}

        b = balances[0]
        raw_bal = b.get("balance", "0")
        # balance is already in UI units (decimals applied)
        balance = float(raw_bal)
        return {
            "found": True,
            "source": "gmgn-cli",
            "wallet": wallet,
            "mint": token,
            "balance": balance,
            "block_height": b.get("height"),
        }
    except subprocess.TimeoutExpired:
        return {"found": False, "error": "gmgn-cli timeout"}
    except Exception as e:
        return {"found": False, "error": str(e)}
