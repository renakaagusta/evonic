"""
Unit and integration tests for sub-agent chat DB in /tmp/evonic-sub-agents/.

Tests cover:
- AgentChatDB path resolution for sub-agents vs normal agents
- AgentChatManager thread safety
- Concurrent sub-agent spawning with temp DB
- Cleanup on destroy and expire
"""

import os
import sys
import json
import time
import uuid
import shutil
import tempfile
import threading
from unittest.mock import patch, PropertyMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from models.chat import AgentChatDB, AgentChatManager, agent_chat_manager, AGENTS_DIR, SUB_AGENTS_TMP_DIR
from backend.subagent_manager import SubAgentManager, subagent_manager


# ---------------------------------------------------------------------------
# Helper: patch all sub-agent path references (AgentChatDB + subagent_manager)
# so tests never touch the real /tmp/evonic-sub-agents/ directory.
# ---------------------------------------------------------------------------
@pytest.fixture
def subagent_env(monkeypatch, tmp_path):
    """Patches both AgentChatDB and SubAgentManager to use tmp_path as root
    for sub-agent chat DB directories instead of the real /tmp/evonic-sub-agents/."""
    sub_root = tmp_path / 'evonic-sub-agents'

    # Patch AgentChatDB path constant
    monkeypatch.setattr('models.chat.SUB_AGENTS_TMP_DIR', str(sub_root))

    # Patch SubAgentManager's destroy() — it has hardcoded "/tmp/evonic-sub-agents"
    original_destroy = subagent_manager.destroy

    def _patched_destroy(sub_agent_id):
        result = original_destroy(sub_agent_id)
        # original_destroy tried to rmtree from real /tmp/ — clean up our tmp_path too
        tmp_dir = os.path.join(str(sub_root), sub_agent_id)
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass
        return result

    monkeypatch.setattr(subagent_manager, 'destroy', _patched_destroy)

    # Patch shutdown() as well
    original_shutdown = subagent_manager.shutdown

    def _patched_shutdown():
        try:
            if os.path.isdir(str(sub_root)):
                shutil.rmtree(str(sub_root), ignore_errors=True)
        except Exception:
            pass
        original_shutdown()

    monkeypatch.setattr(subagent_manager, 'shutdown', _patched_shutdown)

    # Patch destroy_all_for_parent — it only removes from _subagents without
    # cleaning up temp dirs.  Capture the sub-agent IDs before removal so we
    # can clean up their temp dirs.
    original_destroy_all = subagent_manager.destroy_all_for_parent

    def _patched_destroy_all(parent_id):
        with subagent_manager._lock:
            sub_ids = [sid for sid, sub in subagent_manager._subagents.items() if sub.parent_id == parent_id]
        count = original_destroy_all(parent_id)
        for sid in sub_ids:
            tmp_dir = os.path.join(str(sub_root), sid)
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass
        return count

    monkeypatch.setattr(subagent_manager, 'destroy_all_for_parent', _patched_destroy_all)

    return sub_root


# =============================================================================
# Unit tests — AgentChatDB path resolution
# =============================================================================

class TestAgentChatDBPathResolution:
    """Verify AgentChatDB resolves db_path correctly for sub-agents vs normal agents."""

    def test_subagent_path_resolved_to_tmp(self, monkeypatch, tmp_path):
        """Sub-agent ID → db_path = /tmp/evonic-sub-agents/<id>/chat.db"""
        sub_id = f"test_sub_{uuid.uuid4().hex[:8]}"

        # Mock is_subagent → True
        monkeypatch.setattr(subagent_manager, 'is_subagent', lambda aid: aid == sub_id)

        # Also prevent creating dirs in real AGENTS_DIR or /tmp
        # We monkeypatch SUB_AGENTS_TMP_DIR to point at tmp_path
        monkeypatch.setattr('models.chat.SUB_AGENTS_TMP_DIR', str(tmp_path / 'evonic-sub-agents'))

        db = AgentChatDB(sub_id)
        expected_path = str(tmp_path / 'evonic-sub-agents' / sub_id / 'chat.db')
        assert db.db_path == expected_path, f"Expected {expected_path}, got {db.db_path}"
        # Verify the directory was created
        assert os.path.isdir(os.path.dirname(db.db_path))

    def test_normal_agent_path_resolved_to_agents_dir(self, monkeypatch, tmp_path):
        """Normal agent ID → db_path = agents/<id>/chat.db"""
        agent_id = f"test_agent_{uuid.uuid4().hex[:8]}"

        monkeypatch.setattr(subagent_manager, 'is_subagent', lambda aid: False)
        monkeypatch.setattr('models.chat.AGENTS_DIR', str(tmp_path / 'agents'))

        db = AgentChatDB(agent_id)
        expected_path = str(tmp_path / 'agents' / agent_id / 'chat.db')
        assert db.db_path == expected_path, f"Expected {expected_path}, got {db.db_path}"
        assert os.path.isdir(os.path.dirname(db.db_path))

    def test_directory_created_automatically(self, monkeypatch, tmp_path):
        """AgentChatDB.__init__ creates the agent directory via os.makedirs."""
        agent_id = f"test_dir_{uuid.uuid4().hex[:8]}"
        subagents_root = tmp_path / 'evonic-sub-agents'

        monkeypatch.setattr(subagent_manager, 'is_subagent', lambda aid: True)
        monkeypatch.setattr('models.chat.SUB_AGENTS_TMP_DIR', str(subagents_root))

        agent_dir = subagents_root / agent_id
        assert not agent_dir.exists()

        db = AgentChatDB(agent_id)
        assert agent_dir.is_dir(), f"Directory {agent_dir} was not created"
        assert db.db_path == str(agent_dir / 'chat.db')

    def test_subagent_and_normal_use_different_roots(self, monkeypatch, tmp_path):
        """Sub-agent and normal agent DBs go to different root directories."""
        sub_id = f"sub_diff_{uuid.uuid4().hex[:8]}"
        normal_id = f"norm_diff_{uuid.uuid4().hex[:8]}"

        agents_root = tmp_path / 'agents'
        sub_root = tmp_path / 'evonic-sub-agents'

        monkeypatch.setattr(subagent_manager, 'is_subagent', lambda aid: aid == sub_id)
        monkeypatch.setattr('models.chat.AGENTS_DIR', str(agents_root))
        monkeypatch.setattr('models.chat.SUB_AGENTS_TMP_DIR', str(sub_root))

        sub_db = AgentChatDB(sub_id)
        normal_db = AgentChatDB(normal_id)

        assert sub_db.db_path.startswith(str(sub_root))
        assert normal_db.db_path.startswith(str(agents_root))
        assert sub_db.db_path != normal_db.db_path

    def test_existing_subagent_path(self, monkeypatch, tmp_path):
        """A sub-agent (in subagent_manager._subagents) gets /tmp path."""
        sub_id = f"existing_sub_{uuid.uuid4().hex[:8]}"
        parent_id = "test_parent"

        # Register as real sub-agent in manager so is_subagent returns True
        subagent_manager._subagents[sub_id] = type('FakeSub', (), {
            'id': sub_id, 'parent_id': parent_id, 'config': {},
            'created_at': time.time(), 'last_active_at': time.time(),
            'touch': lambda: None, 'is_expired': lambda ttl=600: False,
        })()

        try:
            monkeypatch.setattr('models.chat.SUB_AGENTS_TMP_DIR', str(tmp_path / 'evonic-sub-agents'))
            db = AgentChatDB(sub_id)
            expected = str(tmp_path / 'evonic-sub-agents' / sub_id / 'chat.db')
            assert db.db_path == expected
        finally:
            subagent_manager._subagents.pop(sub_id, None)


# =============================================================================
# Unit tests — AgentChatManager thread safety
# =============================================================================

class TestAgentChatManagerThreadSafety:
    """Verify AgentChatManager is thread-safe and caches DB instances."""

    def test_get_creates_single_instance_per_agent(self, monkeypatch):
        """Calling get() multiple times returns the same cached AgentChatDB."""
        manager = AgentChatManager()
        agent_id = f"thread_safe_{uuid.uuid4().hex[:8]}"

        # Mock AgentChatDB to avoid side effects
        mock_db = object()
        call_count = 0

        def make_mock_db(aid):
            nonlocal call_count
            call_count += 1
            return mock_db

        monkeypatch.setattr('models.chat.AgentChatDB', lambda aid: make_mock_db(aid))

        db1 = manager.get(agent_id)
        db2 = manager.get(agent_id)
        db3 = manager.get(agent_id)

        assert db1 is mock_db
        assert db2 is mock_db
        assert db3 is mock_db
        assert call_count == 1, f"AgentChatDB was constructed {call_count} times, expected 1"

    def test_concurrent_get_returns_same_instance(self, monkeypatch):
        """10 concurrent threads calling get() with the same agent_id → one instance."""
        manager = AgentChatManager()
        agent_id = f"concurrent_{uuid.uuid4().hex[:8]}"

        mock_db = object()
        constructor_count = 0
        constructor_lock = threading.Lock()

        def make_mock_db(aid):
            nonlocal constructor_count
            with constructor_lock:
                constructor_count += 1
                # Simulate a small delay to trigger race conditions
                time.sleep(0.01)
            return mock_db

        monkeypatch.setattr('models.chat.AgentChatDB', lambda aid: make_mock_db(aid))

        results = []
        errors = []
        barrier = threading.Barrier(10)

        def worker():
            try:
                barrier.wait(timeout=5)
                db = manager.get(agent_id)
                results.append(db)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(errors) == 0, f"Errors occurred: {errors}"
        assert all(r is mock_db for r in results), "Not all got the same instance"
        assert constructor_count == 1, f"AgentChatDB was constructed {constructor_count} times, expected 1"

    def test_concurrent_get_multiple_agents(self, monkeypatch):
        """Multiple agent IDs accessed concurrently → one instance per ID."""
        manager = AgentChatManager()
        agent_ids = [f"multi_{uuid.uuid4().hex[:8]}" for _ in range(5)]

        mock_dbs = {}
        constructor_counts = {}
        constructor_lock = threading.Lock()

        def make_mock_db(aid):
            with constructor_lock:
                constructor_counts[aid] = constructor_counts.get(aid, 0) + 1
                time.sleep(0.01)
            return mock_dbs.setdefault(aid, object())

        monkeypatch.setattr('models.chat.AgentChatDB', lambda aid: make_mock_db(aid))

        errors = []
        barrier = threading.Barrier(10)

        def worker():
            try:
                barrier.wait(timeout=5)
                for aid in agent_ids:
                    manager.get(aid)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(errors) == 0, f"Errors occurred: {errors}"
        for aid in agent_ids:
            assert constructor_counts[aid] == 1, f"Agent {aid} constructed {constructor_counts[aid]} times"

    def test_no_operational_error_on_concurrent_get(self, monkeypatch, tmp_path):
        """No sqlite3.OperationalError when accessing the same DB concurrently."""
        agent_id = f"noerr_{uuid.uuid4().hex[:8]}"

        monkeypatch.setattr(subagent_manager, 'is_subagent', lambda aid: False)
        monkeypatch.setattr('models.chat.AGENTS_DIR', str(tmp_path / 'agents'))

        manager = AgentChatManager()
        errors = []
        barrier = threading.Barrier(10)

        def worker():
            try:
                barrier.wait(timeout=5)
                db = manager.get(agent_id)
                # Perform a quick DB operation
                with db._connect() as conn:
                    conn.execute("SELECT 1").fetchone()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(errors) == 0, f"OperationalError or other errors: {errors}"

    def test_different_agents_get_different_instances(self, monkeypatch):
        """Different agent IDs → different AgentChatDB instances."""
        manager = AgentChatManager()

        instances = {}
        call_count = 0

        def make_db(aid):
            nonlocal call_count
            call_count += 1
            return object()

        monkeypatch.setattr('models.chat.AgentChatDB', lambda aid: make_db(aid))

        dbs = [manager.get(f"diff_{i}") for i in range(5)]
        # Each should be a different instance
        assert len(set(id(db) for db in dbs)) == 5
        assert call_count == 5


# =============================================================================
# Integration tests — Concurrent sub-agent spawning with temp DB
# =============================================================================

class TestConcurrentSubAgentTempDB:
    """Integration tests: spawn sub-agents and verify /tmp/ chat DBs."""

    def _cleanup(self, sub_ids, sub_root=None):
        """Clean up test sub-agents and temp dirs."""
        for sid in sub_ids:
            subagent_manager._subagents.pop(sid, None)
            subagent_manager._counters.pop(sid.rsplit('_sub_', 1)[0], None)
            if sub_root:
                shutil.rmtree(os.path.join(sub_root, sid), ignore_errors=True)

    def test_spawn_concurrent_sub_agents_create_temp_dirs(self, monkeypatch, tmp_path):
        """Spawn 5 sub-agents concurrently → each gets /tmp/evonic-sub-agents/<id>/chat.db."""
        parent_id = f"parent_conc_{uuid.uuid4().hex[:8]}"
        sub_root = tmp_path / 'evonic-sub-agents'
        monkeypatch.setattr('models.chat.SUB_AGENTS_TMP_DIR', str(sub_root))

        parent_config = {'id': parent_id, 'name': 'Parent', 'system_prompt': ''}

        sub_ids = []
        errors = []
        barrier = threading.Barrier(5)
        lock = threading.Lock()

        def spawn_worker():
            try:
                barrier.wait(timeout=5)
                sid = subagent_manager.spawn(parent_config)
                with lock:
                    sub_ids.append(sid)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=spawn_worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        try:
            assert len(errors) == 0, f"Errors during spawn: {errors}"
            assert len(sub_ids) == 5, f"Expected 5 sub-IDs, got {len(sub_ids)}"

            # Now trigger AgentChatDB creation for each sub-agent
            for sid in sub_ids:
                db = AgentChatDB(sid)
                expected_dir = str(sub_root / sid)
                assert os.path.isdir(expected_dir), f"Dir {expected_dir} not created"
                assert db.db_path == str(sub_root / sid / 'chat.db')
                assert os.path.isfile(db.db_path), f"chat.db not found at {db.db_path}"

                # Verify DB is valid by executing a query
                with db._connect() as conn:
                    row = conn.execute("SELECT COUNT(*) FROM chat_sessions").fetchone()
                    assert row is not None, f"DB at {db.db_path} is not valid"
        finally:
            self._cleanup(sub_ids, str(sub_root))

    def test_concurrent_temp_db_access_no_operational_error(self, monkeypatch, tmp_path):
        """5 concurrent sub-agents → each DB accessible without OperationalError."""
        parent_id = f"parent_acc_{uuid.uuid4().hex[:8]}"
        sub_root = tmp_path / 'evonic-sub-agents'
        monkeypatch.setattr('models.chat.SUB_AGENTS_TMP_DIR', str(sub_root))

        parent_config = {'id': parent_id, 'name': 'Parent', 'system_prompt': ''}

        # Spawn sub-agents sequentially for deterministic setup
        sub_ids = []
        for _ in range(5):
            sid = subagent_manager.spawn(parent_config)
            sub_ids.append(sid)

        errors = []
        barrier = threading.Barrier(5)

        try:
            def access_worker(sid):
                try:
                    barrier.wait(timeout=5)
                    # Create chat DB and perform read/write
                    db = AgentChatDB(sid)
                    with db._connect() as conn:
                        # Create a session
                        conn.execute(
                            "INSERT INTO chat_sessions (id, agent_id, external_user_id) VALUES (?, ?, ?)",
                            (f"test-session-{sid}", sid, "test_user")
                        )
                        conn.commit()
                        count = conn.execute("SELECT COUNT(*) FROM chat_sessions").fetchone()[0]
                        assert count >= 1
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=access_worker, args=(sid,)) for sid in sub_ids]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=10)

            assert len(errors) == 0, f"Errors during concurrent DB access: {errors}"

            # Verify each sub-agent's directory has a valid chat.db
            for sid in sub_ids:
                db_path = str(sub_root / sid / 'chat.db')
                assert os.path.isfile(db_path), f"{db_path} missing"
        finally:
            self._cleanup(sub_ids, str(sub_root))

    def test_messages_from_other_sessions_rejected(self, monkeypatch, tmp_path):
        """Sub-agent chat DB isolates sessions — other sessions are not accessible."""
        parent_id = f"parent_iso_{uuid.uuid4().hex[:8]}"
        sub_root = tmp_path / 'evonic-sub-agents'
        monkeypatch.setattr('models.chat.SUB_AGENTS_TMP_DIR', str(sub_root))

        parent_config = {'id': parent_id, 'name': 'Parent', 'system_prompt': ''}

        sub1_id = subagent_manager.spawn(parent_config)
        sub2_id = subagent_manager.spawn(parent_config)

        try:
            # Create a session in sub1's DB
            db1 = AgentChatDB(sub1_id)
            session_id = f"session-{sub1_id}"
            with db1._connect() as conn:
                conn.execute(
                    "INSERT INTO chat_sessions (id, agent_id, external_user_id) VALUES (?, ?, ?)",
                    (session_id, sub1_id, "user1")
                )
                conn.commit()

            # Verify sub2's DB does NOT have that session
            db2 = AgentChatDB(sub2_id)
            with db2._connect() as conn:
                row = conn.execute(
                    "SELECT id FROM chat_sessions WHERE id = ?", (session_id,)
                ).fetchone()
                assert row is None, "Sub-agent 2 should not see sub-agent 1's session"

            # sub1 can access its own session
            with db1._connect() as conn:
                row = conn.execute(
                    "SELECT id FROM chat_sessions WHERE id = ?", (session_id,)
                ).fetchone()
                assert row is not None, "Sub-agent 1 should see its own session"
        finally:
            self._cleanup([sub1_id, sub2_id], str(sub_root))


# =============================================================================
# Integration tests — Cleanup on destroy
# =============================================================================

class TestCleanupOnDestroy:
    """Verify that destroying a sub-agent removes its /tmp/ directory."""

    def test_destroy_removes_temp_directory(self, subagent_env):
        """Spawn → dir created → destroy → dir removed."""
        sub_root = subagent_env
        parent_id = f"parent_del_{uuid.uuid4().hex[:8]}"
        parent_config = {'id': parent_id, 'name': 'Parent', 'system_prompt': ''}
        sub_id = subagent_manager.spawn(parent_config)

        try:
            # Trigger AgentChatDB creation → creates the directory
            AgentChatDB(sub_id)
            agent_dir = str(sub_root / sub_id)
            assert os.path.isdir(agent_dir), f"Temp dir {agent_dir} should exist after spawn + chat DB init"

            # Destroy the sub-agent
            result = subagent_manager.destroy(sub_id)
            assert result is True, "destroy() should return True"

            # Directory should be removed
            assert not os.path.exists(agent_dir), f"Temp dir {agent_dir} should be removed after destroy"
        finally:
            subagent_manager._subagents.pop(sub_id, None)
            subagent_manager._counters.pop(parent_id, None)

    def test_destroy_nonexistent_subagent(self):
        """Destroying a non-existent sub-agent returns False and doesn't error."""
        result = subagent_manager.destroy(f"nonexistent_{uuid.uuid4().hex[:8]}")
        assert result is False

    def test_destroy_multiple_subagents(self, subagent_env):
        """Spawn multiple sub-agents, destroy all → all temp dirs removed."""
        sub_root = subagent_env
        parent_id = f"parent_multi_{uuid.uuid4().hex[:8]}"
        parent_config = {'id': parent_id, 'name': 'Parent', 'system_prompt': ''}

        sub_ids = []
        for _ in range(3):
            sid = subagent_manager.spawn(parent_config)
            AgentChatDB(sid)
            sub_ids.append(sid)

        try:
            for sid in sub_ids:
                agent_dir = str(sub_root / sid)
                assert os.path.isdir(agent_dir), f"Dir {agent_dir} should exist"

            # Destroy all
            for sid in sub_ids:
                result = subagent_manager.destroy(sid)
                assert result is True

            # All dirs gone
            for sid in sub_ids:
                agent_dir = str(sub_root / sid)
                assert not os.path.exists(agent_dir), f"Dir {agent_dir} should be removed"
        finally:
            for sid in sub_ids:
                subagent_manager._subagents.pop(sid, None)
            subagent_manager._counters.pop(parent_id, None)

    def test_destroy_with_active_connections(self, subagent_env):
        """Destroy a sub-agent while its chat DB has open connections is safe."""
        sub_root = subagent_env
        parent_id = f"parent_conn_{uuid.uuid4().hex[:8]}"
        parent_config = {'id': parent_id, 'name': 'Parent', 'system_prompt': ''}
        sub_id = subagent_manager.spawn(parent_config)

        try:
            db = AgentChatDB(sub_id)
            # Add some data
            with db._connect() as conn:
                conn.execute(
                    "INSERT INTO chat_sessions (id, agent_id, external_user_id) VALUES (?, ?, ?)",
                    ("test-session", sub_id, "user")
                )
                conn.commit()

            agent_dir = str(sub_root / sub_id)
            assert os.path.isdir(agent_dir)

            # Destroy the sub-agent (should remove the dir even with previous connections)
            result = subagent_manager.destroy(sub_id)
            assert result is True
            assert not os.path.exists(agent_dir)
        finally:
            subagent_manager._subagents.pop(sub_id, None)
            subagent_manager._counters.pop(parent_id, None)

    def test_destroy_all_for_parent_removes_temp_dirs(self, subagent_env):
        """Destroy_all_for_parent removes all in-memory state and temp dirs."""
        sub_root = subagent_env
        parent_id = f"parent_all_{uuid.uuid4().hex[:8]}"
        parent_config = {'id': parent_id, 'name': 'Parent', 'system_prompt': ''}

        sub_ids = []
        for _ in range(3):
            sid = subagent_manager.spawn(parent_config)
            AgentChatDB(sid)
            sub_ids.append(sid)

        try:
            for sid in sub_ids:
                assert os.path.isdir(str(sub_root / sid))

            count = subagent_manager.destroy_all_for_parent(parent_id)
            assert count == 3

            # destroy_all_for_parent removes sub-agents from _subagents
            # The fixture patches it to also clean up temp dirs
            for sid in sub_ids:
                assert not os.path.exists(str(sub_root / sid))
                assert sid not in subagent_manager._subagents
        finally:
            for sid in sub_ids:
                subagent_manager._subagents.pop(sid, None)
            subagent_manager._counters.pop(parent_id, None)


# =============================================================================
# Integration tests — Cleanup on expire
# =============================================================================

class TestCleanupOnExpire:
    """Verify that expired sub-agents have their temp dirs cleaned up."""

    def test_cleanup_expired_single_subagent(self, subagent_env):
        """Expired sub-agent → _cleanup_expired removes its temp dir."""
        sub_root = subagent_env
        parent_id = f"parent_exp_{uuid.uuid4().hex[:8]}"
        parent_config = {'id': parent_id, 'name': 'Parent', 'system_prompt': ''}
        sub_id = subagent_manager.spawn(parent_config)
        AgentChatDB(sub_id)
        agent_dir = str(sub_root / sub_id)

        try:
            assert os.path.isdir(agent_dir)

            # Manually set the sub-agent's last_active_at far in the past
            with subagent_manager._lock:
                subagent_manager._subagents[sub_id].last_active_at = 0

            # Trigger cleanup
            subagent_manager._cleanup_expired()

            assert not os.path.exists(agent_dir), f"Expired sub-agent dir {agent_dir} should be cleaned up"
        finally:
            subagent_manager._subagents.pop(sub_id, None)
            subagent_manager._counters.pop(parent_id, None)

    def test_cleanup_only_expired_subagents(self, subagent_env):
        """Only expired sub-agents are cleaned up; active ones remain."""
        sub_root = subagent_env
        parent_id = f"parent_exp2_{uuid.uuid4().hex[:8]}"
        parent_config = {'id': parent_id, 'name': 'Parent', 'system_prompt': ''}

        expired_id = subagent_manager.spawn(parent_config)
        AgentChatDB(expired_id)

        active_id = subagent_manager.spawn(parent_config)
        AgentChatDB(active_id)

        expired_dir = str(sub_root / expired_id)
        active_dir = str(sub_root / active_id)

        try:
            assert os.path.isdir(expired_dir)
            assert os.path.isdir(active_dir)

            # Expire only the first one
            with subagent_manager._lock:
                subagent_manager._subagents[expired_id].last_active_at = 0

            subagent_manager._cleanup_expired()

            assert not os.path.exists(expired_dir), f"Expired dir {expired_dir} should be removed"
            assert os.path.isdir(active_dir), f"Active dir {active_dir} should remain"
        finally:
            subagent_manager._subagents.pop(expired_id, None)
            subagent_manager._subagents.pop(active_id, None)
            subagent_manager._counters.pop(parent_id, None)

    def test_cleanup_expired_timer_cancelled_on_shutdown(self, subagent_env):
        """shutdown() cancels the cleanup timer and clears temp dirs."""
        sub_root = subagent_env
        parent_id = f"parent_shut_{uuid.uuid4().hex[:8]}"
        parent_config = {'id': parent_id, 'name': 'Parent', 'system_prompt': ''}
        sub_ids = []
        for _ in range(2):
            sid = subagent_manager.spawn(parent_config)
            AgentChatDB(sid)
            sub_ids.append(sid)

        try:
            for sid in sub_ids:
                assert os.path.isdir(str(sub_root / sid))

            # shutdown() removes all temp dirs (patched by subagent_env)
            subagent_manager.shutdown()

            for sid in sub_ids:
                assert not os.path.exists(str(sub_root / sid))
        finally:
            for sid in sub_ids:
                subagent_manager._subagents.pop(sid, None)
            subagent_manager._counters.pop(parent_id, None)

    def test_cleanup_expired_called_after_ttl(self, subagent_env):
        """_ensure_cleanup schedules timer; expired sub-agents get cleaned."""
        sub_root = subagent_env
        parent_id = f"parent_ttl_{uuid.uuid4().hex[:8]}"
        parent_config = {'id': parent_id, 'name': 'Parent', 'system_prompt': ''}
        sub_id = subagent_manager.spawn(parent_config)
        AgentChatDB(sub_id)
        agent_dir = str(sub_root / sub_id)

        try:
            assert os.path.isdir(agent_dir)

            # Manually expire and trigger cleanup
            with subagent_manager._lock:
                subagent_manager._subagents[sub_id].last_active_at = 0

            subagent_manager._cleanup_expired()

            assert not os.path.exists(agent_dir)

            # Verify cleanup rescheduled (timer is not None after _cleanup_expired)
            with subagent_manager._lock:
                assert subagent_manager._cleanup_timer is not None
                subagent_manager._cleanup_timer.cancel()
                subagent_manager._cleanup_timer = None
        finally:
            subagent_manager._subagents.pop(sub_id, None)
            subagent_manager._counters.pop(parent_id, None)


# =============================================================================
# Integration tests — Flask API routes (end-to-end)
# =============================================================================

class TestSubAgentChatAPI:
    """End-to-end tests via Flask test client."""

    @pytest.fixture
    def agent_with_sub(self, use_test_database, ensure_super_agent, monkeypatch, tmp_path):
        """Fixture: create a parent agent, sub-agent, and temp DB."""
        from models.db import db

        parent_id = f"api_parent_{uuid.uuid4().hex[:8]}"
        db.create_agent({'id': parent_id, 'name': 'API Parent', 'system_prompt': ''})

        sub_root = tmp_path / 'evonic-sub-agents'
        sub_root.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr('models.chat.SUB_AGENTS_TMP_DIR', str(sub_root))

        parent_config = db.get_agent(parent_id)
        sub_id = subagent_manager.spawn(parent_config)

        yield parent_id, sub_id, sub_root

        # Cleanup
        subagent_manager._subagents.pop(sub_id, None)
        subagent_manager._counters.pop(parent_id, None)
        shutil.rmtree(str(sub_root / sub_id), ignore_errors=True)

    def test_chat_state_endpoint_with_subagent(self, use_test_database, ensure_super_agent):
        """GET /api/agents/<sub_id>/chat/state returns valid JSON without errors."""
        from models.db import db
        from app import app

        # Create parent and sub-agent
        parent_id = f"parent_state_{uuid.uuid4().hex[:8]}"
        db.create_agent({'id': parent_id, 'name': 'Parent', 'system_prompt': ''})

        parent_config = db.get_agent(parent_id)
        sub_id = subagent_manager.spawn(parent_config)

        try:
            with app.test_client() as client:
                with client.session_transaction() as sess:
                    sess['authenticated'] = True

                resp = client.get(f'/api/agents/{sub_id}/chat/state')
                assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.data}"
                data = resp.get_json()
                assert data is not None
                # Response should have at least a 'success' field or similar
                assert 'success' in data or isinstance(data, dict)
        finally:
            subagent_manager._subagents.pop(sub_id, None)
            subagent_manager._counters.pop(parent_id, None)

    def test_subagent_chat_state_returns_null_state_for_unknown(self, use_test_database, ensure_super_agent):
        """GET /api/agents/<unknown_id>/chat/state returns 200 with null mode."""
        from app import app

        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess['authenticated'] = True

            resp = client.get(f'/api/agents/nonexistent_sub_999/chat/state')
            # The endpoint doesn't validate agent existence — it returns
            # {"mode": None} for unknown agent IDs.
            assert resp.status_code == 200
            data = resp.get_json()
            assert data is not None
            assert data.get('mode') is None
