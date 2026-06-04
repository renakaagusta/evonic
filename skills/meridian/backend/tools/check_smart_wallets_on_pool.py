"""check_smart_wallets_on_pool — bridges to meridian CLI via subprocess (see _lib.py)."""
from . import _lib

def execute(agent: dict, args: dict) -> dict:
    return _lib.call("check_smart_wallets_on_pool", args)
