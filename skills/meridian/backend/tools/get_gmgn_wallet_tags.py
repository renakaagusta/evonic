"""get_gmgn_wallet_tags — bridges to meridian CLI via subprocess (see _lib.py)."""
from . import _lib


def execute(agent: dict, args: dict) -> dict:
    return _lib.call("get_gmgn_wallet_tags", args)
