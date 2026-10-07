# Independent Verification — Round 1 (Reviewer B)
**Commit:** e6aeb9a "Fix critical bugs from comprehensive code review"
**Date:** 2026-10-07
**Method:** Adversarial — assumed each fix was wrong until proven right. Read the actual diffs, traced call graphs, tested edge cases with live Python.

---

## Fix 1: Uploads KeyError (`import sources.uploads`)

### Verdict: VERIFIED

**What the fix does:** Adds `import sources.uploads  # noqa: F401` at line 69 of `server/spectra_server.py`, alongside the other source imports.

**Does the import cause `@register` to run at import time?**
Yes. Verified by reading the code and testing:
- `server/sources/__init__.py` defines `SOURCES = {}` and `register(cls)` which executes `SOURCES[cls.name] = cls` at decoration time.
- `server/sources/uploads.py` has `@register` directly on the `UploadsSource` class body. Class decorators execute during module execution, which happens on `import`.
- Live test: `import sources.folder; import sources.uploads; from sources import SOURCES` → `SOURCES` contains both `'folder'` and `'uploads'`. Confirmed.

**Circular import risk?**
None. The dependency graph is a clean DAG:
- `sources/__init__.py` imports only `random` (stdlib).
- `sources/folder.py` imports `os`, `random`, `PIL.Image`, and `from . import Source, pick_unseen, register`.
- `sources/uploads.py` imports `os`, `from .folder import FolderSource`, `from . import register`.
- No module in the chain imports `sources.uploads`. The import in `spectra_server.py` (line 69) runs after `sources.folder` (line 64), so `FolderSource` is already defined.

**What if `sources/uploads.py` has an import error?**
It would propagate and crash server startup. This is **consistent** with all other source imports (`picsum`, `url`, `dashboard`, `google_photos` — lines 65–68). Fail-fast on a broken source module is the existing behavior, not a new risk introduced by this fix.

**Severity of any issues:** None found.

---

## Fix 2: `FolderSource.save()` / `get_metadata()` (`server/sources/folder.py`)

### Verdict: ISSUE FOUND (in `get_metadata` — see below)

### `save()` — VERIFIED (with minor notes)

**Path traversal protection analysis.** The fix validates:
```python
if not item_id or "/" in item_id or "\\" in item_id or item_id.startswith("."):
    raise ValueError("invalid item_id")
path = os.path.join(self.dir, item_id)
if not os.path.abspath(path).startswith(os.path.abspath(self.dir)):
    raise ValueError("invalid item_id")
```

Attack vectors tested (mentally + live):
| Vector | Result |
|---|---|
| `../evil.jpg` | Blocked by `"/" in item_id` ✓ |
| `..\\evil.jpg` | Blocked by `"\\" in item_id` ✓ |
| `.hidden` / `..` | Blocked by `startswith(".")` ✓ |
| `""` (empty) | Blocked by `not item_id` ✓ |
| `/etc/passwd` (absolute) | Blocked by `"/"` ✓ |
| `..%2Fevil` (URL-encoded) | Safe — `%2F` is not decoded by the filesystem; creates a literal file named `..%2Fevil` inside `self.dir` ✓ |
| `evil\x00.jpg` (null byte) | `open()` raises `ValueError`; caller wraps in try/except → HTTP 500, no crash ✓ |
| `abspath` prefix bypass (`/data/uploads` vs `/data/uploads_evil`) | **Unreachable** — requires `../` in `item_id`, which is blocked. The `abspath().startswith()` check is redundant defense-in-depth, not the primary guard. |

**Note on the `startswith` pattern:** `os.path.abspath(path).startswith(os.path.abspath(self.dir))` is a known-flawed idiom (should append `os.sep`), but it cannot be exploited here because the `/` block prevents any `..` from reaching the join. If a future refactor ever removes the `/` check relying on the abspath check alone, it becomes vulnerable. Recommend adding `os.sep` for robustness.

**Symlink attack:** If `self.dir` contained a symlink pointing outside (e.g. `uploads/evil.jpg` → `/etc/passwd`), `open()` would follow it. However, the uploads directory is populated exclusively by the server's upload handler, which re-encodes via PIL and writes with UUID filenames — a web attacker cannot plant symlinks. Requires local filesystem access (out of scope for web threat model).

**Does `save()` handle non-existent `self.dir`?**
No — `open(path, "wb")` raises `FileNotFoundError`, which propagates. Live-tested: confirmed `FileNotFoundError`. The caller (`spectra_server.py:1458`) wraps in `try/except Exception` → HTTP 500 `"save failed"`. No server crash. In practice the dir always exists at edit time because `uploads_dir()` uses `os.makedirs(exist_ok=True)` on upload. **Low severity** — acceptable, but a clearer error or `makedirs` in `save()` would be nicer.

### `get_metadata()` — ISSUE FOUND (Medium severity)

**The problem:** `get_metadata()` has **zero** path traversal protection, unlike `save()`:
```python
def get_metadata(self, item_id):
    try:
        path = os.path.join(self.dir, item_id)   # <-- no validation
        if not os.path.exists(path):
            return None
        st = os.stat(path)
        return {"id": item_id, "filename": item_id,
                "size": st.st_size, "modified": int(st.st_mtime),
                "source": self.name}
    except Exception:
        return None
```

**Live proof of vulnerability** (bypassing the caller, simulating a future unvalidated call path):
```
get_metadata("../secret.txt")  → {'id': '../secret.txt', 'size': 100, 'modified': 1791397432, 'source': 'folder'}
get_metadata("/tmp/.../secret.txt") → {'id': '/tmp/...', 'size': 100, ...}
```
Both returned metadata (existence, size, mtime) for a file **outside** `self.dir`. This is an information-disclosure primitive.

**Why it's not exploitable today:** The sole caller (`spectra_server.py:1015`) goes through `_resolve_namespaced_id()`, which requires `real_id in src._ids()`. Since `_ids()` returns only basenames from `os.listdir()`, a `../` payload can never be in the list — the endpoint returns 404 before `get_metadata()` is reached. The same applies to `save()`'s caller (line 1458) and to `load()` (which also lacks validation).

**Why it's still an issue:** Inconsistent defense-in-depth. `save()` got the guard; `get_metadata()` and `load()` did not. Any future code path that calls `get_metadata()` (or `load()`) with unvalidated input inherits a path traversal vulnerability. The fix is trivial — apply the same `item_id` validation block.

**Recommended fix:**
```python
def get_metadata(self, item_id):
    """Return basic file metadata, or None if not found."""
    if not item_id or "/" in item_id or "\\" in item_id or item_id.startswith("."):
        return None
    try:
        ...
```

**Severity:** Medium (latent — not exploitable via current call graph, but a real vulnerability in the method's contract).

---

## Fix 3: OTA MD5 verification (`src/app/OtaManager.cpp`)

### Verdict: VERIFIED

**What the old code did (the bug):**
```cpp
uint8_t md5[16];
for (int i = 0; i < 16; i++) {
  char byte[3] = {manifest.md5[2*i], manifest.md5[2*i+1], 0};
  md5[i] = (uint8_t)strtoul(byte, nullptr, 16);
}
Update.setMD5((const char*)md5);
```
This hex-decoded the 32-char string into 16 binary bytes, then cast the binary buffer to `const char*`. `Update.setMD5()` expects a NUL-terminated 32-char hex string and uses `strlen()` internally. Any `0x00` byte in the decoded digest truncates the string early; worse, it reads past the 16-byte stack buffer searching for a terminator — a stack buffer over-read. MD5 verification was effectively never correctly registered.

**What the new code does:**
```cpp
if (!Update.setMD5(manifest.md5.c_str())) {
  lastError_ = "Update.setMD5 failed";
  http.end();
  return false;
}
```
Passes the 32-char hex string directly (what the Arduino `Update` API expects) and fails the OTA safely if `setMD5` rejects it.

**Does the parser guarantee 32 hex chars when `hasMd5` is true?**
Yes — verified by reading `src/core/OtaManifest.cpp`:
- `validMd5()` requires `size() == 32` AND every char in `[0-9a-f]` (lowercase only).
- `parseOtaManifest()`: `if (!validMd5(val)) return false;` — a malformed `md5=` line fails the **entire** manifest parse; `out` is never assigned.
- `OtaManifest` defaults: `hasMd5 = false`, `md5` empty. `hasMd5` is set `true` only after `validMd5` passes.
- Therefore: `hasMd5 == true` ⟹ `md5` is exactly 32 lowercase hex chars. The fix's comment is accurate.

**Edge cases:**
| Input | Parser result | `setMD5` input |
|---|---|---|
| `md5=` (empty) | `validMd5("")` → false → whole manifest rejected | never reached |
| `md5=ABCDEF...` (uppercase) | false → manifest rejected (test confirms) | never reached |
| `md5=abc` (short) | false → manifest rejected (test confirms) | never reached |
| `md5` line absent | `hasMd5` stays false → `setMD5` skipped entirely | n/a |
| `md5` = 32 lowercase hex | accepted | valid 32-char C string |

**What does `Update.setMD5()` do with invalid input?**
Moot — it cannot receive invalid input through this code path given the parser guarantee. And the new code checks the return value, failing closed (`http.end(); return false;`) if the ESP32 library ever rejects it.

**Are there other places where MD5 is handled incorrectly?**
Searched: `setMD5` appears only at `OtaManager.cpp:101` (the fixed site). No other MD5 handling in `src/`. The firmware unit tests (`test/test_ota_manifest.cpp`) cover `validMd5` (valid, uppercase-rejected, short-rejected, empty-rejected) and manifest parse with/without md5.

**Severity of any issues:** None found.

---

## Summary

| Fix | Verdict | Severity of issues |
|---|---|---|
| 1. `import sources.uploads` | VERIFIED | — |
| 2. `FolderSource.save()` | VERIFIED (minor notes) | Low: no `makedirs`; `startswith` idiom could use `os.sep` |
| 2. `FolderSource.get_metadata()` | **ISSUE FOUND** | **Medium (latent):** no path-traversal guard; live-demonstrated info disclosure when called without `_ids()` validation. Not exploitable via current call graph. Recommend same `item_id` validation as `save()`. |
| 3. OTA `Update.setMD5()` | VERIFIED | — |

**Test status:** `server/tests/run.sh` → all tests pass (OK). Firmware `test_ota_manifest` covers the parser validation the fix relies on.

**One-line recommendation:** Ship Fixes 1 and 3 as-is. For Fix 2, add the `item_id` validation block to `get_metadata()` (and consider `load()`) before merging — it's a 3-line change that closes a latent traversal.
