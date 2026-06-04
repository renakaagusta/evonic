"""swap_token — bridges to meridian CLI via subprocess (see _lib.py).

Cross-stack guard: _lib.call() inspects the agent context and blocks any
swap_token call that would touch an active trade:<mint> bag owned by Hunter
or Hands unless the caller is in the trader stack themselves.
"""
from . import _lib

def execute(agent: dict, args: dict) -> dict:
    return _lib.call("swap_token", args, agent)
