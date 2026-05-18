"""
output_parser.py — Detect and report malformed tool calls in assistant text.

Adopted from little-coder's output-parser extension. When a model (especially
small ones) isn't trained for native function calling, it sometimes embeds
tool calls as text in the response body instead of using the tool_calls field.

This module detects three common malformed patterns:

1. Fenced ```tool blocks — ```tool\n{...}\n```
2. <tool_call> XML tags — <tool_call>{"name": "...", ...}</tool_call>
3. Bare JSON objects that look like tool calls

When detected, it builds a nudge message telling the model to use native
tool calling and includes the extracted calls so the model can re-issue them.

IMPORTANT: This module does NOT auto-execute extracted calls. It only nudges
the model to re-issue them through the native tool calling channel.

Part of the diet llm_loop.py refactor (Layout C / Pipeline).
"""

import json
import logging
import re

_logger = logging.getLogger(__name__)

# --- Pattern definitions ---

# Matches fenced ```tool ... ``` blocks
_TOOL_FENCE_RE = re.compile(
    r"```tool\s*\n(.*?)```",
    re.DOTALL | re.IGNORECASE,
)

# Matches <tool_call>...</tool_call> XML tags (Qwen-style)
_TOOL_CALL_XML_RE = re.compile(
    r"<tool_call>\s*(.*?)\s*</tool_call>",
    re.DOTALL | re.IGNORECASE,
)

# Matches bare JSON objects that look like tool calls: {"name": "...", "arguments": {...}}
# Must start with {" at a word boundary and contain both "name" and "arguments" keys.
_TOOL_CALL_JSON_RE = re.compile(
    r'\{\s*"name"\s*:\s*"[^"]+".*?"arguments"\s*:\s*\{[^}]+\}',
    re.DOTALL,
)


def detect_fenced_tool_blocks(content: str) -> list[dict]:
    """Detect ```tool ... ``` fenced blocks in text.

    Returns a list of dicts with keys:
        format:   "fenced_code"
        raw:      The raw matched text (```tool\n...\n```)
        content:  The inner content (without fence markers)

    Each inner content is parsed as JSON if possible.
    """
    results = []
    for match in _TOOL_FENCE_RE.finditer(content):
        inner = match.group(1).strip()
        parsed = None
        try:
            parsed = json.loads(inner)
        except (json.JSONDecodeError, TypeError):
            pass
        results.append({
            "format": "fenced_code",
            "raw": match.group(0),
            "content": inner,
            "parsed": parsed,
        })
    return results


def detect_xml_tool_calls(content: str) -> list[dict]:
    """Detect <tool_call>...</tool_call> XML tags in text.

    Returns a list of dicts with keys:
        format:   "xml_tag"
        raw:      The raw matched text (<tool_call>...</tool_call>)
        content:  The inner tag content
        parsed:   Parsed JSON if the content is valid JSON, else None.
    """
    results = []
    for match in _TOOL_CALL_XML_RE.finditer(content):
        inner = match.group(1).strip()
        parsed = None
        try:
            parsed = json.loads(inner)
        except (json.JSONDecodeError, TypeError):
            pass
        results.append({
            "format": "xml_tag",
            "raw": match.group(0),
            "content": inner,
            "parsed": parsed,
        })
    return results


def detect_bare_json_tool_calls(content: str) -> list[dict]:
    """Detect bare JSON objects that look like tool calls.

    Only matches JSON objects containing both "name" and "arguments" keys.
    This is intentionally narrow to avoid false positives on regular JSON
    data the model might be discussing.

    Returns a list of dicts with keys:
        format:   "bare_json"
        raw:      The raw matched JSON string
        content:  Same as raw
        parsed:   Parsed JSON dict, or None if parsing fails.
    """
    results = []
    # Skip content that's already inside fenced blocks or XML tags
    # to avoid double-counting — strip those out first
    clean = _TOOL_FENCE_RE.sub("", content)
    clean = _TOOL_CALL_XML_RE.sub("", clean)

    for match in _TOOL_CALL_JSON_RE.finditer(clean):
        raw = match.group(0)
        parsed = None
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            pass
        results.append({
            "format": "bare_json",
            "raw": raw,
            "content": raw,
            "parsed": parsed,
        })
    return results


def detect_all(content: str) -> list[dict]:
    """Run all three detectors and return combined results.

    Order: fenced blocks first, then XML tags, then bare JSON.
    Bare JSON detector strips fenced/XML content first to avoid duplicates.

    Returns a list of dicts, each with at least:
        format, raw, content, parsed
    """
    results = []
    results.extend(detect_fenced_tool_blocks(content))
    results.extend(detect_xml_tool_calls(content))
    results.extend(detect_bare_json_tool_calls(content))
    return results


def has_malformed_calls(content: str) -> bool:
    """Quick check: does this text contain any malformed tool call patterns?"""
    if not content:
        return False
    if _TOOL_FENCE_RE.search(content):
        return True
    if _TOOL_CALL_XML_RE.search(content):
        return True
    # For bare JSON, do the stripped check to avoid false positives
    clean = _TOOL_FENCE_RE.sub("", content)
    clean = _TOOL_CALL_XML_RE.sub("", clean)
    if _TOOL_CALL_JSON_RE.search(clean):
        return True
    return False


def build_nudge_message(extracted_calls: list[dict]) -> str:
    """Build a correction nudge message from extracted malformed tool calls.

    The nudge tells the model to use native tool calling and includes
    the extracted calls so the model can re-issue them.

    Args:
        extracted_calls: List of detection result dicts from detect_* functions.

    Returns:
        A user-role message string ready for injection into the conversation.
    """
    if not extracted_calls:
        return ""

    formats_seen = set(c["format"] for c in extracted_calls)
    format_descriptions = {
        "fenced_code": "```tool code blocks",
        "xml_tag": "<tool_call> XML tags",
        "bare_json": "bare JSON objects",
    }
    format_list = ", ".join(
        format_descriptions.get(f, f) for f in sorted(formats_seen)
    )

    # Build a summary of extracted calls
    call_summaries = []
    for i, call in enumerate(extracted_calls[:5]):  # cap at 5 to avoid message bloat
        if call.get("parsed") and isinstance(call["parsed"], dict):
            name = call["parsed"].get("name", call["parsed"].get("function", "?"))
            args = call["parsed"].get("arguments", call["parsed"].get("parameters", {}))
            args_preview = json.dumps(args)[:120]
            call_summaries.append(f"  {i+1}. {name}({args_preview})")
        else:
            preview = call.get("content", "")[:80]
            call_summaries.append(f"  {i+1}. [unparseable] {preview}...")

    if len(extracted_calls) > 5:
        call_summaries.append(f"  ... and {len(extracted_calls) - 5} more")

    summaries_block = "\n".join(call_summaries)

    return (
        "[SYSTEM] Your response contains tool calls embedded as text "
        f"({format_list}) instead of using native function calling. "
        "You must use the native tool_calls mechanism to invoke tools.\n\n"
        "Detected calls:\n"
        f"{summaries_block}\n\n"
        "Please re-issue these tool calls using the proper function calling "
        "format. Do NOT embed tool calls in text blocks, code fences, or XML tags."
    )
