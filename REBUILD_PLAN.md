# SpectraFrame Rebuild Plan — shared server OAuth client
Date: 2026-10-04. Status: architecture finalized, verified against official Google docs.

## Goal
Replace bring-your-own-OAuth with the standard third-party-site flow:
welcome page → "Sign in with Google" → account page → "Connect Google Photos"
→ Google allow/deny → pick photos. No Cloud Console, no client IDs, no
secrets anywhere in the user-facing flow.

## Verified facts (from official Google docs, 2026-10-04)
- GIS button (`gsi/client` + `google.accounts.id.initialize/renderButton`) is
  the current sign-in pattern; FedCM is opt-in for the button — no changes
  needed to our GIS code.
- One OAuth client serves both GIS sign-in and the later server-side code
  flow (incremental auth). Add `include_granted_scopes=true` to the connect
  request per Google's incremental-auth guidance.
- Picker API is the sanctioned API. Scope
  `photospicker.mediaitems.readonly` is correct. Session flow unchanged.
- **BUG FOUND 2026-10-04:** `PICKER_BASE` is
  `https://photoslibrary.googleapis.com/v1`; must be
  `https://photospicker.googleapis.com/v1`. This is why "Pick more photos"
  silently failed in the live test.
- baseUrls expire in ~60 min: our PickFlow downloads during import — keep,
  and keep respecting `pollingConfig`.
- Testing-mode refresh tokens expire after 7 days (official). Fix: publish
  the Cloud project to Production. Family runs under Google's personal-use
  exception (unverified warning, click once each). Verification optional
  later (sensitive scope, not restricted: 3–5 days, no security assessment).
- `access_type=offline` + `prompt=consent` already in our connect flow —
  keep (matches Google's longevity guidance). One refresh token per user;
  handle `invalid_grant` → re-prompt to connect.

## Config (SPECTRA_CONFIG_JSON, admin one-time)
```json
{
  "google": {"client_id": "<server OAuth client ID>",
             "client_secret": "<server OAuth client secret>"},
  "auth": {"allowlist": ["er.chiragjain92@gmail.com"]}
}
```
The client already exists ("SpectraFrame web",
`922976952815-jv14fj603edsucs64pd6h7faio247k43.apps.googleusercontent.com`,
project spectraframe-fb5d6). Admin generates one fresh secret for the
config (Google never re-shows secrets) and pastes both values once.

## Code changes
- `auth.py`: `AuthManager` reads server client ID from config;
  `verify_id_token(id_token)` (no client_id param); aud must equal the
  server client ID. Drop user-supplied client validation/binding.
- `spectra_server.py`:
  - `POST /api/auth/token {id_token}` — no client_id, no account↔client
    binding. Account keyed by Google `sub` (email/name stored).
  - `GET /api/config` — serves the server client ID for GIS init.
  - DELETE `PATCH /api/account/client` (rotation UI) and
    `POST /api/gphotos/setup` (per-user secret) incl. legacy migration.
  - `GET /api/gphotos/connect` — server client ID + secret; keep
    `?origin=` validation; add `include_granted_scopes=true`.
  - `GET /api/gphotos/callback` — unchanged mechanics (per-user tokens).
  - KEEP: per-user token store (`StoreTokenStore`), per-user blob
    prefix/cache dir, per-device rotation, OAuth state persistence.
  - FIX `PICKER_BASE`; surface pick errors in-page (no silent alert()).
- Welcome page: friendly headline + GIS "Sign in with Google" only. No
  client-ID box, no Cloud Console steps.
- Account page: email + sign out; Photos section = "Connect Google Photos"
  button (or status + Pick more/Disconnect); pick status shown inline
  (waiting/done/error text).
- UI/UX research (running) feeds the visual design of these pages.

## Migration
Existing account's `oauth_client_id` equals the shared client → ignored by
new code, harmless. Per-user `photos_client_secret` becomes unused.
Existing Photos tokens were minted for the same client → remain valid.

## Rollout
1. Implement + tests green + docs updated; commit + push.
2. Publish Cloud project to Production (browser; user taps).
3. User pastes fresh client secret into SPECTRA_CONFIG_JSON in Portainer.
4. Redeploy stack via Portainer (public URL already live).
5. E2E verify: welcome → sign-in → connect → pick → photos display.
   (User taps Google 2FA/consent prompts as needed.)

## Status 2026-10-04 (post-implementation)

- server/auth.py, sources/google_photos.py, spectra_server.py converted.
- Welcome + console pages rewritten (warm-paper design, GIS button).
- Tests updated; **81/81 green** (incl. PICKER_BASE regression test).
- Docs updated: README, PROTOCOL (v2.2), SELFHOST, GOOGLE_PHOTOS,
  FIREBASE, SYSTEM_PLAN, docker-compose.yml, config.json.example.
- Fix found during test update: WELCOME_HTML() was called without ()
  (function now); CONSOLE/CLAIM_HTML are plain strings.
- Next: commit + push, Production publish, Portainer redeploy, E2E verify.
