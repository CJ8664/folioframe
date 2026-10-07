# FolioFrame Server Code Review

**Date:** 2026-10-07 · **Scope:** `server/` (4,428 lines) — `spectra_server.py` (2,446),
`auth.py`, `devices.py`, `pipeline.py`, `store.py`, `blobs.py`, `token_store.py`,
`sources/*.py`. Reviewed by three parallel section readers plus direct reads of
every supporting module.

**Method:** line-by-line read of all files under `server/` except generated
`__pycache__`. Findings verified against the actual code (not inferred).

---

## 1. Critical — broken functionality in production

### C1. `SOURCES["uploads"]` raises `KeyError` — the unified photo library is silently half-broken
**`server/spectra_server.py:383`** (also `:365`), root cause: missing import.

`server/sources/uploads.py` defines `UploadsSource` with `@register`, but
`spectra_server.py` imports only `sources.folder`, `sources.picsum`,
`sources.url`, `sources.dashboard`, `sources.google_photos` (lines 64–68).
`import sources.uploads` is missing, so the decorator never runs and
`SOURCES` has no `"uploads"` key. Verified at runtime:
`SOURCES["uploads"]` → `KeyError`.

Blast radius:
- `_all_user_photos()` (`:330–349`) wraps the uploads branch in
  `try/except Exception: pass` — the `KeyError` is **swallowed**, so
  `/api/photos` returns `{"ok": true, "photos": [...]}` with uploads silently
  missing. Indistinguishable from "no uploads" in the UI.
- `_resolve_namespaced_id()` (`:355–375`) does **not** catch it, so
  `/api/photos/uploads:<id>/thumb|meta|full` and the edit route
  (`:997–1028`, `:1423+`) die with an unhandled `KeyError` → the request
  thread dies, connection reset, no response.

**Fix:** one line — add `import sources.uploads  # noqa: F401 (registers)`.
Then add a regression test that instantiates `_user_source(sub, "uploads")`
(no test currently touches the uploads path — `server/tests/` has zero
references to `uploads`).

### C2. `FolderSource` has no `save()` / `get_metadata()` — upload edits and metadata crash
`server/sources/folder.py` defines only `next_id`/`load`. `UploadsSource`
inherits from it, so:
- `POST /api/photos/uploads:<id>/edit` (`spectra_server.py:1457`):
  `src.save(real_id, ...)` → `AttributeError`, caught by the surrounding
  `try/except` → `500 {"error": "save failed"}`. Editing an uploaded photo
  can never work.
- `GET /api/photos/uploads:<id>/meta` (`spectra_server.py:1014`):
  `src.get_metadata(real_id)` → **unhandled** `AttributeError` → request
  thread dies, connection reset.

**Fix:** implement `save()` and `get_metadata()` on `FolderSource`
(`get_metadata` can return `None` / basic file stat; `save()` writes bytes
to the item path). Or add a capability check at the route layer and return
`501`/graceful JSON.

---

## 2. High severity

### H1. Legacy photo-ID fallback resolves against the wrong source
**`server/spectra_server.py:371`.**
```python
# "Falls back to active source for un-namespaced IDs (backward compat)."
src = self.photos_for(sub).source   # always the Google Photos source
```
`photos_for()` always returns the Google Photos controller, not the user's
configured active source. A user whose active source is `picsum`/`folder`/
`dashboard` gets 404s for photos that exist, and the returned tuple is
internally inconsistent (`src` = gphotos while `source_name` =
`_user_source_name(sub)`). **Fix:** `src = self._user_source(sub,
self._user_source_name(sub))`.

### H2. CSRF form-fallback consumes the request body → later reads hang forever
**`server/spectra_server.py:699–718`.** When the `X-CSRF-Token` header is
absent, `_require_csrf` reads the entire body off `self.rfile` looking for a
form field. If the token validates that way, handlers like
`/api/devices/claim` (`~1310`) or `/api/source` (`~1480`) then call
`self._read_json()` → `self.rfile.read(length)` on already-consumed bytes →
**blocks indefinitely** (no socket timeout is set). `ThreadingHTTPServer`
spawns unbounded threads, so repeated hits exhaust memory. The header path
is unaffected, so this is latent — but any client exercising the form path
(including an attacker with a session) permanently hangs a thread.
**Fix:** buffer the body once per request and share it, or drop the form
fallback.

### H3. Upload handlers lack the pixel-dimension guard the edit route has
**`server/spectra_server.py:1342–1358`** (`/api/devices/<id>/photos/upload`)
and **`:1384–1396`** (`POST /api/uploads`): read up to 25 MB bodies fully
into memory and call `Image.open(...).convert("RGB")` with no cap. A 25 MB
JPEG can decode to 100+ MP (~300+ MB transient RAM) per request thread;
Pillow's default bomb threshold only trips at ~178 MP. Concurrent uploads →
memory exhaustion. The edit route (`:1446`) already does this correctly via
`pipeline.load_image` (`MAX_IMAGE_PIXELS = 50_000_000`). **Fix:** use
`pipeline.load_image()` in both upload handlers.

---

## 3. Medium severity

### M1. `config.json` (holds `google.client_secret`) written world-readable
**`server/spectra_server.py:142–145`.** `open(cfg_path, "w")` creates the file
0666 & ~umask, while the module docstring (`:48`) asserts sensitive state
lives in 0600 files. On a host/container with permissive umask the OAuth
client secret is world-readable. **Fix:** `os.open(path, O_WRONLY|O_CREAT,
0o600)` or `os.chmod` after write (as `store.py` already does).

### M2. No clickjacking headers on any HTML page
No `X-Frame-Options` or `frame-ancestors` CSP on `/`, `/photos`, `/claim`,
`/flash`, or the console. `SameSite=Lax` + CSRF tokens blunt classic attacks,
but the console UI (rename/unpair/push-photo buttons) can still be iframed
for clickjacking. **Fix:** add `X-Frame-Options: DENY` (or
`SAMEORIGIN` if framing is ever needed) to all HTML responses in `_send`.

### M3. Stray CSS text renders visibly on the public welcome and pairing pages
**`server/spectra_server.py:1723–1724`** (`WELCOME_HTML`) and **`:2383–2384`**
(`CLAIM_HTML`): a bare CSS rule (`#err{margin-top:10px}` /
`form .btn{width:100%;margin-top:14px}`) followed by `</style>` with no
opening `<style>` tag. Browsers render the rule as literal text at the top
of the page. User-visible on first impression and during pairing.
**Fix:** wrap in `<style>…</style>` or drop the orphan `</style>`.

### M4. Non-object JSON bodies crash with unhandled `AttributeError` → 500
**`:1260`** (`/v1/device/register`), **`:1279`** (`/v1/device/claim`),
**`:1314`** (`/api/devices/claim`), **`:1481`** (`/api/source`),
**`:1506`** (`do_PATCH`): `data = self._read_json(); if data is None: 400`
then `data.get(...)`. A client posting valid JSON that isn't an object
(`[1,2]`, `"x"`, `42`) passes the `None` check and `data.get` raises
`AttributeError` → unhandled 500 (and `BaseHTTPRequestHandler` renders the
exception into the 500 page — minor internals disclosure).
**Fix:** `if not isinstance(data, dict): 400` at each site, or once inside
`_read_json`.

### M5. `/api/auth/logout` has no CSRF check — logout CSRF is possible
**`:1240–1247`.** Every other state-changing human route enforces
`_require_csrf`; logout only destroys the session. `SameSite=Lax` still
sends cookies on top-level POST navigations, so a malicious page can log the
victim out via a hidden form POST. Impact is annoyance-level, but it's the
single inconsistent route. **Fix:** require the CSRF header like every other
POST (the console's `logout()` JS at `:2373` would need the header added —
currently it uses raw `fetch` without it).

### M6. Race: `self._frames` and `self.state["history"]` mutated lock-free
**`:451–467`, `:489–535`.** There is **no `threading.Lock` anywhere** in
`spectra_server.py`, but `_rotate_device` runs concurrently from the
background `tick()` thread, lazy rotation in `device_frame`/`device_preview`,
and `/api/next`. Two threads rotating the same device can both read the
same history, both pick the *same* photo via `src.next_id(hist)`, both burn
seconds dithering, and the last writer wins on `hist[-200:]` — silently
dropping the other's history append. `JsonStore`'s internal lock serializes
the file write but not the in-memory read-modify-write. **Fix:** a
per-device lock (or single-flight) around `_rotate_device`; a lock around
history mutation.

### M7. Swallowed exceptions make failures indistinguishable from empty state
- `_all_user_photos` (`:341`, `:348`): `except Exception: pass` → broken
  source = empty library, no log (this is exactly what hid C1).
- `/api/photos` (`:988–990`): `except Exception: photos = []`.
- `/api/photos/<id>/thumb|full` (`:1006`, `:1023`): every exception → 404
  "not found", including disk I/O failures and corrupt caches.
**Fix:** log at `WARNING` minimum; map expected-not-found to 404 and let
unexpected errors 500 with a logged traceback.

### M8. No rate limiting on human routes
Only `/v1/device/register` and `/v1/device/claim` are per-IP rate-limited
(`devices.RateLimiter`, wired at `:1249`, `:1268`). Unauthenticated-but-
session-holding callers can hammer without backoff:
- `/api/devices/claim` (`:1304`) — claim-code guessing with a valid session.
- `/api/next` (`:1464–1475`) — each call re-renders all of a user's devices
  (full dither + PNG + disk write per device); a stolen session or misclick
  loop pins CPU.
- `/api/uploads` (`:1364`) — 25 MB/request, no per-user quota → disk fill.
- `/api/gphotos/pick` — unbounded daemon threads per call (R5 below).

### M9. `_parse_multipart` `.decode()` unguarded → crafted filename kills the request
**`:589`.** Non-UTF-8 bytes in a multipart field name/filename raise
`UnicodeDecodeError`, uncaught in both upload routes → thread dies,
connection reset. Trivially triggerable. **Fix:** `errors="replace"`.

---

## 4. Low severity / robustness

- **L1** `photos_for` (`:305–321`) and `_user_source` (`:376–390`):
  check-then-act races — duplicate `GPhotosController`/source construction;
  benign (last write wins, functionally equivalent) but no eviction:
  `self._photos` grows one entry per user `sub` forever (memory leak on a
  long-lived multi-user server).
- **L2** `gphotos_pick` (`:414–436`) spawns an unbounded daemon thread per
  call; a user can spam `POST /api/gphotos/pick` and pile up concurrent
  photo imports (each downloading from Google).
- **L3** `sub` (Google `sub` claim) interpolated raw into filesystem paths
  (`:294`), blob prefixes (`:313`), and state keys — latent traversal if the
  claim ever isn't a plain numeric string. Sanitize once at session creation.
- **L4** `int(APP.build)` (`:970`) unguarded — a `None`/non-numeric build
  500s the whole `/api/devices` console endpoint.
- **L5** Startup fragility: `json.load(config.json)` (`:147`) and
  `json.loads(SPECTRA_CONFIG_JSON)` (`:152`) unhandled → malformed config
  kills the server with a bare traceback. `quiet_start`/`quiet_end`
  (`:123–125`) never validated — a typo like `"2200"` raises `ValueError`
  per-request inside `_in_quiet_now`.
- **L6** `_google_creds` (`:221–222`, same pattern `:163`): `cfg.get("google",
  {})` returns `None` when the key is JSON null → `.get` → `AttributeError`.
- **L7** `DELETE /api/uploads/<name>` (`:1520–1535`) never URL-decodes the
  name while the client sends `encodeURIComponent(name)` (`:2284`) — latent
  today (names are `uuid4hex.ext`), but the asymmetry is a real bug for any
  future non-ASCII filename.
- **L8** `/api/gphotos/pick` (`:1412`) returns `str(e)` to the client —
  leaks internal paths/provider details; inconsistent with the redacted
  `/api/gphotos/callback` (`:1128–1135`).
- **L9** Dead ternary in `_flash_page` (`:1940`):
  `n if n != 'firmware.bin' else 'firmware.bin'` ≡ `n`. Harmless; indicates
  unreviewed edits.
- **L10** `os.remove` in DELETE uploads (`:1531`) and `img.save` in POST
  uploads (`:1392`) unguarded — disk-full/permission errors → unhandled 500
  (possibly after partial success).
- **L11** `self.rfile.read(length)` has no disconnect handling — mid-upload
  disconnects yield short reads that downstream code only mostly tolerates.
- **L12** Trailing-slash papercuts: `POST /api/uploads/` → 404 (exact match
  only); `PATCH /api/devices/<id>/` → 404.
- **L13** `main()` (`:2430–2444`): no graceful shutdown; SIGTERM drops
  in-flight requests (relevant for Docker/Cloud Run deploys).
- **L14** Version strings interpolated unescaped into `<option>` HTML and a
  JS string in `_flash_page` (`:1925–1935`, `~1994`) — exploitable only with
  server-admin file-drop access; defense-in-depth `html.escape` warranted.
- **L15** `e.message` concatenated into `innerHTML` (`:2014`) — browser-
  generated string today, but the pattern becomes DOM-XSS the moment the
  source changes; use `textContent`.

## 5. Pipeline dead code and doc drift (after the `epaper-dithering` migration)

`server/pipeline.py` still carries the full pre-migration implementation as
dead code, and its docstrings now misdescribe reality:
- **Dead:** `apply_tone`, `apply_drc`, `apply_preprocessing`,
  `DEFAULT_TONE`, `_tone_cfg`, `_nearest`, `_palette_image`,
  `_coverage_solver`, `BAYER8`/`_BAYER8`, `_SRGB2LIN`,
  `_palette_lab_lightness`, `_PALETTE_LS/*`. `process_image` (`:350`)
  explicitly skips preprocessing — none of these are reachable.
- **Latent crash in dead code:** `_coverage_solver` (`:241`) declares
  `global _coverage_solver_cache` but the name is never initialized at
  module level — calling it raises `NameError`. Harmless only because it's
  unreachable.
- **Wrong docstring:** `dither_floyd_steinberg` claims
  "Native codes: 0x0 black, 0x1 white, 0x2 yellow, 0x3 red, 0x5 blue, 0x6
  green" — the actual mapping (`_LIB_TO_NATIVE`) emits this repo's `PALETTE`
  nibbles (`0x0=white, 0x2=green, 0x6=red, 0xB=yellow, 0xD=blue,
  0xF=black`). A future reader "fixing" toward the docstring would break
  the firmware contract.
- **Stale module docstring** (`:1–37`): three paragraphs describe the
  hand-rolled Floyd-Steinberg-via-Pillow and the ported coverage-Bayer
  solver as if they were the implementation. Misleading for contributors.
- **Duplication:** `cover()` (`:118`) reimplements
  `PIL.ImageOps.fit(img, (w, h), Image.LANCZOS)` (center-crop + resize).
  Replace with the stdlib one-liner.
- The `itertools` import is now used only by dead `_coverage_solver`.

## 6. What's actually good (don't regress these)

- **Auth/CSRF discipline is consistently correct** on every state-changing
  human route reviewed: `_require_human()` + `_require_csrf()` everywhere
  except logout (M5). Device routes use Bearer tokens via `_require_device()`.
- **`auth.py` session design is sound:** 256-bit secret persisted in the
  store, HMAC-signed `session_id.sig` cookies, `hmac.compare_digest`,
  24h TTL with lazy expiry, per-session CSRF secrets, constant-time claim-
  code comparison in `devices.py`. No findings above low severity.
- **Claim flow has no oracle:** `/v1/device/claim` maps `BadClaim` to the
  identical `{"status":"pending"}` shape.
- **IDOR is handled:** device routes check `dev.get("owner") != sub`;
  photo IDs resolve through an allowlist against the user's own cached
  `_ids()` with unquoting *before* the check.
- **Traversal guards** on `/static/`, `/flash/*.bin`, `/api/uploads/file/`,
  DELETE-upload operate on the raw (never-decoded) path segment and reject
  `/`, `..`, leading `.`.
- **Upload hygiene:** size caps enforced from `Content-Length` *before*
  reading bodies; device-push checks ownership before reading the body;
  uploads are re-encoded (`convert("RGB")` + `img.save`), stripping
  EXIF/metadata.
- **Google Photos download parsing** correctly reads `mediaFile.baseUrl`
  (the Oct-2026 Picker bug is fixed and documented in-code).
- **`JsonStore`** uses atomic tmp+rename writes, 0600 perms, a lock, and
  quarantines corrupt files instead of crash-looping. `LocalBlobStore._path`
  contains keys under root.
- **`devices.py`** is the best-written module: clear security model,
  grace-window re-delivery, atomic ownership transfer, per-field heartbeat
  sanitization.

## 7. Framework / library replacement analysis

The codebase deliberately leans on stdlib (`urllib` over `requests`,
`http.server` over Flask — see `google_photos.py`: "Minimal OAuth2
auth-code flow (stdlib only)"). That choice has a real benefit (small
Docker image, no dependency surprises) and a real cost (this review's
bug list is dominated by things frameworks give you for free). Assessment
per component:

### 7a. HTML templating: inline strings → Jinja2 — STRONG RECOMMEND
~1,200 lines of HTML/CSS/JS live as Python string literals with `+`
concatenation and `.format`-style interpolation. No syntax checking, no
editor support, and Python/JS/HTML quoting layers interact badly (the
`\\'` in the `clearOv` onclick, `{{}}` doubling in `_flash_page`'s f-string
JS). This directly caused M3 (stray `</style>` visible to users).
Jinja2's **autoescaping** eliminates the XSS class that today depends on
developers remembering the hand-rolled `esc()` helper on every page (only
`CONSOLE_HTML` has it). **Adoptable without changing the web framework**:
render to string, serve via the existing `_send`. Low risk, high value —
do this first.

### 7b. Web framework: raw `http.server` → Flask — RECOMMEND, but as a project
The 2,446-line `Server` god object with a ~60-branch `if/elif` dispatch
chain is where auth-check omissions *would* hide (today's discipline is
good, but it's enforced by convention, not construction). Flask gives:
route table with decorators (missing-auth becomes structurally obvious),
`flask.abort`/error handlers (replaces the ad-hoc 404/500 mapping that
produced M4/M7), request/response objects (replaces the `_read_json` /
`_parse_multipart` / `_photo_id_from_path` hand-rolls), and `gunicorn` for
production (graceful shutdown — L13). **FastAPI is the wrong fit** here:
the app is synchronous and I/O is blocking Pillow/urllib work; async buys
nothing and every handler would need `run_in_executor`. **Tactical
alternative** if a rewrite is rejected: keep `http.server` but add a
`(method, regex) → (handler, auth_required)` route table so auth becomes
declarative, plus Jinja2 (7a). That captures ~70% of the value at ~10% of
the cost.

### 7c. Cookie signing: hand-rolled HMAC → `itsdangerous` — OPTIONAL
The current scheme (`session_id.sig`, `compare_digest`, server-side store)
is correct; `itsdangerous.URLSafeTimedSerializer` would replace ~15 lines
with a maintained implementation and add timestamped signatures. Nice
hygiene, not a fix. Low priority.

### 7d. HTTP client: `urllib` + duplicated retry → `httpx` + `tenacity` — RECOMMEND
Transient-error detection is hand-rolled **twice** with different keyword
lists: `auth.py:verify_id_token` (string matching on exception messages)
and `google_photos.py:_is_transient_network_error`/`_http_with_retry`
(type-based). `httpx` (proper timeouts, connection pooling) + `tenacity`
(declarative retry with backoff/jitter) collapses ~80 lines and unifies
policy. Also fixes the string-matching fragility in `auth.py`.

### 7e. OAuth2 flow: hand-rolled → `authlib` — DEFER
`GoogleOAuth` (~60 lines, stdlib) is well-tested and correct; the
stdlib-only choice is deliberate for image size. Revisit only if scopes or
flows get more complex.

### 7f. Image utils: `cover()` → `PIL.ImageOps.fit` — DO IT
One-line replacement, battle-tested C implementation. Trivial.

### 7g. Logging: `print()` → stdlib `logging` — DO IT
`print` is the only observability (E-track: swallowed exceptions are
invisible in production). `logging` with a formatter + level is stdlib and
makes M7's recommended `WARNING` logs actually useful.

## 8. Prioritized action items

**P0 (fix before the next user-facing test):**
1. Add `import sources.uploads` (C1) + regression test.
2. Implement `save()`/`get_metadata()` on `FolderSource` (C2).
3. Fix `_resolve_namespaced_id` legacy branch to use the active source (H1).

**P1 (this week):**
4. Harden upload handlers: `pipeline.load_image` pixel cap (H3), file-count
   and per-user quota (M8/S4 in §3 of section report).
5. Fix the two stray-`</style>` rendering bugs (M3).
6. Add `isinstance(data, dict)` guards on JSON bodies (M4).
7. `0600` on written `config.json` (M1); validate config at startup (L5).
8. CSRF on logout + header in `logout()` JS (M5).
9. Clickjacking headers on all HTML responses (M2).

**P2 (structural):**
10. Per-device lock / single-flight around `_rotate_device`; lock history
    mutation (M6). Add rate limiting to human routes (M8).
11. Delete `pipeline.py` dead code; fix the wrong `dither_floyd_steinberg`
    docstring; rewrite the stale module docstring; `ImageOps.fit` for
    `cover()` (§5, 7f).
12. Replace `print` with `logging`; stop swallowing exceptions (M7).
13. Unify retry logic (`httpx` + `tenacity`, 7d).
14. Adopt Jinja2 templates (7a) — the single highest-leverage structural
    change; Flask migration (7b) as the follow-on project.

**P3 (nice to have):** `itsdangerous` (7c), `authlib` (7e), trailing-slash
consistency (L12), graceful shutdown (L13), `sub` sanitization (L3),
`_photos` eviction (L1), `origin` redirect validation audit (S6 in section
report — the `/api/gphotos/connect?origin=` handler needs a server-side
check against the request host).
