"""get_gmgn_pool_fee — bridges to meridian CLI via subprocess (see _lib.py)."""
from . import _lib


def execute(agent: dict, args: dict) -> dict:
    return _lib.call("get_gmgn_pool_fee", args)
