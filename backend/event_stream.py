"""
Lightweight event bus for agent runtime events.

Usage:
    from backend.event_stream import event_stream

    # Subscribe
    event_stream.on('processing_started', my_handler)

    # Emit
    event_stream.emit('processing_started', {'agent_id': ..., ...})

    # Unsubscribe
    event_stream.off('processing_started', my_handler)

Handlers are called asynchronously in a thread pool and must not block.
Events are logged to logs/events.log (configurable via EVENT_LOG_FILE in .env).
"""

import collections
import itertools
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

_logger = logging.getLogger(__name__)


class EventStream:
    def __init__(self):
        self._listeners: Dict[str, List[Callable]] = {}
        self._lock = threading.Lock()
        self._log_lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix='event')
        self._log_file: str = None  # resolved lazily to avoid import-time circular deps
        # Sequence numbering and ring buffers for gap-fill recovery
        self._seq_counter = itertools.count(1)
        self._buffer_lock = threading.Lock()
        self._global_buffer: collections.deque = collections.deque(maxlen=1000)
        self._session_buffers: Dict[str, collections.deque] = {}
        self._web_listeners: Dict[str, int] = {}

    def _get_log_file(self) -> str:
        if self._log_file is None:
            from config import EVENT_LOG_FILE
            self._log_file = EVENT_LOG_FILE
            os.makedirs(os.path.dirname(self._log_file), exist_ok=True)
        return self._log_file

    def _write_log(self, line: str):
        try:
            log_file = self._get_log_file()
            ts = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            with self._log_lock:
                with open(log_file, 'a', encoding='utf-8') as f:
                    f.write(f"[{ts}] {line}\n")
        except Exception as e:
            _logger.error("Failed to write log: %s", e)

    def on(self, event_name: str, callback: Callable):
        """Subscribe a callback to an event."""
        with self._lock:
            self._listeners.setdefault(event_name, []).append(callback)

    def off(self, event_name: str, callback: Callable):
        """Unsubscribe a callback from an event."""
        with self._lock:
            if event_name in self._listeners:
                self._listeners[event_name] = [
                    cb for cb in self._listeners[event_name] if cb != callback
                ]

    def emit(self, event_name: str, data: dict):
        """Emit an event to all subscribers (non-blocking)."""
        seq = next(self._seq_counter)
        data['_seq'] = seq
        data['_event'] = event_name
        # Store in ring buffers for gap-fill queries
        session_id = data.get('session_id')
        entry = {'seq': seq, 'event': event_name, 'data': data}
        with self._buffer_lock:
            self._global_buffer.append(entry)
            if session_id:
                if session_id not in self._session_buffers:
                    self._session_buffers[session_id] = collections.deque(maxlen=500)
                self._session_buffers[session_id].append(entry)
        preview = ', '.join(f'{k}={str(v)[:120]}' for k, v in data.items() if not k.startswith('_'))
        self._write_log(f"[seq={seq}] {event_name} | {preview}")
        with self._lock:
            listeners = list(self._listeners.get(event_name, []))
        for cb in listeners:
            self._executor.submit(self._safe_call, event_name, cb, data)

    def get_events_in_range(self, session_id: str, after_seq: int, up_to_seq: int) -> list:
        """Return buffered events for session_id where after_seq < seq <= up_to_seq."""
        with self._buffer_lock:
            buf = self._session_buffers.get(session_id, collections.deque())
            return [e for e in buf if after_seq < e['seq'] <= up_to_seq]

    def get_session_events(self, session_id: str, after_seq: int = 0) -> list:
        """Return all buffered events for session_id with seq > after_seq."""
        with self._buffer_lock:
            buf = self._session_buffers.get(session_id, collections.deque())
            return [e for e in buf if e['seq'] > after_seq]

    def cleanup_session_buffer(self, session_id: str):
        """Remove per-session buffer (called after turn completes)."""
        with self._buffer_lock:
            self._session_buffers.pop(session_id, None)

    def register_web_listener(self, session_id: str):
        with self._lock:
            self._web_listeners[session_id] = self._web_listeners.get(session_id, 0) + 1

    def unregister_web_listener(self, session_id: str):
        with self._lock:
            count = self._web_listeners.get(session_id, 0) - 1
            if count <= 0:
                self._web_listeners.pop(session_id, None)
            else:
                self._web_listeners[session_id] = count

    def has_web_listener(self, session_id: str) -> bool:
        with self._lock:
            return self._web_listeners.get(session_id, 0) > 0

    def _safe_call(self, event_name: str, cb: Callable, data: dict):
        try:
            cb(data)
        except Exception as e:
            self._write_log(f"ERROR listener on '{event_name}': {e}")
            _logger.error("Listener error on '%s': %s", event_name, e)


event_stream = EventStream()


# ── Swarmscope mirror (additive, observation-only) ──────────────────────────
# One listener turns every agent turn into a swarmscope span (reasoning + tool
# steps) under a per-session trace, plus a real-name heartbeat (with avatar) —
# so the swarm play-by-play is real, not synthesized. Data is partitioned by
# STACK (namespace): trader agents -> meme stack, the rest -> LP stack.
# Runs in the event-bus thread pool (exception-safe + non-blocking); each
# request is timeout-guarded. Uses the swarmscope ADMIN key so the per-agent
# namespace override is honored.
import base64 as _b64

_AV_CACHE: dict = {}


def swarmscope_ns_for(agent_id: str) -> str:
    """Stack -> namespace. Trader agents are the meme-trading stack."""
    return "meridian-meme" if "trader" in (agent_id or "") else "meridian-dlmm"


def swarmscope_avatar(agent_id: str):
    """Agent avatar as a base64 data-URL (cached per process). None if absent."""
    if not agent_id:
        return None
    if agent_id in _AV_CACHE:
        return _AV_CACHE[agent_id]
    data = None
    try:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(root, "shared", "avatars", agent_id, "avatar.png")
        if os.path.isfile(path) and os.path.getsize(path) < 2_000_000:
            with open(path, "rb") as f:
                raw = f.read()
            mime = "image/png" if raw[:8] == b"\x89PNG\r\n\x1a\n" else ("image/jpeg" if raw[:2] == b"\xff\xd8" else "image/png")
            data = f"data:{mime};base64," + _b64.b64encode(raw).decode("ascii")
    except Exception:
        data = None
    _AV_CACHE[agent_id] = data
    return data


# Tool name (substring) -> verdict word. Action tools outrank read-only ones,
# so a turn that both screened AND deployed reads as "deploy". Applies to every
# agent in both stacks (LP + meme), not just the screeners.
_SWARMSCOPE_VERDICT = {
    "deploy_position": "deploy", "open_position": "deploy", "add_liquidity": "deploy",
    "close_position": "close", "remove_liquidity": "close", "claim_fees": "claim",
    "swap_token": "swap", "buy": "buy", "sell": "sell", "rebalance": "rebalance",
    "send_agent_message": "handoff", "set_position_note": "note", "update_config": "config",
}


def _swarmscope_verdict(tool_names, tools_present, is_err):
    """One-word verdict for a turn, derived from the tools it actually called."""
    if is_err:
        return "error"
    verdict = None
    for name in tool_names:
        low = str(name).lower()
        for key, v in _SWARMSCOPE_VERDICT.items():
            if key in low:
                verdict = v  # last matching action wins
    if verdict:
        return verdict
    return "analyze" if tools_present else "hold"


def _swarmscope_turn_listener(data: dict) -> None:
    """Turn every agent turn into an inspectable decision cycle: verdict (what) +
    reasoning (why) + tool steps (how). Additive, fire-and-forget, per-turn trace
    so each decision is its own cycle. Covers all agents across both stacks."""
    url = os.getenv("SWARMSCOPE_URL", "")
    key = os.getenv("SWARMSCOPE_KEY", "")
    if not url or not key:
        return
    try:
        import requests
        import time as _time
        agent_id = data.get("agent_id") or ""
        agent = data.get("agent_name") or agent_id or "agent"
        sid = data.get("session_id") or ""
        resp = (data.get("response") or "").strip()
        tools = data.get("tool_trace") or []
        is_err = bool(data.get("is_error"))
        # Skip trivial turns (no work + nothing said) so the funnel stays meaningful.
        if not tools and len(resp) < 80 and not is_err:
            return
        ns = swarmscope_ns_for(agent_id)
        hdr = {"x-api-key": key}

        # Normalise tool_trace items (dicts or strings) -> name + optional args/result.
        tool_objs = []
        for t in (tools or [])[:14]:
            if isinstance(t, dict):
                tool_objs.append({
                    "name": t.get("tool") or t.get("name") or t.get("function") or "tool",
                    "args": t.get("args") if t.get("args") is not None else (t.get("input") if t.get("input") is not None else t.get("arguments")),
                    "result": t.get("result") if t.get("result") is not None else t.get("output"),
                })
            else:
                tool_objs.append({"name": str(t)[:40], "args": None, "result": None})
        tool_names = [t["name"] for t in tool_objs]
        verdict = _swarmscope_verdict(tool_names, bool(tools), is_err)

        # One trace per turn -> each agent decision is its own cycle in the funnel.
        ts_ms = int(_time.time() * 1000)
        tid = f"evo:{sid or agent}:{ts_ms}"
        first_line = resp.split("\n", 1)[0].strip()
        if first_line:
            summary = f"{verdict} · {first_line[:96]}"
        elif tool_names:
            summary = f"{verdict} · {len(tool_names)} tool{'s' if len(tool_names) != 1 else ''}"
        else:
            summary = verdict

        dec = {
            "namespace": ns, "trace_id": tid, "agent": agent, "kind": "agent-turn",
            "decision_type": verdict, "summary": summary[:140],
            "reasoning": resp[:4000],
            "context": {"tools": tool_names, "thinking_s": data.get("thinking_duration")},
        }
        if is_err:
            dec["error"] = "turn error"
        requests.post(f"{url}/v1/decisions", timeout=2.5, headers=hdr, json=dec)

        # Tool calls as ordered spans so the Execution timeline shows the HOW.
        for i, t in enumerate(tool_objs):
            started = _time.strftime("%Y-%m-%dT%H:%M:%S", _time.gmtime((ts_ms + i * 1000) / 1000)) + "Z"
            out = {}
            if t["args"] is not None:
                out["args"] = str(t["args"])[:300]
            if t["result"] is not None:
                out["result"] = str(t["result"])[:300]
            requests.post(f"{url}/v1/spans", timeout=2.5, headers=hdr, json={
                "namespace": ns, "trace_id": tid, "agent": agent, "type": "tool",
                "name": t["name"], "status": "ok", "started_at": started,
                "output": (out or None),
            })

        requests.post(f"{url}/v1/agents/heartbeat", timeout=2.5, headers=hdr, json={
            "namespace": ns, "name": agent, "role": "worker", "status": "online",
            "attributes": {"agent_id": agent_id, "stack": ns, "avatar": swarmscope_avatar(agent_id)},
        })
    except Exception:
        pass


try:
    event_stream.on("turn_complete", _swarmscope_turn_listener)
except Exception:
    pass


# ── Roster sweep: register the FULL agent roster (not just active ones) ───────
# Every agent acts only occasionally, so on-activity heartbeats leave the
# registry sparse (esp. idle stacks). This daemon periodically heartbeats every
# configured agent with its real status + avatar, partitioned by stack.
def _swarmscope_roster_sweep() -> None:
    import time
    time.sleep(25)  # let the app + DB finish starting
    while True:
        url = os.getenv("SWARMSCOPE_URL", "")
        key = os.getenv("SWARMSCOPE_KEY", "")
        if url and key:
            try:
                import requests
                from models.db import db
                for a in (db.get_agents() or []):
                    aid = a.get("id") or ""
                    if not aid:
                        continue
                    name = a.get("name") or aid
                    ns = swarmscope_ns_for(aid)
                    status = "online" if a.get("enabled", 1) else "offline"
                    try:
                        requests.post(f"{url}/v1/agents/heartbeat", timeout=2.5,
                                      headers={"x-api-key": key}, json={
                                          "namespace": ns, "name": name, "role": "worker", "status": status,
                                          "attributes": {"agent_id": aid, "stack": ns, "avatar": swarmscope_avatar(aid)},
                                      })
                    except Exception:
                        pass
            except Exception:
                pass
        time.sleep(300)


try:
    threading.Thread(target=_swarmscope_roster_sweep, daemon=True).start()
except Exception:
    pass
