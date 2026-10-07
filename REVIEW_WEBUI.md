# FolioFrame Web UI — Deep Code Review

**Date:** 2026-10-07
**Scope:** `server/spectra_server.py` (2,446 lines), `server/static/` (CSS/JS assets)
**Reviewer:** subagent code review

---

## 1. Page/Route Inventory

### HTML pages (4)

| Route | Template | Auth | Description |
|---|---|---|---|
| `/` (signed out) | `WELCOME_HTML()` (line 1717) | Public | Frosted-glass hero, Google Identity Services sign-in button, feature cards, PWA install prompt, link to `/flash` |
| `/` (signed in) | `CONSOLE_HTML` (line 2106) | Login | Main console: My uploads card, Google Photos card, Photo source switcher, Frames/devices card, Account card |
| `/photos` | `PHOTOS_HTML()` (line 1807) | Login | Photo library: thumbnail grid, slide-in preview panel (original + simulated e-ink), full 3:4 photo editor modal |
| `/claim` | `CLAIM_HTML` (line 2379) | Login | Pair-a-frame: 8-char code input, auto-redirects to `/` 1.5s after success |
| `/flash` | `_flash_page()` (line 1917) | Public | Firmware flasher: 30/70 split (steps + version picker left, console right), esp-web-tools `ewt-install-dialog` |
| `/login` | — | — | Redirect to `/` (legacy bookmark support) |
| `/debug` | — | Login | JSON diagnostics (sources, rotation, build, device IDs) — benign |

### Shared snippets (all pages)

- `PWA_HEAD` (1592): meta tags, theme-color `#d9d1c4`, theme init script (localStorage + `ffThemeToggle()`)
- `THEME_CSS` (1585): 3 stylesheets with content-hash cache-busting — `farvist.min.css`, `farvist-warm-clay.css`, `folioframe.css`
- `HINT_JS` (1648): "?" tooltip system (hover on desktop, tap-toggle on touch, Escape closes, viewport-clamped)
- `SW_REGISTER` (1620): service worker registration + PWA install prompt handling

### Static assets

| File | Size | Purpose |
|---|---|---|
| `static/farvist.min.css` | 143 KB | Farvist UI framework (vendor) — buttons, cards, forms |
| `static/farvist-warm-clay.css` | 2.5 KB | Farvist design-token mapping to Warm Clay / Ink Dark |
| `static/folioframe.css` | 27 KB (1,013 lines) | App-specific components: photo grid, preview drawer, editor modal, uploads, tooltips |
| `static/photos.js` | 21.5 KB (543 lines) | Photo picker: grid, e-ink simulation (CIELAB + Floyd-Steinberg in JS), 3:4 editor |
| `static/sw.js` | 2 KB | Service worker: app-shell cache + offline fallback |
| `static/esp-web-tools/` | — | Web Serial flasher components |

---

## 2. Bugs Found

### B1. Invisible link in light mode (console, Google Photos card)
**Location:** `spectra_server.py:2210`
```js
st=`<p class='msg'>Picker open — <a style='color:#fff' href='...'>continue choosing photos</a>, ...`;
```
Hardcoded `color:#fff` (white text). In Warm Clay light mode this link is invisible against the light card background. Should use `var(--accent)` or a theme-aware class.

### B2. CSS selector mismatch — photo section heading unstyled
**Location:** `folioframe.css:793` vs `spectra_server.py:1832`
CSS targets `.photo-section-head h3` but the HTML uses `<h2>Your photos</h2>`. The heading gets browser-default h2 styling instead of the intended 15px semibold. Either change the CSS selector to `h2` or the HTML to `h3`.

### B3. Flash "inline console" is actually a modal (known issue, root cause identified)
**Location:** `spectra_server.py:2024-2032`
The `_flash_page` docstring claims `ewt-install-dialog` is "instantiated directly so the whole flow stays in the page instead of a popup." But `ewt-install-dialog` from esp-web-tools **is inherently a modal dialog web component** — it renders as an overlay by design. No amount of CSS token theming changes this. Options:
- (a) Accept the modal (it's the component's intended UX) and remove the misleading docstring/CSS comments
- (b) Switch to `esp-web-install-button` (inline button variant) + a separate log `<pre>` element, driving the install via the `esp-web-tools` JS API directly

### B4. Service worker caches auth-dependent `/`
**Location:** `static/sw.js`
`SHELL` includes `"/"`, and navigations cache `cache.put("/", res.clone())`. But `/` returns **different HTML** depending on sign-in state (welcome vs console). An offline load could serve the wrong variant. Fix: don't cache `/` navigations, or use separate cache keys.

### B5. Manifest / meta theme-color mismatch
**Location:** `static/manifest.webmanifest` vs `PWA_HEAD`
Manifest has `"theme_color": "#070a13"` and `"background_color": "#070a13"` (dark navy), but `PWA_HEAD` sets `<meta name='theme-color' content='#d9d1c4'>` (warm clay). The installed-PWA splash/header color won't match the site theme. Also `sw.js` cache name is still `"spectraframe-v2"` — stale product name.

### B6. Missing network error handling (console page)
**Location:** `CONSOLE_HTML` inline JS (`renderDevices`, `renderUploads`, `renderSources`)
Unlike `photos.js:loadPhotos()` (which shows "Could not reach the server"), these three functions `await fetch(...)` with no try/catch. If the server is unreachable mid-session, they throw unhandled promise rejections and leave "Loading…" spinners forever. Wrap in try/catch with a user-visible error like photos.js does.

### B7. Fragile inline-JS string interpolation (XSS-adjacent pattern)
**Location:** `renderUploads` — `onclick=\"upDelete('${esc(p.name)}')\"`
`esc()` HTML-escapes (`'` → `&#39;`), but HTML attribute parsing decodes entities **before** JS evaluation, so a name containing `'` would break the handler. Safe in practice (upload names are server-generated UUID hex), but the pattern is fragile. Prefer `data-*` attributes + delegated listeners (as `photos.js` does with `data-photo-id`).

---

## 3. UI/UX Issues

### U1. Claim page: no manual "continue" affordance
Fixed with 1.5s auto-redirect, but during the wait there's no button/link. Add a "Continue to console →" link that appears on success for users who don't want to wait.

### U2. Confusing empty-state copy (My uploads)
"No uploads yet — pick some photos below." The upload form is **above** this message (same card). Change to "use the upload form above" or move the empty state below the form.

### U3. Photo-source `tablist` has no keyboard arrow navigation
Buttons have `role='tab'`/`aria-selected` but arrow keys don't move between tabs (WAI-ARIA tab pattern). Minor; alternatively drop `role='tablist'`/`role='tab'` and use a plain radiogroup or button group.

### U4. No feedback when Google Picker polling times out
`pollPick()` polls 48×5s (4 min) then silently calls `renderPhotos()`. If the user abandons the picker tab, the console just quietly refreshes. Acceptable, but a "picker timed out" note would help.

### U5. Device preview images have no loading/error state
`<img src='/api/devices/.../preview'>` with no `onerror` fallback — a 503 (no frame rendered yet) shows a broken-image icon. Add a placeholder or hide on error.

### U6. `photos.js` e-ink simulation now diverges from server pipeline
The JS simulation uses its own calibrated palette + Floyd-Steinberg, but the server just switched to the `epaper-dithering` library with `tone='auto'`/`gamut='auto'`. The preview is now a **different algorithm** than what the frame will show. Update the JS palette/tonemapping to match, or document the divergence as "approximation."

---

## 4. Code Organization Issues

### C1. 2,446-line single file with inline HTML/CSS/JS
All 4 pages are Python string literals. No syntax highlighting, no JS/CSS linting, no template validation. The f-string composition pattern (`PWA_HEAD + THEME_CSS + ...`) is clean, but:
- **Console page JS (~270 lines)** should be extracted to `static/console.js` like `photos.js` was — same cache-busting pattern already exists (`_static_ver`)
- **Inline `<style>` blocks** in `CLAIM_HTML` (`form .btn{...}`) and `_flash_page` (flash-split layout, `.parts` table) should move to `folioframe.css`

### C2. Dark mode uses two parallel mechanisms
`ffThemeToggle()` sets **both** `documentElement.classList['dark']` and `dataset.theme`. `folioframe.css` keys off `html.dark`; `farvist-warm-clay.css` keys off `[data-theme="dark"]`. Works today, but a future edit touching only one mechanism will half-break theming. Standardize on `data-theme` (Farvist's convention).

### C3. Dead CSS
`_flash_page` styles `esp-web-install-button` (line 2043) but the page only ever creates `ewt-install-dialog`. Remove or keep if pursuing fix B3-b.

### C4. Inconsistent heading levels
Console cards use `<h2>` for card titles; photos page section head CSS expects `<h3>`. Flash page uses `<h3>` for card titles and `<h1>` for the hero. Pick one scale: page `<h1>` → card `<h2>`.

---

## 5. Mobile Responsiveness — mostly good

| Area | Status |
|---|---|
| Photo grid (`repeat(auto-fill, minmax(96px, 1fr))` / photo tiles) | ✓ Responsive |
| Preview drawer (`width: min(880px, 92%)`) | ✓ Works on phones |
| Editor layout (stacks < 760px) | ✓ Has media query |
| Flash 30/70 split (collapses < 900px) | ✓ Has media query |
| Hint tooltips (viewport-clamped via JS) | ✓ Thoughtful |
| `.control-row` grid (86px / 1fr / 48px) | ⚠ Tight on 320px screens — labels may wrap |
| Topbar on narrow screens (brand + Photos + theme + install + avatar + logout) | ⚠ Could overflow on very narrow screens; no wrapping rule |

---

## 6. Accessibility — generally strong, small gaps

**Good:** aria-labels on icon buttons, `role='dialog'`/`aria-modal` on preview+editor, `aria-live='polite'` on render status, `focus-visible` outlines, focus restore on modal close (`lastFocused`), `prefers-color-scheme` respected on first load, `tabindex='0'` on editor canvas.

**Gaps:**
- No skip-to-content link
- Tablist arrow-key nav missing (U3)
- Emoji-only buttons (🌕 theme toggle, ⏻ sign-out) — have `title`/`aria-label`, acceptable
- `aria-hidden='true'` on `previewShell`/`editorShell` while `is-open` toggles it to false — correct pattern ✓

---

## 7. Framework Recommendations

**Keep Farvist.** It's already integrated and working: `.btn`, `.btn-primary`, `.btn-ghost`, `.btn-sm`, `.card`, `.form-control`, `.badge`/`.pill` come from `farvist.min.css` (143 KB vendored, self-hosted — no CDN dependency). `folioframe.css` (27 KB) is appropriately scoped to app-specific components. This is a good division; do not replace.

**Do not adopt React/Vue/Svelte.** Four pages with modest interactivity; a build step would complicate the single-binary Docker deploy. The vanilla-JS + `fetch` approach is the right weight.

**Recommended changes (no new dependencies):**
1. Extract console inline JS → `static/console.js` (mirrors `photos.js` pattern, gets `_static_ver` cache-busting free)
2. Move inline `<style>` blocks → `folioframe.css`
3. Standardize dark mode on `data-theme` only
4. **Do not adopt Jinja2.** The current composition (`PWA_HEAD + THEME_CSS + HINT_JS + SW_REGISTER`) is effectively a tiny template system with zero dependencies. Jinja2 adds a dependency for 4 pages — not worth it. If pages grow past ~8, reconsider.

**One dependency worth considering:** none for the frontend. The backend already did the right thing adopting `epaper-dithering` instead of hand-rolled dithering (same principle the user asked about).

---

## 8. Prioritized Action Items

### P0 — user-visible bugs
1. **B1**: Fix hardcoded `color:#fff` picker link (one-line CSS fix)
2. **B6**: Add try/catch + error UI to `renderDevices`/`renderUploads`/`renderSources`
3. **B4**: Stop service worker from caching auth-dependent `/`

### P1 — correctness / consistency
4. **B2**: Fix `.photo-section-head h3` → `h2` selector mismatch
5. **B5**: Align manifest `theme_color`/`background_color` with `#d9d1c4`; rename SW cache to `folioframe-v1`
6. **U6**: Reconcile `photos.js` e-ink simulation with server `epaper-dithering` output
7. **B3**: Decide: accept modal dialog (fix docstring) or switch to inline install button

### P2 — code health
8. **C1**: Extract console JS → `static/console.js`; move inline `<style>` → `folioframe.css`
9. **C2**: Unify dark mode on `data-theme`
10. **B7**: Replace inline `onclick` string interpolation with `data-*` + delegation
11. **U1/U2**: Claim-page continue link; fix uploads empty-state copy
12. **C4**: Normalize heading levels across pages

### P3 — polish
13. **U3**: Tablist keyboard nav (or drop tab roles)
14. **U5**: Loading/error state for device preview images
15. Topbar wrapping for very narrow screens
6. Remove dead `esp-web-install-button` CSS (or use it per B3-b)
