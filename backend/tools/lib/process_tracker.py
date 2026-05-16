"""
process_tracker — Global registry of running subprocesses per session.

Allows request_stop() to kill a long-running tool immediately by session_id,
regardless of which backend (Docker, Local, SSH) is executing it.

Usage:
    from backend.tools.lib.process_tracker import process_tracker

    # Before execution
    process_tracker.register(session_id, proc, pid)
    try:
        ...  # polling loop
    finally:
        process_tracker.unregister(session_id)

    # From request_stop():
    process_tracker.kill(session_id)
"""

import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)


class ProcessTracker:
    """Thread-safe registry of running subprocesses, keyed by session_id."""

    def __init__(self):
        self._processes: dict = {}
        self._lock = threading.Lock()

    def register(self, session_id: str, proc, pid: int) -> None:
        """Store a running subprocess for a session.

        Args:
            session_id: The chat session ID.
            proc: A subprocess.Popen object (for Docker/Local) or any object
                  with a .kill() method (for SSH).
            pid: The process PID (or remote PID for SSH).
        """
        with self._lock:
            self._processes[session_id] = {
                'proc': proc,
                'pid': pid,
                'started_at': __import__('time').time(),
            }

    def unregister(self, session_id: str) -> None:
        """Remove the process entry after execution completes naturally."""
        with self._lock:
            self._processes.pop(session_id, None)

    def kill(self, session_id: str) -> None:
        """Terminate and kill the running process for a session.

        Safe to call even if the process has already finished or was never
        registered (no-op for missing entries).
        """
        with self._lock:
            info = self._processes.pop(session_id, None)
        if info is None:
            return
        proc = info['proc']
        pid = info['pid']
        try:
            logger.info(
                '[process_tracker] Killing pid=%s for session %s',
                pid, session_id[:12],
            )
            # If the object has its own .kill() method (e.g. SSH backend),
            # delegate to it.
            if hasattr(proc, 'kill') and not isinstance(proc, __import__('subprocess').Popen):
                proc.kill()
            else:
                # Standard subprocess.Popen: terminate, wait, then kill
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except __import__('subprocess').TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2)
        except Exception as e:
            logger.warning(
                '[process_tracker] Error killing pid=%s for session %s: %s',
                pid, session_id[:12], e,
            )


# Module-level singleton
process_tracker = ProcessTracker()
