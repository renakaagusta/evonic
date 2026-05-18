"""
quality_monitor.py — Post-turn quality checks with auto-correction.

Adopted from little-coder's quality-monitor extension. Detects three failure
modes at each turn end and injects automatic correction messages:

1. Empty response    — no text, no tool calls
2. Hallucinated tool — tool name not in the available tool set
3. Loop detection    — same tool + arguments repeated in sliding window

Correction messages are injected as user-role messages appended to the
conversation. A correction counter caps at 2 consecutive corrections to
prevent infinite correction loops. The counter resets on any successful
(non-corrected) turn.

Part of the diet llm_loop.py refactor (Layout C / Pipeline).
"""
from __future__ import annotations

import json
import logging

_logger = logging.getLogger(__name__)

# Maximum number of consecutive quality corrections before giving up.
# Prevents infinite correction loops when the model is fundamentally confused.
MAX_CONSECUTIVE_CORRECTIONS = 2

# System tools that are always available regardless of what the tool registry
# reports. These should never be flagged as hallucinated by the quality monitor.
_ALWAYS_AVAILABLE_TOOLS = frozenset({
    "use_skill",
    "unload_skill",
})


class QualityMonitor:
    """Tracks and enforces quality correction limits across turns."""

    def __init__(self):
        self._consecutive_count = 0

    @property
    def consecutive_count(self) -> int:
        return self._consecutive_count

    @property
    def is_capped(self) -> bool:
        """True when max consecutive corrections have been reached."""
        return self._consecutive_count >= MAX_CONSECUTIVE_CORRECTIONS

    def increment(self, reason: str = ""):
        """Record a correction — increment the counter and emit event."""
        self._consecutive_count += 1
        _logger.debug(
            "Quality correction #%d (cap=%d) reason=%s",
            self._consecutive_count, MAX_CONSECUTIVE_CORRECTIONS, reason,
        )
        # Emit event for monitoring / notifier system
        try:
            from backend.event_stream import event_stream
            event_stream.emit('quality_correction', {
                'correction_count': self._consecutive_count,
                'cap': MAX_CONSECUTIVE_CORRECTIONS,
                'is_capped': self.is_capped,
                'reason': reason,
            })
        except Exception:
            pass  # event_stream not available in all contexts

    def reset(self):
        """Reset the counter after a successful turn."""
        self._consecutive_count = 0

    def build_correction_message(self, message: str) -> str:
        """Wrap a raw correction message with the standard prefix."""
        return f"[SYSTEM] {message}"


# Singleton instance — shared across all loop instances within a process.
# Per-loop state (the counter) is managed by the caller, not the singleton.
_monitor = QualityMonitor()


def check_empty_response(
    content: str,
    tool_calls: list,
    monitor: QualityMonitor = None,
) -> str | None:
    """Check for empty response and return a correction message if needed.

    An empty response means no text content AND no tool calls.
    This typically happens when small models get confused and produce
    only whitespace or empty content.

    Args:
        content:    The assistant's text response (may be empty).
        tool_calls: List of tool calls from the response (may be empty).
        monitor:    QualityMonitor instance tracking correction count.
                    If None, uses the module-level singleton.

    Returns:
        A correction message string, or None if no correction is needed.
    """
    _mon = monitor or _monitor
    if content or tool_calls:
        return None
    if _mon.is_capped:
        _logger.warning(
            "Empty response detected but correction cap reached (%d/%d) — "
            "letting the response through as-is.",
            _mon.consecutive_count, MAX_CONSECUTIVE_CORRECTIONS,
        )
        return None
    _mon.increment(reason="empty_response")
    _logger.warning("Empty response detected — injecting correction message")
    return _mon.build_correction_message(
        "Your previous response was empty — no text content and no tool calls. "
        "You MUST provide a response. If you have nothing more to do, "
        "reply with [DONE]. Otherwise, use your tools to make progress."
    )


def check_hallucinated_tool(
    fn_name: str,
    available_tools: set,
    monitor: QualityMonitor = None,
) -> str | None:
    """Check if a called tool exists in the available set.

    Small models sometimes hallucinate tool names, especially when they
    haven't been fine-tuned for tool calling. This check catches those
    before they reach the execution layer.

    Args:
        fn_name:         The tool name the model tried to call.
        available_tools: Set of available tool function names.
        monitor:         QualityMonitor instance. If None, uses singleton.

    Returns:
        A correction message string, or None if the tool exists.
    """
    _mon = monitor or _monitor
    if fn_name in available_tools or fn_name in _ALWAYS_AVAILABLE_TOOLS:
        return None
    if _mon.is_capped:
        _logger.warning(
            "Hallucinated tool '%s' detected but correction cap reached — "
            "letting execution fail naturally.", fn_name,
        )
        return None

    _mon.increment(reason=f"hallucinated_tool:{fn_name}")
    _logger.warning("Hallucinated tool '%s' detected — injecting correction", fn_name)

    # Build a helpful list of available tools (limit to avoid message bloat)
    tool_list = sorted(available_tools)
    if len(tool_list) > 15:
        tool_preview = ", ".join(tool_list[:12]) + f", ... ({len(tool_list)} total)"
    else:
        tool_preview = ", ".join(tool_list)

    return _mon.build_correction_message(
        f"You tried to call a tool named '{fn_name}' that does not exist. "
        f"Available tools: {tool_preview}. "
        f"Please use only the tools listed above. Do NOT invent new tool names."
    )


def check_loop_detection(
    tool_call_window: list,
    fn_name: str,
    args: dict,
    threshold: int = 5,
    monitor: QualityMonitor = None,
) -> str | None:
    """Check if the same tool+args combination has been called repeatedly.

    Uses a sliding-window approach: if the same (tool, args) pair appears
    >= threshold times in the window, the model is stuck in a loop.

    Args:
        tool_call_window: Deque or list of "fn_name|json_args" keys.
        fn_name:          Current tool name being called.
        args:             Current tool arguments dict.
        threshold:        How many repetitions trigger detection. Default 5.
        monitor:          QualityMonitor instance. If None, uses singleton.

    Returns:
        A force-stop correction message, or None if no loop detected.
    """
    _mon = monitor or _monitor
    key = f"{fn_name}|{json.dumps(args, sort_keys=True, default=str)}"
    count = tool_call_window.count(key)

    if count < threshold:
        return None

    if _mon.is_capped:
        _logger.warning(
            "Loop detected (%d/%d) but correction cap reached — "
            "hard-terminating.", count, threshold,
        )
        return _mon.build_correction_message(
            f"URGENT: You have called '{fn_name}' with the same arguments "
            f"{count} times. STOP immediately. You are stuck in a loop. "
            f"Provide your FINAL answer NOW based on what you have so far. "
            f"Do NOT call any more tools."
        )

    _mon.increment(reason=f"loop_detection:{fn_name}")
    _logger.warning(
        "Loop detected (%d/%d calls for '%s') — injecting force-stop",
        count, threshold, fn_name,
    )
    return _mon.build_correction_message(
        f"URGENT: You have called the tool '{fn_name}' with the same arguments "
        f"{count} times in the last {len(tool_call_window)} tool calls. "
        f"STOP and revert to the state where you started. "
        f"Review your previous results and provide your FINAL answer."
    )
