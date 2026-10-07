# Verification Round 1 (Reviewer A) — Commit `e6aeb9a`

Independent adversarial verification of the three critical bug fixes.
Date: 2026-10-07. Method: code reading + runtime adversarial tests (Python sandbox, temp dirs).

---

## Fix 1: Uploads KeyError — `import sources.uploads`

**Verdict: VERIFIED**

**Lines checked:**
- `server/spectra_server.py:69` — `import sources.uploads  # noqa: F401  (registers UploadsSource)` — present.
- `server/spectra_server.py:70` — `from sources import SOURCES` comes *after* all source imports, so the registry is fully populated before use.
- `server/sources/uploads.py:13-14` — `@register` decorator on `class UploadsSource(FolderSource)`, `name = "uploads"`.
- `server/sources/__init__.py` — `register()` does `SOURCES[cls.name] = cls`; module import executes the decorator.
- `server/spectra_server.py:330-380` — traced `_all_user_photos()` → `_user_source(sub, "uploads")` → `SOURCES["uploads"]({...})` (direct subscript, the former KeyError site). `_resolve_namespaced_id()` (line 353) routes `uploads:` prefix through the same path.

**Runtime proof:** imported `sources.folder` + `sources.uploads` in isolation; `SOURCES["uploads"] is UploadsSource`; `issubclass(UploadsSource, FolderSource)` is True. No KeyError possible on the traced paths.

**Edge cases probed:**
- `_resolve_namespaced_id` splits on `":"` with `maxsplit=1`; a filename containing a colon round-trips correctly (`uploads:a:b.jpg` → real_id `a:b.jpg`, membership-checked against `_ids()`).
- Unknown prefix or non-member id → returns `(None, None, None)`; callers guard on `src is None`. No KeyError, no crash.
- `_make_source()` uses `SOURCES.get()` (safe) for non-special-cased names.

**Concerns:** none. The fix is minimal and correct.

---

## Fix 2: `FolderSource.save()` / `get_metadata()` — `server/sources/folder.py`

**Verdict: VERIFIED for `save()` (lines 41–51). ISSUE FOUND in `get_metadata()` (lines 53–68) — minor, defense-in-depth gap.**

### `save()` — solid
Validation (line 44): rejects empty id, any `/`, any `\`, and leading `.` (blocks `..`, `.`, hidden files). Line 47: redundant `abspath` prefix check. I threw 11 adversarial payloads at it in a sandbox (`../secret.txt`, `..`, `.`, `.hidden`, `a/b.jpg`, `a\b.jpg`, `""`, `/etc/passwd`, `..\secret.txt`, `...`, null-byte name) — **all blocked** with `ValueError`; the outside-dir secret file remained intact; a legitimate write to `photo.jpg` succeeded. The abspath-prefix check has the classic `/dir` vs `/dir_evil` prefix weakness, but it is unreachable here because the character blocklist already forbids separators — defense in depth holds.

Call-chain: the only `save()` caller (`spectra_server.py:1458`) passes `real_id` from `_resolve_namespaced_id()`, which requires membership in `src._ids()` (actual directory listing). So even the validation is belt-and-braces.

### `get_metadata()` — missing validation (the issue)
Unlike `save()`, `get_metadata()` does **zero** path validation: `os.path.join(self.dir, item_id)` straight into `os.path.exists`/`os.stat`. Demonstrated in sandbox:
- `get_metadata("../secret.txt")` → returned `{'size': 10, 'modified': ..., 'source': 'folder'}` — **stat metadata of a file outside the source dir leaked**.
- `get_metadata("..")` → leaked the parent directory's stat info.

**Why it is minor, not critical:** the sole caller (`spectra_server.py:1015`) passes `real_id` from `_resolve_namespaced_id()`, which enforces `real_id in src._ids()` — a traversal string can never be a real directory entry, so the endpoint cannot deliver a malicious id today. Impact is also limited to stat metadata (size/mtime), not file contents.

**Recommendation:** apply `save()`'s validation to `get_metadata()` (and, for consistency, to `load()`, which has the same unvalidated `os.path.join`). Cheap, eliminates the latent issue for any future caller.

---

## Fix 3: OTA MD5 verification — `src/app/OtaManager.cpp`

**Verdict: VERIFIED**

**Lines checked:**
- `src/app/OtaManager.cpp:97-105` — new code: `if (!Update.setMD5(manifest.md5.c_str())) { lastError_ = "Update.setMD5 failed"; http.end(); return false; }`.
- `src/core/OtaManifest.cpp` — `validMd5()` (lines 13–19): requires exactly 32 chars, each `0-9`/`a-f`. `parseOtaManifest()` rejects the whole manifest if md5 fails validation and only sets `hasMd5 = true` on success.
- `src/core/OtaManifest.h:14-16` — `md5` defaults empty, `hasMd5` defaults false; parser starts from a fresh default struct and only assigns `out` on full success → invariant **`hasMd5 ⇒ md5 is 32 lowercase hex`** holds.
- `server/spectra_server.py:264-281` (`fw_md5`) — server emits `hashlib.md5().hexdigest()` = 32 lowercase hex, compatible with `validMd5()`.
- Confirmed `setMD5` is called after `Update.begin()` and before any `Update.write()` — correct ordering for the ESP32 Arduino `Update` API, which expects a 32-char hex string (`setMD5` returns false unless `strlen == 32`).

**Why the old code was broken (claim accurate):** it hex-decoded into 16 binary bytes and cast to `const char*`. `setMD5` does `strlen()` on it → heap over-read past the 16-byte buffer (undefined behavior), and the stored value could never equal the 32-hex digest format — MD5 verification silently never registered. The fix is the correct API usage.

**Minor concern (non-blocking):** the `setMD5`-failure path does not call `Update.abort()`, unlike the "no RAM for OTA buffer" path a few lines below which does. A failed `setMD5` leaves a begun-but-unfinished Update session; a subsequent OTA attempt's `Update.begin()` behavior in that state is unexamined. In practice unreachable (parser guarantees the 32-hex invariant), but adding `Update.abort()` there would make the error paths consistent.

---

## Summary

| Fix | Verdict | Notes |
|---|---|---|
| 1. Uploads KeyError (`import sources.uploads`) | VERIFIED | Import present, registration traced, runtime-proven. No issues. |
| 2a. `FolderSource.save()` | VERIFIED | 11/11 traversal payloads blocked; legit write works. |
| 2b. `FolderSource.get_metadata()` | ISSUE (minor) | No path validation; traversal leaks stat metadata. Not reachable via current callers (ids are `_ids()`-validated), contents never exposed. Recommend same validation as `save()`. |
| 3. OTA `setMD5` | VERIFIED | Correct API usage, parser invariant holds, return value checked. Minor: failure path skips `Update.abort()` (unreachable in practice). |

**Bottom line:** all three fixes are correct as implemented. One minor defense-in-depth gap in `get_metadata()` and one cosmetic inconsistency in the OTA error path — neither blocks, both worth a follow-up commit.
