# FolioFrame Testing Gap Analysis

**Date:** 2026-10-07
**Scope:** `server/` (Python) + `src/`/`test/` (firmware C++)
**Existing:** 116 server tests passing, 7 firmware core test files passing

---

## 1. Coverage Map

### 1.1 Server — What's Tested

| Area | Test File | Coverage |
|------|-----------|----------|
| Google OAuth token verification | test_auth_devices.py | ✅ Strong: forged/expired/wrong-aud/wrong-iss/unverified-email/allowlist |
| Sessions (create/verify/expire/logout) | test_auth_devices.py | ✅ Good: round-trip, tamper, expiry, logout |
| Device registry (claim codes, pairing, tokens) | test_auth_devices.py | ✅ Good: format, poll-before-approve, token-once, bad-id, hash-never-plaintext, one-device-one-user, unpair-revokes, expired-code, rate-limit, heartbeat-sanitize, truncation, self-unpair |
| HTTP auth gating (welcome public, console gated) | test_auth_devices.py | ✅ Good |
| CSRF enforcement, oversized body/JSON rejection | test_auth_devices.py | ✅ Good |
| Full pairing + frame flow (HTTP integration) | test_auth_devices.py | ✅ `test_full_pairing_and_frame_flow` — register → claim → poll → frame fetch |
| Flash page, manifest, binaries, ESP web tools | test_auth_devices.py | ✅ Good |
| OTA version endpoint | test_auth_devices.py | ✅ Good |
| Cross-user device isolation | test_auth_devices.py | ✅ Good |
| Upload override + clear (per-device pinned photo) | test_auth_devices.py | ✅ `test_upload_override_and_clear` |
| Google Photos OAuth (auth URL, token exchange, refresh) | test_google_photos.py | ✅ Good |
| Picker API client (session create, pagination, download) | test_google_photos.py | ✅ Good, incl. regression for Picker API host |
| PickFlow import (skip video, metadata sidecar, cleanup) | test_google_photos.py | ✅ Good |
| GooglePhotosSource (cache scan, load, empty) | test_google_photos.py | ✅ Good |
| Image pipeline (pack, dither, cover, etag, preview, EXIF) | test_pipeline.py | ✅ Good (updated for epaper-dithering) |
| Blob stores (local + GCS fake) | test_firebase_backends.py | ✅ Good, incl. path traversal |
| Token stores (file + Firestore fake) | test_firebase_backends.py | ✅ Good |
| Firestore store (CRUD, expired sessions) | test_firebase_backends.py | ✅ Good |
| Quiet hours, pick_unseen, FolderSource, DashboardSource, PicsumSource, UrlSource | test_server_logic.py | ✅ Good |

### 1.2 Server — What's NOT Tested

| Area | File:Function | Risk |
|------|---------------|------|
| **Unified photo library** (`_all_photos`, `_resolve_namespaced_id`) | spectra_server.py:330-370 | 🔴 **CRITICAL** — zero tests; deployed 2026-10-07 |
| **Upload flow end-to-end** (POST /api/uploads → GET /api/uploads → file serve) | spectra_server.py (do_POST:1364, do_GET:1151,1166) | 🔴 **CRITICAL** — zero tests; the user's primary workflow |
| **Edit uploaded photo** (`src.save()` on UploadsSource) | spectra_server.py:1423 + sources/uploads.py | 🔴 **CRITICAL BUG** (see §2.1) |
| **Photo metadata for uploads** (`src.get_metadata()` on UploadsSource) | spectra_server.py:1013 + sources/uploads.py | 🔴 **CRITICAL BUG** (see §2.2) |
| **Photo edit endpoint** (`/api/photos/{id}/edit`) | spectra_server.py:1423 | 🟡 Partial — `test_edit_replaces_cached_photo` covers Google Photos only |
| **Frame push flow** (select library photo → pin to frame) | No such endpoint exists? | 🔴 **CRITICAL** — verify the actual UX path (see §2.3) |
| **Device frame rendering** (`device_frame`, `_rotate_device`) | spectra_server.py:489, 445 | 🟡 Only covered indirectly via `test_full_pairing_and_frame_flow` |
| **`/api/next`, `/api/source`** (rotation control) | spectra_server.py:1464, 1477 | 🟡 No tests |
| **`/api/devices` list, `/api/devices/{id}/preview`** | spectra_server.py:951, 1040 | 🟡 No tests |
| **`/api/account`, `/api/session`** | spectra_server.py:923, 933 | 🟡 No tests |
| **`/api/gphotos/pick`, `/disconnect`, `/status`** | spectra_server.py:1404, 1415, 1189 | 🟡 No HTTP-level tests (unit-tested at client level) |
| **DELETE /api/uploads/{name}** | spectra_server.py:1518 | 🟡 No tests |
| **`/api/auth/token`, `/api/auth/logout`** | spectra_server.py:1214, 1240 | 🟡 Partial — logout tested at AuthManager level, not HTTP |
| **`/v1/device/*` endpoints** (register, claim, status, unpair) | spectra_server.py:1249-1296 | 🟡 Partial — covered in integration flow, not error paths |
| **Error paths** (404s, 400s, 500s, malformed input) | Throughout | 🟡 Sparse — happy paths dominate |
| **UploadsSource class itself** | sources/uploads.py (27 lines) | 🟡 No direct tests (inherits FolderSource which is tested) |
| **DashboardSource rendering** | sources/dashboard.py | 🟢 Tested (size/mode only) |
| **PicsumSource/UrlSource network paths** | sources/picsum.py, url.py | 🟢 Partial — describe() tested, fetch not (correctly avoided) |

### 1.3 Firmware — What's Tested

| Module | Test File | Coverage |
|--------|-----------|----------|
| BatteryCurve | test/test_battery.cpp | ✅ |
| JsonLite | test/test_json_lite.cpp | ✅ |
| OtaManifest | test/test_ota_manifest.cpp | ✅ |
| QuietHours | test/test_quiet_hours.cpp | ✅ |
| Scheduler | test/test_scheduler.cpp | ✅ |
| UrlTemplate | test/test_url_template.cpp | ✅ |
| Validate | test/test_validate.cpp | ✅ |

All 7 `src/core/` modules have host-native unit tests (g++, no Arduino deps). This is good.

### 1.4 Firmware — What's NOT Tested

| Area | Files | Risk |
|------|-------|------|
| **All of `src/app/`** (Config, DeviceClient, FrameFetcher, OtaManager, Portal, PowerManager, TimeSync) | 7 .cpp files, ~2000+ lines | 🔴 **CRITICAL** — zero tests; this is where the boot-loop bugs lived |
| **All of `src/hal/`** (EE02Board, Gdeb0709e01Panel) | 4 files | 🟡 Hardware-dependent, but interfaces could be mocked |
| **All of `src/ui/`** (StatusScreen, StatusBadge) | 4 files | 🟡 The "UI is crap" complaints — no way to catch regressions |
| **4bpp frame parsing** (`drawPacked4bpp`) | firmware display code | 🔴 **CRITICAL** — the garbled-photo bug was here; no test would catch it |
| **Claim-code pairing flow** (Portal) | src/app/Portal.cpp | 🟡 Untested state machine |
| **OTA update flow** (OtaManager) | src/app/OtaManager.cpp | 🟡 Untested; failure = bricked device |

---

## 2. Critical Bugs Found (Untested Code Paths)

### 2.1 🔴 `src.save()` Missing on UploadsSource — Photo Edit Broken for Uploads

**Location:** `server/spectra_server.py:1452` calls `src.save(real_id, buf.getvalue())`

**Problem:**
- `Source` base class (`sources/__init__.py`) has **no `save()` method**
- `FolderSource` (`sources/folder.py`) has **no `save()` method**
- `UploadsSource` (`sources/uploads.py`) inherits from `FolderSource` — **no `save()`**
- Only `GooglePhotosSource` (`sources/google_photos.py:451`) implements `save()`

**Impact:** Editing an uploaded photo via `/api/photos/uploads:xxx/edit` raises `AttributeError`, caught by the generic `except Exception` → returns `500 {"error": "save failed"}`. The user sees a silent failure.

**Fix:** Add `save()` to `FolderSource` (write bytes to `os.path.join(self.dir, item_id)` with path traversal protection).

### 2.2 🔴 `src.get_metadata()` Missing on UploadsSource — Metadata Endpoint Crashes

**Location:** `server/spectra_server.py:1014` calls `src.get_metadata(real_id)` **without try/except**

**Problem:**
- `Source` base class has **no `get_metadata()` method**
- `FolderSource` and `UploadsSource` have **no `get_metadata()`**
- Only `GooglePhotosSource` (`sources/google_photos.py:417`) implements it

**Impact:** `GET /api/photos/uploads:xxx/meta` raises uncaught `AttributeError` → **500 Internal Server Error** (not a clean 404). The web UI's metadata display will break for uploaded photos.

**Fix:** Either (a) add `get_metadata()` to `FolderSource` returning basic file metadata (name, size, mtime, dimensions), or (b) wrap the call in try/except and return 404.

### 2.3 🔴 No "Push Library Photo to Frame" Path — Verify the UX

**Problem:** The unified library requirement was: *"easier for the user to push the image or the photo to the display."*

**Existing:** Per-device photo override uses `POST /api/devices/{id}/photos/upload` (multipart file upload) — a **separate file upload**, not "select from library."

**Gap:** There is **no tested path** for "select an existing library photo (Google or upload) and pin it to a frame." Either:
- The web UI has this flow but it's untested, or
- The flow doesn't exist and the unified library doesn't actually solve the user's requirement.

**Action:** Map the exact UI/API route for library→frame push. If missing, it's a feature gap, not just a test gap.

### 2.4 🟡 Upload Re-encode Doesn't Specify Format

**Location:** `server/spectra_server.py` (do_POST `/api/uploads`): `img.save(os.path.join(d, name))`

**Problem:** `img.save()` without explicit `format=` relies on PIL inferring from extension. Works for `.jpg`/`.png`, but if `ext` falls through to the default `.jpg`, it's implicit. Also uses default JPEG quality (75) — lower than the 92 used elsewhere.

**Fix:** `img.save(path, "JPEG", quality=92)` explicitly, or preserve format based on extension.

---

## 3. Prioritized Test Cases to Add

### P0 — Fix the bugs first (§2.1, §2.2), then test

1. **`test_uploads_source_save`**: UploadsSource.save() writes bytes, rejects path traversal (`../`, `/`, `.` prefix)
2. **`test_uploads_source_get_metadata`**: Returns dict with at least `filename`, `width`, `height`, `size`; returns None for missing file
3. **`test_edit_uploaded_photo`**: HTTP integration — upload a photo, POST to `/api/photos/uploads:{id}/edit` with rotated JPEG, verify 200 and file replaced on disk
4. **`test_upload_metadata_endpoint`**: HTTP integration — `GET /api/photos/uploads:{id}/meta` returns 200 (not 500)

### P1 — Unified library (the deployed-but-untested feature)

5. **`test_unified_library_lists_both_sources`**: Seed Google Photos cache + uploads dir, call `_all_photos()`, assert both `gphotos:` and `uploads:` IDs present
6. **`test_resolve_namespaced_id`**: 
   - `gphotos:abc.jpg` → (GooglePhotosSource, `abc.jpg`)
   - `uploads:xyz.jpg` → (UploadsSource, `xyz.jpg`)
   - `bogus:xyz.jpg` → (None, None, None)
   - Un-namespaced `abc.jpg` → falls back to active source (backward compat)
   - Non-existent ID → (None, None, None)
7. **`test_upload_appears_in_photos_api`**: HTTP — upload photo, GET `/api/photos`, assert `uploads:{name}` in response
8. **`test_upload_thumbnail_renders`**: HTTP — GET `/api/photos/uploads:{name}/thumb` returns 200 JPEG
9. **`test_upload_full_renders`**: HTTP — GET `/api/photos/uploads:{name}/full` returns 200 JPEG
10. **`test_cross_source_isolation`**: User A's uploads don't appear in User B's `/api/photos`

### P2 — Upload flow end-to-end

11. **`test_upload_valid_jpeg`**: POST multipart JPEG → 200, `{"ok": true, "saved": [...]}`, file exists on disk with UUID name
12. **`test_upload_rejects_non_image`**: POST text file → 400 `{"error": "no readable images uploaded"}`
13. **`test_upload_rejects_oversize`**: POST >25MB → 400
14. **`test_upload_strips_metadata`**: Upload JPEG with EXIF → saved file has no EXIF (privacy)
15. **`test_upload_delete`**: DELETE `/api/uploads/{name}` → 200, file gone; DELETE nonexistent → 404; DELETE `../evil` → 404
16. **`test_upload_file_serve`**: GET `/api/uploads/file/{name}` returns correct content-type; path traversal → 404

### P3 — Frame push/render flow

17. **`test_library_photo_to_frame_override`**: (Once §2.3 is resolved) — select library photo, pin to device, verify `/v1/device/frame` serves it
18. **`test_frame_rotation_uses_uploads_source`**: Device with source=uploads → `_rotate_device` renders uploaded photo to 4bpp frame
19. **`test_frame_etag_changes_on_new_photo`**: ETag differs after rotation to different photo (cache invalidation)

### P4 — Error handling and edge cases

20. **`test_photo_endpoints_reject_bad_ids`**: `/api/photos/bogus:xxx/thumb`, `/full`, `/meta`, `/edit` → 404 (not 500)
21. **`test_edit_rejects_non_image`**: POST garbage to `/edit` → 400 `{"error": "not an image"}`
22. **`test_edit_rejects_oversize`**: POST >15MB to `/edit` → 400
23. **`test_concurrent_uploads`**: Two simultaneous uploads don't corrupt each other's files
24. **`test_empty_uploads_dir`**: `/api/photos` with no uploads and no Google Photos → empty list (not crash)

### P5 — Firmware (host-testable)

25. **4bpp frame parser test**: Feed known 4bpp bytes to `drawPacked4bpp` logic (refactored to pure function), verify pixel output matches expected nibble unpacking. **This would have caught the garbled-photo bug.**
26. **Portal state machine test**: Claim code generation → display → poll → token receipt → paired. Test timeout and error transitions.
27. **OtaManager test**: Manifest parse → version compare → download → verify → apply. Test rollback on verification failure.
28. **FrameFetcher test**: HTTP fetch → ETag handling (304 not-modified) → 4bpp validation → panel write. Test with mock HTTP.
29. **PowerManager test**: Battery threshold gating, deep-sleep duration calculation.
30. **StatusScreen layout test**: Render to mock Panel, assert text fits within bounds (would catch "UI is crap" regressions at the layout level).

---

## 4. Firmware Testing Recommendations

### Can we test firmware logic on host? **Yes — partially, and we should do more.**

**What works today:** `src/core/` is pure C++17 with zero Arduino dependencies. Tests compile with g++ and run natively. This is excellent and should be the model.

**The gap:** `src/app/` contains the most bug-prone code (networking, pairing, OTA, power management) with zero tests. The 0.0.3 boot-loop bug lived here.

**Recommendation — three layers:**

#### Layer 1: Extract pure logic from `src/app/` (high ROI, low effort)
Many `src/app/` modules contain pure logic tangled with Arduino calls:
- `Portal.cpp`: Claim-code format validation, state transitions → extract to `core/`
- `OtaManager.cpp`: Version comparison, manifest parsing (already in core) → extract download state machine
- `PowerManager.cpp`: Sleep duration calculation, battery gating → extract to `core/`
- `FrameFetcher.cpp`: ETag comparison, 4bpp validation → extract to `core/`

**Pattern:** For each, create a `core/XxxLogic.h` with pure functions, keep Arduino I/O in `app/`. Test the logic natively.

#### Layer 2: Mock HAL for `src/app/` integration tests (medium effort)
`src/hal/` already defines `Board` and `Panel` as interfaces. Create mock implementations in `test/`:
- `MockPanel`: Records draw calls instead of touching hardware
- `MockBoard`: Simulates WiFi connect/disconnect, battery readings

This enables testing:
- `StatusScreen` layout (assert text fits, no overlap)
- `drawPacked4bpp` pixel accuracy (the garbled-photo bug)
- `Portal` full pairing flow against mock network

#### Layer 3: Don't test on-device (correctly avoided)
Hardware timing, SPI communication, and deep-sleep behavior can't be meaningfully tested on host. The existing `tools/stub_compile.sh` (compile against Arduino API stubs) catches compile errors. For runtime hardware bugs, the isolation-build discipline (0.0.4 proved the old UI boots) is the right approach.

### Specific firmware test additions (prioritized)

| Priority | Module | What to test | Why |
|----------|--------|--------------|-----|
| P0 | 4bpp parser | Nibble unpacking, row stride, panel code mapping | The garbled-photo bug |
| P0 | Portal | State machine: idle → displaying → polling → paired/timeout | Pairing is user-facing |
| P1 | OtaManager | Version compare, rollback on bad checksum | Brick risk |
| P1 | FrameFetcher | ETag/304 handling, frame validation | Wasted bandwidth/battery |
| P2 | PowerManager | Sleep calculation, battery gating | Battery life |
| P2 | StatusScreen | Text layout bounds | UI regression |

---

## 5. Summary of Critical Actions

| # | Action | Risk if ignored |
|---|--------|-----------------|
| 1 | Add `save()` to `FolderSource` (§2.1) | Uploaded photo editing silently fails (500) |
| 2 | Add `get_metadata()` to `FolderSource` or wrap in try/except (§2.2) | Metadata endpoint crashes (500) for uploads |
| 3 | Verify/implement library→frame push flow (§2.3) | Unified library doesn't solve the user's actual requirement |
| 4 | Add P0+P1 server tests (§3) | The deployed unified library has zero test coverage |
| 5 | Extract pure logic from `src/app/` for host testing (§4) | Next firmware bug will also have zero test coverage |
| 6 | Add 4bpp parser test (§4) | Next image corruption bug will also ship uncaught |

---

## Appendix: Test File Inventory

| File | Lines | Tests | What it covers |
|------|-------|-------|----------------|
| test_auth_devices.py | 1051 | ~60 | Auth, sessions, devices, HTTP integration |
| test_google_photos.py | 263 | ~20 | OAuth, Picker API, PickFlow, source |
| test_pipeline.py | 180 | ~25 | Image dithering, packing, tone mapping |
| test_firebase_backends.py | 265 | ~15 | Blob stores, token stores, Firestore |
| test_server_logic.py | 101 | ~12 | Quiet hours, sources, pick_unseen |
| **Total** | **1860** | **116** | |

| Firmware test | Lines | What it covers |
|---------------|-------|----------------|
| test_battery.cpp | — | BatteryCurve |
| test_json_lite.cpp | — | JsonLite parser |
| test_ota_manifest.cpp | — | OTA manifest parsing |
| test_quiet_hours.cpp | — | QuietHours |
| test_scheduler.cpp | — | Scheduler |
| test_url_template.cpp | — | URL templates |
| test_validate.cpp | — | Input validation |
