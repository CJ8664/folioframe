# FolioFrame Comprehensive Review & Modernization Plan

**Date:** 2026-10-07  
**Status:** In progress — critical bugs fixed, framework evaluation complete  
**Reviews:** Server, Firmware, Web UI, Testing (4 parallel deep reviews)

---

## Executive Summary

Four parallel deep code reviews covered 6,257 lines across server (4,428), firmware (1,829), web UI, and test coverage. Found **3 critical bugs** (2 fixed), **2 high-severity issues**, and identified clear framework replacement opportunities.

**Key decisions:**
- ✅ **Adopted:** `epaper-dithering` (replaces custom dithering) — DONE, deployed
- ✅ **Fixed:** Uploads `KeyError` (missing import) — DONE
- ✅ **Fixed:** `FolderSource.save()`/`get_metadata()` missing — DONE  
- ✅ **Fixed:** OTA MD5 verification broken — DONE
- 🔄 **Evaluate:** Jinja2 for templating, Flask for routing
- ❌ **Rejected:** React/Vue (overkill), ArduinoJson (no benefit), GxEPD2 (wrong panel)

---

## Critical Bugs (Fixed)

### C1. Uploads source never registered — FIXED
**File:** `server/spectra_server.py:64-68`  
**Root cause:** `import sources.uploads` was missing, so `@register` decorator never ran. `SOURCES["uploads"]` → `KeyError`.  
**Impact:** Unified photo library silently omitted uploads; direct `uploads:<id>` requests crashed with connection reset.  
**Fix:** Added the import.  
**Test:** All 116 tests pass.

### C2. FolderSource missing save()/get_metadata() — FIXED
**File:** `server/sources/folder.py`  
**Root cause:** `UploadsSource` inherits from `FolderSource` which only had `next_id()`/`load()`.  
**Impact:** Editing uploaded photos → 500 "save failed"; `/meta` on uploads → unhandled `AttributeError` → thread death.  
**Fix:** Implemented both methods with path-traversal protection.

### C3. OTA MD5 verification broken — FIXED
**File:** `src/app/OtaManager.cpp:95-104`  
**Root cause:** Code hex-decoded MD5 to 16 binary bytes and cast to `const char*`, but `Update.setMD5()` expects a 32-char hex string. `strlen` over-read the stack buffer; validation never registered.  
**Impact:** "MD5-verified OTA" claim was false — updates accepted on size + header only.  
**Fix:** Pass `manifest.md5.c_str()` directly, check return value.

---

## High Severity (To Fix)

### H1. Legacy photo-ID fallback uses wrong source
**File:** `server/spectra_server.py:371`  
`photos_for()` always returns Google Photos controller, not user's active source. Users with `picsum`/`folder`/`dashboard` active get 404s for valid photos.  
**Fix:** `src = self._user_source(sub, self._user_source_name(sub))`

### H2. CSRF form-fallback consumes request body → thread exhaustion DoS
**File:** `server/spectra_server.py:699-718`  
When `X-CSRF-Token` header is absent, code reads entire body looking for form field. Subsequent `_read_json()` blocks forever on consumed bytes. Unbounded threads → memory exhaustion.  
**Fix:** Buffer the body once, or require header-only CSRF.

---

## Framework Replacement Analysis

### Server-Side

| Component | Current | Recommendation | Verdict |
|-----------|---------|----------------|---------|
| Dithering | Custom (377 lines) | `epaper-dithering` (PyPI) | ✅ **ADOPTED** — deployed 2026-10-07 |
| Web framework | Raw `http.server` | Flask | 🔄 **Evaluate** — route table + auth-by-construction; FastAPI rejected (sync app) |
| Templating | Inline HTML strings | Jinja2 | 🔄 **Evaluate** — autoescape kills XSS class; WebUI review says current composition is "fine" for 4 pages |
| HTTP client retry | Hand-rolled (2x) | `httpx` + `tenacity` | 🔄 **Evaluate** — low risk, clear win |
| Logging | `print()` | stdlib `logging` | ✅ **Adopt** — trivial, high value |
| Session signing | Custom HMAC | `itsdangerous` | ⏸️ **Optional** — current code is sound |

**Flask migration:** 2,446-line `spectra_server.py` is a god object. Flask would give:
- Route decorators instead of `if p == "/..."` chains
- `before_request` for auth (instead of manual checks per route)
- Blueprint separation (devices, photos, web UI, API)

**Effort:** Medium (2-3 days). **Risk:** Medium (touches every route).  
**Recommendation:** Do after critical bugs are verified in production. The tactical alternative (route table + Jinja2 on stdlib) gets 70% of the value with 20% of the risk.

### Firmware-Side

| Component | Current | Recommendation | Verdict |
|-----------|---------|----------------|---------|
| Display driver | Seeed_GFX (v1) | Seeed_GFX2 | 🔄 **Evaluate** — v1 is deprecated per Seeed README; GFX2 has native 4bpp framebuffers (eliminates 4bpp→RGB565 conversion) |
| JSON parsing | Custom `JsonLite` (58 lines) | ArduinoJson | ❌ **Rejected** — responses are server-controlled, flat, tiny. ArduinoJson adds ~10KB flash for zero gain. Harden `valuePos()` instead. |
| URL templating | Custom `UrlTemplate` | — | ✅ **Keep** — no better alternative |
| OTA | Custom `OtaManager` | HTTPUpdate | ❌ **Rejected** — manifest format is custom; battery gate + staging justify custom code |

**Seeed_GFX2 migration:**  
- Kills hand-edited `User_Setup.h` + `TFT_CS` `#error` guard
- Native packed-4bpp framebuffers (today: 4bpp→RGB565 conversion pushes ~3.8MB over SPI per refresh)
- `GfxResult` error returns (v1 `begin()` is void)
- Better-maintained ~30s refresh path (relevant to 0.0.3 boot-loop)

**Effort:** Medium. **Risk:** High (needs hardware validation).  
**Recommendation:** Evaluate on bench hardware before committing. The `hal/Panel` seam doesn't need to change.

### Web UI

| Component | Current | Recommendation | Verdict |
|-----------|---------|----------------|---------|
| CSS framework | Farvist (adopted) | — | ✅ **Keep** — working well |
| JS framework | Vanilla | React/Vue | ❌ **Rejected** — overkill for 4 pages; complicates Docker deploy |
| Templating | Inline strings | Jinja2 | ⏸️ **Disputed** — Server review says adopt; WebUI review says current `PWA_HEAD + THEME_CSS` composition is "fine for 4 pages" |

**Organizational improvements (no framework change):**
- Extract console inline JS → `static/console.js`
- Move inline `<style>` → `folioframe.css`
- Unify dark mode on `data-theme` only

---

## Testing Gaps (P0-P2)

### P0: Critical untested paths
1. **Unified photo library** (`_all_photos`, `_resolve_namespaced_id`) — zero tests despite being deployed
2. **Upload flow end-to-end** — zero tests
3. **Library→frame push path** — no verified API/UI route for selecting library photo → pinning to frame

### P1: Important gaps
4. All of `src/app/` firmware (Portal, OtaManager, FrameFetcher, PowerManager) — zero tests (this is where boot-loop bugs lived)
5. 4bpp frame parser — zero tests (this is where garbled-photo bug lived)
6. CSRF edge cases, session expiry, concurrent uploads

### P2: Nice to have
7. Firmware testing: 3-layer approach (extract pure logic → mock HAL → hardware tests on-device)
8. Load testing: concurrent frame fetches, large uploads
9. Mobile-specific UI tests

**30 specific test cases** documented in
[`REVIEW_TESTING.md`](../reviews/REVIEW_TESTING.md).

---

## Implementation Phases

### Phase 1: Critical Fixes — DONE ✅
- [x] Fix uploads `KeyError` (add import)
- [x] Add `FolderSource.save()`/`get_metadata()`
- [x] Fix OTA MD5 verification
- [x] All 116 tests pass
- [ ] Deploy to production and verify

### Phase 2: High-Severity Fixes (This Week)
- [ ] Fix H1: legacy photo-ID fallback source
- [ ] Fix H2: CSRF body-consumption DoS
- [ ] Add regression tests for C1, C2, H1, H2
- [ ] Deploy and verify

### Phase 3: Framework Adoption (Next 2 Weeks)
- [ ] Adopt stdlib `logging` (replace `print()`)
- [ ] Evaluate `httpx` + `tenacity` for retry logic
- [ ] **Decision:** Flask vs tactical route-table (needs Chirag's input on risk tolerance)
- [ ] **Decision:** Jinja2 vs current templating (needs Chirag's input)
- [ ] If Flask: migrate incrementally (one blueprint at a time)

### Phase 4: Firmware Improvements (Next Month)
- [ ] Harden `JsonLite.valuePos()` (key-in-value false positives)
- [ ] Add `jsonInt()` helper, fix `expires_in` parsing hack
- [ ] **Decision:** Seeed_GFX2 migration (needs hardware validation)
- [ ] Fix hardcoded GPIO magic numbers (use `board_config.h`)

### Phase 5: Testing (Ongoing)
- [ ] Add P0 tests (unified library, upload flow, push path)
- [ ] Add P1 tests (firmware app layer, 4bpp parser)
- [ ] Set up firmware host-native tests for `src/app/`

---

## Verification Plan

Per Chirag's requirement: verify 2-3 times using subagents or neutral sessions.

### Round 1: Post-Fix Verification (Now)
- [ ] Spawn subagent to independently verify C1, C2, C3 fixes
- [ ] Run full test suite
- [ ] Deploy to production
- [ ] Manual end-to-end test: upload → library → push to frame

### Round 2: Post-High-Severity Fixes
- [ ] Spawn 2 subagents for independent review of H1, H2 fixes
- [ ] Security-focused review (CSRF, auth, input validation)
- [ ] Load test if feasible

### Round 3: Post-Framework Adoption
- [ ] Full regression test
- [ ] Performance comparison (before/after)
- [ ] Independent code review of migrated components

---

## Open Questions for Chirag

1. **Flask migration:** Full Flask rewrite (higher risk, cleaner) vs tactical route-table on stdlib (lower risk, 70% value)? 
2. **Jinja2:** Adopt for autoescape/XSS protection, or keep current inline templating?
3. **Seeed_GFX2:** Invest in hardware validation for the migration, or stay on v1?
4. **Timeline:** Phase 2 (high-severity) this week — okay to deploy mid-week, or wait for weekend?

---

## Files Changed (This Session)

- `server/spectra_server.py` — added `import sources.uploads`
- `server/sources/folder.py` — added `save()`, `get_metadata()`
- `src/app/OtaManager.cpp` — fixed MD5 verification
- `server/pipeline.py` — migrated to `epaper-dithering` (previous session)
- `server/requirements.txt` — added `epaper-dithering>=6.0`

## Review Documents

- [`REVIEW_SERVER.md`](../reviews/REVIEW_SERVER.md) — full server review
- [`REVIEW_FIRMWARE.md`](../reviews/REVIEW_FIRMWARE.md) — full firmware review
- [`REVIEW_WEBUI.md`](../reviews/REVIEW_WEBUI.md) — full web UI review
- [`REVIEW_TESTING.md`](../reviews/REVIEW_TESTING.md) — testing gap analysis
- [`COMPREHENSIVE_PLAN.md`](./COMPREHENSIVE_PLAN.md) — this document
