"""estimate_swap_slippage - read-only Jupiter quote for a spot swap (no tx). Bridges to meridian CLI via subprocess (see _lib.py)."""
from . import _lib

def execute(agent: dict, args: dict) -> dict:
    return _lib.call("estimate_swap_slippage", args, agent)
