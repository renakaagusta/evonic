"""Resolve report_to_id / report_to_channel_id for agent and sub-agent messaging."""

from __future__ import annotations

from typing import Any, Dict, Tuple

_AGENT_MSG_PREFIX = "__agent__"


def resolve_report_to_from_context(
    agent_context: Dict[str, Any],
    sender_id: str,
) -> Tuple[str, str]:
    """Map sender context to a human-visible session for reply auto-forward."""
    report_to_id = agent_context.get("user_id", "") or ""
    report_to_channel_id = agent_context.get("channel_id", "") or ""

    if not report_to_id.startswith(_AGENT_MSG_PREFIX):
        return report_to_id, report_to_channel_id

    # Inter-agent context: inherit the originating human session that the
    # runtime threaded in from the incoming message's report_to metadata.
    # This keeps replies routed to the chat the human actually used instead
    # of falling back to the agent's latest session (often a shared group).
    inherited_id = agent_context.get("report_to_id", "") or ""
    inherited_channel = agent_context.get("report_to_channel_id", "") or ""
    if inherited_id and not inherited_id.startswith(_AGENT_MSG_PREFIX):
        return inherited_id, inherited_channel

    lookup_id = sender_id
    if agent_context.get("is_subagent"):
        parent_id = agent_context.get("parent_id", "") or ""
        if parent_id:
            lookup_id = parent_id

    return _lookup_human_session(lookup_id)


def resolve_report_to_for_subagent_spawn(
    parent_agent_id: str,
    spawner_user_id: str,
    spawner_channel_id: str,
) -> Tuple[str, str]:
    """Resolve where a spawned sub-agent should report its final answer."""
    report_to_id = spawner_user_id or ""
    report_to_channel_id = spawner_channel_id or ""

    if report_to_id and not report_to_id.startswith(_AGENT_MSG_PREFIX):
        return report_to_id, report_to_channel_id

    return _lookup_human_session(parent_agent_id)


def _lookup_human_session(lookup_agent_id: str) -> Tuple[str, str]:
    from models.db import db

    human_sess = db.get_latest_human_session(lookup_agent_id)
    if human_sess:
        return human_sess.get("external_user_id", ""), human_sess.get("channel_id") or ""
    return "", ""
