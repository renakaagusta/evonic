"""
skill_injector.py — Intent-based Skill Injection for dynamic tool guidance.

Adopts little-coder's 3-priority tool selection algorithm:
  Priority 1 (Error Recovery): inject the skill for the last failed tool
  Priority 2 (Recency): inject skills for the last 2-4 successful tool calls
  Priority 3 (Intent Prediction): keyword matching on user's current prompt

Also provides tool schema filtering to keep token usage under budget.

Usage:
  1. Call record_tool_call(session_id, tool_name, success=True/False) after each tool execution.
  2. Call get_guidance(agent_context, user_prompt) to get the guidance block for the system prompt.
  3. Call filter_tool_schemas(tools, session_id, user_prompt) to get the filtered tool list.
"""

import logging
import re
from collections import deque
from typing import Dict, Any, List, Optional, Set, Tuple

_logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

# Tools that are ALWAYS included regardless of intent.
# These are essential for basic operation and recovery.
UNIVERSAL_TOOLS: Set[str] = {
    # Core file & content tools
    "read", "read_file", "write_file",
    # Code modification
    "str_replace", "patch",
    # Execution
    "bash", "runpy",
    # Memory & state
    "remember", "recall",
    # Navigation
    "state",
    # Skill loading
    "use_skill",
}

# Tool that must be available when agent has skill tools loaded
SKILL_RELATED_TOOLS: Set[str] = {
    "unload_skill",
}

# Token budgets
DEFAULT_GUIDANCE_TOKEN_BUDGET = 300       # max tokens for guidance text
DEFAULT_SCHEMA_TOKEN_BUDGET = 3000        # max tokens for tool schemas (~10-15 tools)

# Recency buffer: how many recent tool calls to pull from for priority 2
MAX_RECENT_CALLS = 8
RECENCY_SELECT_COUNT = 4                  # pull up to this many from recency

# Intent prediction: max tools from keyword matching for priority 3
INTENT_MAX_SELECT = 8

# ─────────────────────────────────────────────────────────────────────────────
# Intent Map — keyword → tool name(s)
# ─────────────────────────────────────────────────────────────────────────────

INTENT_MAP: Dict[str, List[str]] = {
    # File reading / viewing
    "read": ["read", "read_file"],
    "view": ["read", "read_file"],
    "show": ["read", "read_file"],
    "open": ["read_file", "read"],
    "cat": ["read_file"],
    "look": ["read", "read_file"],
    "inspect": ["read_file", "read"],
    "examine": ["read_file", "read"],
    "check": ["read_file", "bash"],

    # File writing / creating
    "write": ["write_file"],
    "create": ["write_file", "file_create"],
    "new": ["write_file", "file_create"],
    "save": ["write_file", "save_artifact"],
    "store": ["write_file", "save_artifact"],
    "artifact": ["save_artifact"],

    # Editing / fixing
    "fix": ["str_replace", "patch"],
    "edit": ["str_replace", "patch"],
    "modify": ["str_replace", "patch"],
    "change": ["str_replace", "patch"],
    "update": ["str_replace", "write_file"],
    "patch": ["patch"],
    "replace": ["str_replace"],
    "refactor": ["str_replace", "patch", "read_file"],
    "correct": ["str_replace", "patch"],

    # Running / executing
    "run": ["bash", "runpy"],
    "execute": ["bash", "runpy"],
    "exec": ["bash", "runpy"],
    "python": ["runpy"],
    "script": ["bash", "runpy"],
    "command": ["bash"],
    "shell": ["bash"],
    "terminal": ["bash"],
    "test": ["bash", "runpy"],
    "build": ["bash"],
    "compile": ["bash"],
    "install": ["bash"],
    "pip": ["bash"],
    "npm": ["bash"],

    # Searching / finding
    "search": ["read_file", "bash"],
    "find": ["read_file", "bash"],
    "grep": ["bash"],
    "locate": ["bash"],
    "lookup": ["read_file", "read"],

    # Fetching / API calls
    "curl": ["bash"],
    "wget": ["bash"],

    # Browsing / web
    "browse": ["browser_navigate"],
    "navigate": ["browser_navigate"],
    "click": ["browser_navigate"],
    "screenshot": ["browser_screenshot"],
    "web": ["browser_navigate"],
    "url": ["browser_navigate"],

    # Database
    "database": ["database_query"],
    "query": ["database_query"],
    "sql": ["database_query"],
    "db": ["database_query"],

    # Memory / recall
    "remember": ["remember"],
    "recall": ["recall"],
    "memory": ["remember", "recall"],
    "forget": ["remember"],
    "note": ["remember", "write_file"],

    # GitHub / version control
    "git": ["bash"],
    "commit": ["bash"],
    "github": ["bash"],
    "pr": ["bash"],
    "pull request": ["bash"],
    "push": ["bash"],
    "clone": ["bash"],
    "branch": ["bash"],
    "merge": ["bash"],
    "rebase": ["bash"],

    # Research / analysis
    "research": ["read_file", "read", "bash"],
    "analyze": ["read_file", "bash", "runpy"],
    "understand": ["read_file", "read"],
    "investigate": ["read_file", "bash"],
    "debug": ["bash", "runpy", "read_file"],
    "trace": ["bash", "read_file"],
    "profile": ["bash", "runpy"],
    "benchmark": ["bash", "runpy"],

    # State management
    "plan": ["state", "save_plan", "update_tasks"],
    "task": ["update_tasks", "save_plan"],
    "todo": ["update_tasks"],
    "mode": ["set_mode"],
    "clear": ["clear_log_file"],
    "reset": ["clear_log_file", "reset_active_model"],

    # Booking / scheduling
    "booking": ["create_booking"],
    "schedule": ["create_booking"],
    "reserve": ["create_booking"],
    "appointment": ["create_booking"],

    # Notifications
    "notify": ["send_notification"],
    "notification": ["send_notification"],
    "alert": ["send_notification"],

    # Weather / external data
    "weather": ["get_weather"],
    "price": ["check_price"],
    "order": ["get_order"],
    "hotel": ["search_hotels"],
    "restaurant": ["search_restaurants"],
    "ssh": ["sshc"],

    # Calculator
    "calculate": ["calculator"],
    "calculator": ["calculator"],
    "compute": ["calculator"],
    "math": ["calculator"],
    "evaluate": ["calculator", "runpy"],

    # Date / time
    "date": ["get_current_date"],
    "time": ["get_current_date"],
    "today": ["get_current_date"],
    "current": ["get_current_date"],

    # Messaging
    "message": ["send_agent_message"],
    "tell": ["send_agent_message"],
    "ask": ["read_file", "bash"],
    "delegate": ["send_agent_message"],

    # Attachments
    "attachment": ["read_attachment"],
    "cleanup": ["cleanup_attachments"],
    "image": ["read_attachment"],

    # Skills
    "skill": ["use_skill"],
    "load": ["use_skill"],
    "plugin": ["use_skill"],
    "extension": ["use_skill"],
}


# ─────────────────────────────────────────────────────────────────────────────
# Tool Call Tracker — per-session state
# ─────────────────────────────────────────────────────────────────────────────

class ToolCallTracker:
    """Tracks recent tool calls and failures for a single session."""

    def __init__(self):
        # Most-recent-first list of tool names (capped at MAX_RECENT_CALLS)
        self.recent_calls: deque = deque(maxlen=MAX_RECENT_CALLS)
        # Last failed tool name (or None)
        self.last_failed: Optional[str] = None

    def record_call(self, tool_name: str, success: bool = True):
        """Record a tool call. Append to recent, track failure."""
        self.recent_calls.appendleft(tool_name)
        if not success:
            self.last_failed = tool_name
        else:
            # Clear the error flag if the same tool succeeds later
            if self.last_failed == tool_name:
                self.last_failed = None

    def record_error(self, tool_name: str):
        """Record an error without a successful call first (e.g., malformed call)."""
        self.last_failed = tool_name

    def get_recent(self, count: int = RECENCY_SELECT_COUNT) -> List[str]:
        """Return up to `count` most recent unique tool names."""
        seen: Set[str] = set()
        result: List[str] = []
        for name in self.recent_calls:
            if name not in seen:
                seen.add(name)
                result.append(name)
                if len(result) >= count:
                    break
        return result

    def clear_error(self):
        """Reset the last error flag."""
        self.last_failed = None

    def is_empty(self) -> bool:
        """True if no calls have been recorded yet."""
        return len(self.recent_calls) == 0 and self.last_failed is None


# ─────────────────────────────────────────────────────────────────────────────
# Per-session tracker registry
# ─────────────────────────────────────────────────────────────────────────────

_trackers: Dict[str, ToolCallTracker] = {}


def get_tracker(session_id: str) -> ToolCallTracker:
    """Get or create the tracker for a session."""
    if session_id not in _trackers:
        _trackers[session_id] = ToolCallTracker()
    return _trackers[session_id]


def record_tool_call(session_id: str, tool_name: str, success: bool = True):
    """Record a tool call outcome for a session."""
    get_tracker(session_id).record_call(tool_name, success)


def record_tool_error(session_id: str, tool_name: str):
    """Record a tool error for a session."""
    get_tracker(session_id).record_error(tool_name)


def clear_session(session_id: str):
    """Remove tracking data for a session (cleanup)."""
    _trackers.pop(session_id, None)


# ─────────────────────────────────────────────────────────────────────────────
# Tool Selection Algorithm — 3-priority
# ─────────────────────────────────────────────────────────────────────────────

def _extract_keywords(prompt: str) -> Set[str]:
    """Extract lowercase keywords from a user prompt for intent matching."""
    if not prompt:
        return set()
    text = prompt.lower()
    words = set(re.findall(r"[a-z]+", text))
    # Also match multi-word phrases
    phrases = {
        "pull request",
        "pull_request",
    }
    for phrase in phrases:
        if phrase.replace("_", " ") in text or phrase in text:
            words.add(phrase.replace(" ", "_"))
    return words


def _match_intent(keywords: Set[str]) -> List[str]:
    """Match keywords against INTENT_MAP and return ordered tool names.

    Tools are ordered by match frequency — most frequently matched first.
    """
    scores: Dict[str, int] = {}
    for kw in keywords:
        if kw in INTENT_MAP:
            for tool in INTENT_MAP[kw]:
                scores[tool] = scores.get(tool, 0) + 1
    # Sort by score descending, then alphabetically for stability
    return [t for t, _ in sorted(scores.items(), key=lambda x: (-x[1], x[0]))]


def select_tools(
    tracker: ToolCallTracker,
    user_prompt: str,
    universal_tools: Optional[Set[str]] = None,
    intent_max: int = INTENT_MAX_SELECT,
    recency_count: int = RECENCY_SELECT_COUNT,
) -> List[str]:
    """Run the 3-priority selection and return an ordered list of tool names.

    Priority 1 (Error Recovery): last failed tool
    Priority 2 (Recency): last N successful tool calls
    Priority 3 (Intent Prediction): keyword matching on user prompt

    Returns a deduplicated list in priority order.
    """
    if universal_tools is None:
        universal_tools = UNIVERSAL_TOOLS

    selected: List[str] = []
    seen: Set[str] = set()

    def add(name: str):
        """Add tool name to selected, skipping duplicates."""
        if name and name not in seen:
            seen.add(name)
            selected.append(name)

    # Priority 1: Error recovery
    if tracker.last_failed:
        add(tracker.last_failed)

    # Priority 2: Recency
    for name in tracker.get_recent(recency_count):
        add(name)

    # Priority 3: Intent prediction
    keywords = _extract_keywords(user_prompt)
    intent_tools = _match_intent(keywords)
    for name in intent_tools:
        if len(selected) >= intent_max:
            break
        add(name)

    _logger.debug(
        "select_tools: error=%s, recent=%s, keywords=%s, intent=%s, selected=%s",
        tracker.last_failed,
        list(tracker.recent_calls)[:recency_count],
        keywords,
        intent_tools[:10],
        selected,
    )

    return selected


# ─────────────────────────────────────────────────────────────────────────────
# Guidance Block Building
# ─────────────────────────────────────────────────────────────────────────────

# Inline tool-usage guidance — short instruction snippets for each tool.
# These replace the need for external markdown files in Phase 1.
# Each maps a tool name to a concise usage note (~1-3 lines).

TOOL_GUIDANCE: Dict[str, str] = {
    "read": (
        "**read** — Read a file from this agent's KB. Pass bare filename only, no paths. "
        "Not for workspace/source files — use read_file for those."
    ),
    "read_file": (
        "**read_file** — Read any text file with line numbers. Use offset for pagination. "
        "Accepts /workspace/... paths. Large files are paginated automatically."
    ),
    "write_file": (
        "**write_file** — Create a NEW file. Refuses to overwrite existing files — "
        "use str_replace for edits. Creates parent dirs automatically."
    ),
    "str_replace": (
        "**str_replace** — Replace exact text in a file. Always read_file first to get "
        "current content. Include enough context in old_str for unambiguous match."
    ),
    "patch": (
        "**patch** — Apply unified diff patches. Always read_file immediately before "
        "constructing a patch — never use stale line numbers."
    ),
    "bash": (
        "**bash** — Execute bash in an isolated Docker container. The container persists "
        "across calls. Working directory is /workspace. Use action='destroy' to tear down."
    ),
    "runpy": (
        "**runpy** — Execute Python code in the same container as bash. "
        "Files written by runpy are accessible to bash and vice versa."
    ),
    "remember": (
        "**remember** — Store facts in long-term memory. Use for user preferences, "
        "decisions, context. Categories: user_info, preference, decision, context, instruction."
    ),
    "recall": (
        "**recall** — Search long-term memory by keyword. Use before making assumptions "
        "about user preferences."
    ),
    "state": (
        "**state** — Query or transition workflow state. Call with no args to see all states. "
        "Use 'namespace:action' format for transitions."
    ),
    "use_skill": (
        "**use_skill** — Lazy-load a skill. Use before calling skill-specific tools. "
        "Only works for lazy-loaded skills."
    ),
    "unload_skill": (
        "**unload_skill** — Unload a previously loaded skill to keep context clean."
    ),
    "save_artifact": (
        "**save_artifact** — Save a file to your artifacts directory. Use after "
        "generating reports, analysis, or output files."
    ),
    "save_plan": (
        "**save_plan** — Save a markdown plan file. Re-injects into context each turn. "
        "Call before set_mode('execute')."
    ),
    "update_tasks": (
        "**update_tasks** — Manage task list. Use 'set' for full plan, 'add' for single task, "
        "'done'/'in_progress' for status updates."
    ),
    "set_mode": (
        "**set_mode** — Switch between 'plan' and 'execute' modes. Plan mode blocks write tools. "
        "Present plan for approval before switching to execute."
    ),
    "calculator": (
        "**calculator** — Simple math evaluation. Use for arithmetic only, not general code."
    ),
    "kanban_search_tasks": (
        "**kanban_search_tasks** — Search Kanban board tasks. Filter by assignee, query, status. "
        "Returns newest first."
    ),
    "kanban_update_status": (
        "**kanban_update_status** — Set task to 'in-progress' or 'done'. Use after approval."
    ),
    "kanban_add_comment": (
        "**kanban_add_comment** — Log progress on a Kanban task. Use for sub-steps and findings."
    ),
    "kanban_get_task": (
        "**kanban_get_task** — Retrieve a single Kanban task by ID."
    ),
    "kanban_create_task": (
        "**kanban_create_task** — Create a new Kanban task. Required: title. Optional: description, priority, assignee."
    ),
    "kanban_update_task": (
        "**kanban_update_task** — Update task status, assignee, title, description, priority. Supports all fields in one call."
    ),
    "kanban_delete_task": (
        "**kanban_delete_task** — Permanently delete a Kanban task. Requires approval for non-super agents."
    ),
    "kanban_get_comments": (
        "**kanban_get_comments** — Retrieve paginated comments from a Kanban task. Newest first."
    ),
    "browser_navigate": (
        "**browser_navigate** — Navigate a browser to a URL. Use for web scraping and automation."
    ),
    "browser_screenshot": (
        "**browser_screenshot** — Capture a screenshot of the current browser page."
    ),
    "database_query": (
        "**database_query** — Execute SQL queries against the configured database."
    ),
    "send_agent_message": (
        "**send_agent_message** — Send a message to another agent. Delegated tasks are "
        "processed asynchronously."
    ),
    "clear_log_file": (
        "**clear_log_file** — Truncate agent log files. Adds a reset marker with current date."
    ),
    "reset_active_model": (
        "**reset_active_model** — Clear fallback model flag. Agent reverts to primary model next turn."
    ),
    "escalate_to_user": (
        "**escalate_to_user** — Forward a message to the human user. Use when blocked in inter-agent conversations."
    ),
    "resolve_agent_approval": (
        "**resolve_agent_approval** — Approve or reject a pending tool-call approval from another agent."
    ),
    "recall_sessions": (
        "**recall_sessions** — Search past session summaries. Use without query for recent sessions."
    ),
    "send_notification": (
        "**send_notification** — Send a notification to a user or channel."
    ),
    "get_current_date": (
        "**get_current_date** — Get the current date and time."
    ),
    "check_price": (
        "**check_price** — Check current price of a product or service."
    ),
    "get_weather": (
        "**get_weather** — Get current weather for a location."
    ),
    "search_hotels": (
        "**search_hotels** — Search for hotels by location and dates."
    ),
    "search_restaurants": (
        "**search_restaurants** — Search for restaurants by location and cuisine."
    ),
    "create_booking": (
        "**create_booking** — Create a booking/reservation for a service."
    ),
    "get_order": (
        "**get_order** — Retrieve order details by ID."
    ),
    "read_attachment": (
        "**read_attachment** — Read an attached file or image from a message."
    ),
    "cleanup_attachments": (
        "**cleanup_attachments** — Clean up temporary attachment files."
    ),
    "sshc": (
        "**sshc** — Execute commands on a remote host via SSH."
    ),
}


def build_guidance_block(
    selected_tools: List[str],
    token_budget: int = DEFAULT_GUIDANCE_TOKEN_BUDGET,
) -> str:
    """Build a 'Tool Usage Guidance' block for the system prompt.

    Only includes guidance for tools that actually have entries in TOOL_GUIDANCE.
    Stops adding entries when token budget is exceeded (rough estimate).
    """
    if not selected_tools:
        return ""

    lines: List[str] = []
    # Rough token count: ~4 chars per token for English text
    token_estimate = 0
    max_chars = token_budget * 4

    header = "## Tool Usage Guidance\n\n"
    token_estimate += len(header) // 4
    lines.append(header.rstrip())

    for tool_name in selected_tools:
        guidance = TOOL_GUIDANCE.get(tool_name)
        if not guidance:
            continue
        entry = f"- {guidance}"
        entry_tokens = len(entry) // 4
        if token_estimate + entry_tokens > token_budget:
            _logger.debug("Guidance token budget reached (%d), stopping", token_budget)
            break
        token_estimate += entry_tokens
        lines.append(entry)

    if len(lines) <= 1:  # only header, no entries
        return ""

    return "\n".join(lines) + "\n"


# ─────────────────────────────────────────────────────────────────────────────
# Tool Schema Filtering
# ─────────────────────────────────────────────────────────────────────────────

def filter_tool_schemas(
    tools: List[Dict[str, Any]],
    selected_tools: List[str],
    universal_tools: Optional[Set[str]] = None,
    token_budget: int = DEFAULT_SCHEMA_TOKEN_BUDGET,
) -> List[Dict[str, Any]]:
    """Filter tool schemas to only include selected + universal tools.

    Tools are returned in order: universal first, then selected. Token budget is
    enforced — schemas are included until the estimated token count exceeds the budget.

    Args:
        tools: Full list of OpenAI tool definitions (each has 'type' and 'function' keys).
        selected_tools: Ordered list of tool names to prioritize.
        universal_tools: Set of tool names that are always included.
        token_budget: Maximum estimated tokens for the filtered tool list.

    Returns:
        Filtered tool definitions.
    """
    if universal_tools is None:
        universal_tools = UNIVERSAL_TOOLS

    # Build lookup by function name
    tool_by_name: Dict[str, Dict[str, Any]] = {}
    for t in tools:
        fn_name = t.get("function", {}).get("name", "")
        if fn_name:
            tool_by_name[fn_name] = t

    # Estimate tokens for a tool schema (name + description + parameters)
    def _estimate_tokens(tool: Dict[str, Any]) -> int:
        fn = tool.get("function", {})
        text = (
            (fn.get("name", "") or "")
            + (fn.get("description", "") or "")
            + str(fn.get("parameters", {}))
        )
        return max(1, len(text) // 4)  # ~4 chars per token

    filtered: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    token_count = 0

    def _add(name: str):
        nonlocal token_count
        if name in seen:
            return
        tool = tool_by_name.get(name)
        if not tool:
            return
        est = _estimate_tokens(tool)
        if token_count + est > token_budget:
            _logger.debug(
                "Schema token budget reached (%d/%d), skipping %s",
                token_count, token_budget, name,
            )
            return
        seen.add(name)
        token_count += est
        filtered.append(tool)

    # Phase 1: Universal tools first (guaranteed inclusion)
    for name in sorted(universal_tools):
        _add(name)

    # Phase 2: Selected tools (priority order)
    for name in selected_tools:
        _add(name)

    _logger.debug(
        "filter_tool_schemas: %d/%d tools included, ~%d tokens (budget=%d)",
        len(filtered), len(tools), token_count, token_budget,
    )

    return filtered


# ─────────────────────────────────────────────────────────────────────────────
# High-level integration entry points
# ─────────────────────────────────────────────────────────────────────────────

def get_guidance(
    session_id: str,
    user_prompt: str,
    token_budget: int = DEFAULT_GUIDANCE_TOKEN_BUDGET,
) -> str:
    """Convenience: select tools and build guidance block in one call."""
    tracker = get_tracker(session_id)
    selected = select_tools(tracker, user_prompt)
    return build_guidance_block(selected, token_budget)


def get_filtered_tools(
    session_id: str,
    user_prompt: str,
    tools: List[Dict[str, Any]],
    token_budget: int = DEFAULT_SCHEMA_TOKEN_BUDGET,
    universal_tools: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:
    """Convenience: select tools and filter schemas in one call."""
    tracker = get_tracker(session_id)
    selected = select_tools(tracker, user_prompt)
    return filter_tool_schemas(tools, selected, universal_tools, token_budget)
