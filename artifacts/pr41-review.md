# PR #41 Review: fix(agents) — enforce sandbox disabled on remote and cloud workplaces

**Author:** DeryFerd  
**Branch:** `fix/agent-sandbox-workplace-enforcement` → `main`  
**Reviewer:** Richard (Robin Syihab's agent)  
**Date:** 2026-05-16  

---

## Summary

Two files touched (+76 / −11 lines). A new helper `_apply_sandbox_workplace_policy()` replaces inline sandbox checks in `api_create_agent` and `api_update_agent`. The fix ensures `sandbox_enabled` is always forced to `0` for remote and cloud workplaces — not just when the client sends a truthy value.

---

## What Changed

### `routes/agents.py` — new helper + unified call sites

```python
def _apply_sandbox_workplace_policy(agent_data: dict, workplace_id: Optional[str]) -> None:
    """Docker sandbox is only supported on local workplaces."""
    if not workplace_id:
        return
    workplace = db.get_workplace(workplace_id)
    if workplace and workplace.get('type') in ('remote', 'cloud'):
        agent_data['sandbox_enabled'] = 0
```

**Create endpoint** — old code:
```python
if data.get('sandbox_enabled') and data.get('workplace_id'):   # ← skips when falsy
    workplace = db.get_workplace(data['workplace_id'])
    if workplace and workplace.get('type') in ('remote', 'cloud'):
        data['sandbox_enabled'] = 0
```

→ Replaced with `_apply_sandbox_workplace_policy(data, data.get('workplace_id'))`

**Update endpoint** — old code:
```python
if data.get('sandbox_enabled') and target_workplace_id:       # ← same falsy skip
    workplace = db.get_workplace(target_workplace_id)
    if workplace and workplace.get('type') in ('remote', 'cloud'):
        del data['sandbox_enabled']   # ← BUG: removes key, stale DB value persists
```

→ Replaced with `_apply_sandbox_workplace_policy(data, target_workplace_id)`

### `unit_tests/test_agent_sandbox_workplace_validation.py` — new, +64 lines

Seven test cases exercising the helper in isolation with `unittest.mock.patch`.

---

## Bugs Fixed

| # | Location | Bug | Impact |
|---|----------|-----|--------|
| 1 | `api_create_agent` | `if data.get('sandbox_enabled')` — when the client sends `sandbox_enabled=0` the check is skipped entirely. | A remote/cloud agent could be created with `sandbox_enabled` left as whatever the client sent or whatever default the DB layer applies. |
| 2 | `api_update_agent` | Same falsy guard **plus** `del data['sandbox_enabled']` instead of `data['sandbox_enabled'] = 0`. | On a partial update that doesn't include the sandbox field, the old (potentially stale) value in SQLite stays. The UI toggle feels ineffective (issue #35). |

Both are fixed: the helper is always called regardless of the current sandbox value, and it always writes `0` (never deletes the key).

---

## Test Coverage

| Test case | Workplace | Input | Expected | Verdict |
|-----------|-----------|-------|----------|---------|
| `test_local_workplace_allows_sandbox_on` | local | `sandbox_enabled=1` | stays `1` | ✅ |
| `test_local_workplace_allows_sandbox_off` | local | `sandbox_enabled=0` | stays `0` | ✅ |
| `test_remote_workplace_forces_sandbox_off_when_enabling` | remote | `sandbox_enabled=1` | forced `0` | ✅ |
| `test_remote_workplace_forces_sandbox_off_when_already_disabled` | remote | `sandbox_enabled=0` | stays `0` | ✅ |
| `test_cloud_workplace_forces_sandbox_off` | cloud | `sandbox_enabled=1` | forced `0` | ✅ |
| `test_no_workplace_id_leaves_data_unchanged` | (none) | `sandbox_enabled=1` | stays `1`, `get_workplace` not called | ✅ |

**What's covered:**
- All three workplace types (local, remote, cloud)
- Both `sandbox_enabled=0` and `sandbox_enabled=1` on local/remote
- Missing `workplace_id` (graceful no-op)
- Mock assertion that `get_workplace` is never called when `workplace_id` is `None`

**What's missing (minor):**
- No integration test that hits the actual API endpoints. The helper is tested in isolation — which is fine for a unit-level fix, but a follow-up could add a request-level test.
- The case where `workplace_id` is provided but `db.get_workplace` returns `None` (unknown workplace) — the helper silently passes. That's reasonable (it means the workplace was deleted or doesn't exist), but worth noting.

---

## Regression Risk

**Low.** The helper is a strict superset of the old behavior:

- **Local workplace:** old code didn't touch `sandbox_enabled` when `workplace.get('type')` is `'local'`. The helper also doesn't touch it (the `in ('remote', 'cloud')` check is identical).
- **No `workplace_id`:** old code skipped the block. Helper returns early. Same behavior.
- **Remote/cloud, sandbox off:** old code skipped (falsy guard bug). New code explicitly sets to `0`. This is the intended fix, and `0` was already the desired value.
- **Remote/cloud, sandbox on:** old code set to `0` (create) or deleted the key (update). New code sets to `0` in both paths. Safer.

No behavior change for local workplaces. No change for agents without a workplace.

---

## Dashboard / Setup Wizard

The setup wizard in `routes/dashboard.py:api_setup()` creates the super agent with `workspace=config.BASE_DIR` (local path). It does not pass a `workplace_id`, so the new helper would be a no-op if called. The author correctly left it out of scope — but if the wizard ever gains workplace selection, the same helper should be called there.

---

## Verdict

✅ **Approve.** Clean fix for a real bug (issue #35). The helper is small, well-scoped, and comprehensively tested at the unit level. The two old bugs are gone, local workplaces are unchanged, and the new code is easier to audit than the inline blocks it replaces.

**Suggestions (non-blocking):**
1. Add a request-level integration test for create/update with a remote workplace.
2. If the setup wizard ever grows workplace selection, call the same helper.

---

Best,  
Richard  
--  
Robin Syihab's agent.
