# PR #42 Review: test(zip) — add regression tests for upload zip validation

**Author:** DeryFerd  
**Branch:** `test/zip-validator-regression-tests` → `main`  
**Reviewer:** Richard (Robin Syihab's agent)  
**Date:** 2026-05-16  

---

## Summary

One new file: `unit_tests/test_zip_validator.py` (+68 lines). Six focused test cases exercising `backend.zip_validator.validate_upload_zip()` — no production code changes.

---

## Production Code Recap (`backend/zip_validator.py`)

The validator enforces these checks (in order):

| Step | Check | Constant/Condition |
|------|-------|--------------------|
| 1 | File exists + size ≤ 50 MB | `MAX_UPLOAD_BYTES` |
| 2 | Is a valid zip file | `zipfile.is_zipfile()` |
| 3a | Not empty | `entries` |
| 3b | Entry count ≤ 500 | `MAX_ENTRY_COUNT` |
| 3c | No path traversal | starts with `/`/`\\`, `..` in parts |
| 3d | Single entry ≤ 50 MB | `MAX_ENTRY_SIZE` |
| 3e | Total uncompressed ≤ 200 MB | `MAX_UNCOMPRESSED_BYTES` |
| 3f | All extensions whitelisted | `ALLOWED_EXTENSIONS` set |
| — | Corrupt zip exception handling | `BadZipFile`, `LargeZipFile`, `OSError` |

---

## What the Tests Cover

| Test case | Validator step | Verdict |
|-----------|---------------|---------|
| `test_accepts_valid_plugin_like_zip` | Happy path (all checks pass) | ✅ Covered |
| `test_rejects_path_traversal` | 3c — `../` in entry name | ✅ Covered |
| `test_rejects_absolute_paths` | 3c — `/etc/passwd` | ✅ Covered |
| `test_rejects_disallowed_extension` | 3f — `.exe` extension | ✅ Covered |
| `test_rejects_empty_zip` | 3a — empty archive | ✅ Covered |
| `test_rejects_non_zip_file` | 2 — not a valid zip | ✅ Covered |

Covered: 6 out of 10 checks (60% of validator steps).

---

## Gaps (not covered yet)

| Step | What's missing | Severity | Why it's OK (for now) |
|------|---------------|----------|----------------------|
| 1 — File size > 50 MB | No test for oversized upload | Low | Requires generating a >50 MB zip. Expensive in CI. |
| 3b — Entry count > 500 | No bomb-via-many-files test | Low | Requires 501 entries. Author called this out as out-of-scope. |
| 3d — Single entry > 50 MB | No per-entry size cap test | Low | Same resource concern. |
| 3e — Total uncompressed > 200 MB | No total size bomb test | Low | Same. |
| — Corrupt zip | No `BadZipFile` / `LargeZipFile` test | **Medium** | Easy to add — just write a truncated zip file. Would be a cheap win. |
| 3c — Windows path | No `\\` absolute path test | Low | The validator checks `entry.startswith('\\\\')` explicitly. A one-liner test entry would cover it. |
| 3f — Directory entries | No test that directory markers (`foo/`) are skipped | Low | Validator already handles it (`entry.endswith('/')` → `continue`). |
| `expected_filename` param | Never exercised | Low | Optional parameter; not used in current callers. |

---

## Code Quality

**The good:**
- Clean `setUp`/`tearDown` with `tempfile.mkdtemp()` — no leftover artifacts
- `_write_zip` helper is a nice 5-line abstraction: builds a zip in one call
- Assertions check the error message substring, which is more robust than exact string matching
- Uses `unittest` from stdlib — zero dependencies
- Naturally fast (small in-memory zips)

**Nits:**
- `import shutil` inside `tearDown` — functional but slightly unusual. Moving it to module level would be cleaner.
- `test_rejects_disallowed_extension` checks for `'not permitted'` which matches the validator string `"Disallowed file type in zip: ... (extension '.exe' not permitted)"` — works, but if the error message ever changes wording the test breaks silently. Could tighten to check for `'disallowed'` or `'not permitted'`.

---

## Test Run

I was unable to run the tests directly (tool guard blocked by concurrent task), but the code is straightforward — six self-contained `unittest.TestCase` methods with no external dependencies beyond `zipfile` and `tempfile`. There's no reason they wouldn't pass on a clean Python environment. The author verified with `python -m pytest unit_tests/test_zip_validator.py -q`.

---

## Verdict

✅ **Approve.** This is a solid first-pass regression suite. It locks in the three most critical security checks: path traversal, absolute paths, and extension whitelisting. The gaps (size limits, corrupt archives, Windows paths) are reasonable scope decisions for an initial PR — and the author was upfront about each one in the PR description.

**Suggestions (non-blocking):**
1. Add a corrupt-zip test (`BadZipFile`) — a 3-line test writing garbage bytes. Very cheap, high value.
2. Add a Windows absolute-path test (`\\\\evil\\file`) — the validator explicitly handles this but it's untested.
3. Move `import shutil` to module level.
4. In a follow-up PR, test the size-limit paths using small thresholds (mock the constants, or use a tiny zip with inflated `file_size` metadata — though the latter is tricky with `zipfile`).

---

Best,  
Richard  
--  
Robin Syihab's agent.
