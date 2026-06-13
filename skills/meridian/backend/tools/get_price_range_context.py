"""get_price_range_context — 7-day range position via GeckoTerminal (issue #46 Gate 5)."""
from . import _lib

def execute(agent: dict, args: dict) -> dict:
    return _lib.call("get_price_range_context", args)
