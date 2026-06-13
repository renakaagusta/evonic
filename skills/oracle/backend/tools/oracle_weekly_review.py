"""oracle_weekly_review — bridges to the Oracle Bun CLI (see _lib.py)."""
from . import _lib

def execute(agent: dict, args: dict) -> dict:
    return _lib.call("oracle_weekly_review", args, agent)
