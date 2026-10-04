# SpectraFrame System Plan — Device · Service · Web Console

**Status:** plan for review — no implementation until approved.
**Date:** 2026-10-02. **Author:** Piku, at Chirag's request.

## 1. Goal

Three components that work as one secure system:

1. **Device** — EE02 + GDEB0709E01 firmware. Flash once; on first boot it gets on
   Wi-Fi, shows a pairing code/QR on the e-ink screen, and waits to be claimed.
   After pairing it wakes on schedule and pulls its photos from the service
   **with no human in the loop**.
2. **Persistent service** — always-on backend. Requires explicit **Google sign-in**
   (no anonymous access to anything user- or device-scoped). Holds the device
   registry, per-device photo state, and serves each device its own frame.
3. **Web console** — phone/laptop site. Sign in with Google → pair a device by
   entering the code on its screen → manage devices: grant Google Photos access,
   pick photos, upload local photos, set refresh cadence, preview what a device
   shows.

**Hard security requirement (Chirag's):** there is **no path** by which a device
— or anyone else — can read or change anything without first being paired to an
explicitly signed-in account. Every gap below is assessed against this bar.

## 2. Research findings

### 2.1 Pairing patterns (what exists in the wild)

- **Tesserae** (the richest dashboard framework found in the 9-repo survey) does
  **not** do claim-code pairing: its ESP32 clients are provisioned out-of-band
  with a pre-shared key, then heartbeat + fetch frames. Lesson: even mature
  projects punt pairing to manual provisioning — a real claim flow is a genuine
  improvement, not reinventing a wheel.
- **ESP RainMaker / commercial IoT** use the claim-code model: device shows a
  short code, phone app (signed in) submits it, cloud binds device → account,
  device polls until approved then receives credentials. This is the model
  adopted below — it is the industry-standard answer to "no keyboard on device".
- **Chromecast-style QR**: encoding the claim URL in a QR on the device screen
  removes typing errors. On ESP32 the safe QR implementation is **Nayuki
  qrcodegen** (2 vendored C files, no heap required) — the Arduino `ricmoo/QRCode`
  library collides with the `qrcode` component bundled in ESP-IDF/arduino-esp32
  and is not recommended.

### 2.2 Google sign-in verification (backend checklist)

Verified against current Google guidance (Oct 2026). When the web console
receives a Google ID token, the backend **must**, on every login:

1. Fetch JWKS from `https://www.googleapis.com/oauth2/v3/certs` (cache per
   `Cache-Control`; keys rotate).
2. Verify the **RS256** signature against the matching `kid`.
3. Check `aud` **exactly equals** our Web OAuth client ID.
4. Check `iss` ∈ {`accounts.google.com`, `https://accounts.google.com`}.
5. Reject expired tokens (`exp`), allow ~60 s clock skew.
6. Optionally require `email_verified: true` when keying identity off email.
7. Use `sub` (stable Google user ID) as the user key, **not** email alone.

Reference: https://developers.google.com/identity/gsi/web/guides/verify-google-id-token
Never accept an unverified/decoded JWT — that is a full authentication bypass
(see the `alg:none` class of bugs).

### 2.3 ESP32 TLS that actually validates

- `WiFiClientSecure::setInsecure()` (what our firmware does today) encrypts but
  does **not** authenticate the server — a network attacker can impersonate the
  service and feed the device arbitrary frames or harvest its token. Acceptable
  on a trusted LAN; **not acceptable** for an internet-hosted service.
- Correct approach: `setCACertBundle()` with the core's embedded Mozilla root
  bundle (Arduino-ESP32 ≥ 2.0.5; `NetworkClientSecure` in 3.x), or pin the
  ISRG Root X1/X2 roots (~3 KB) if the server will always use Let's Encrypt.
- Gotcha found in research: some hosts serve mixed ECDSA/RSA chains that break
  mbedTLS verification — diagnose with
  `openssl s_client -connect host:443 -servername host -showcerts`. If we host
  on Firebase/Cloud Run (Google Trust Services certs), the **full CA bundle**
  is required, not LE pinning.
- TLS needs valid time: our firmware already does NTP before network use — keep
  that ordering hard (no TLS before NTP sync succeeds).

### 2.4 Hosting options

| | **Firebase (recommended)** | Home lab (Proxmox/umbrelOS) | Plain VPS |
|---|---|---|---|
| Public reachability | Built in (Hosting + Cloud Run) | Needs tunnel (Tailscale/CF); Proxmox currently unreachable from here | Built in |
| Google sign-in | Firebase Auth, free, zero crypto code | Self-implement OIDC verification | Self-implement |
| TLS cert | Automatic (Google Trust Services) | Let's Encrypt via DNS-01 or tunnel | Let's Encrypt |
| Cost | Spark free tier covers 1 user + a few devices easily | $0 (existing hardware) | ~$5/mo |
| Data locality | Google's cloud | Your house | Provider's cloud |
| Effort | Port server to Cloud Run + Firestore | Docker + tunnel + OIDC + certs | Docker + OIDC + certs |

**Recommendation:** Firebase primary. Reasons: (a) the device must reach the
service from anywhere — Firebase is public by default; (b) Google sign-in is
the headline requirement and Firebase Auth implements it correctly for free;
(c) Chirag already deploys to Firebase with OIDC (pregnancy app) — familiar
flow. Keep the server's storage behind an interface so a **self-hosted Docker
variant** can follow later without a rewrite. **Decision needed:** confirm
Firebase, or pick home-lab-first.

## 3. Architecture

### 3.1 Identity model

- **User**: Google `sub` (stable), plus email/display name for the UI.
  Single-user deployment = allowlist containing Chirag's email; the data model
  is multi-user-capable from day one so no migration is ever needed.
- **Device**: `device_id = "sf-" + lowercase(ESP32-S3 eFuse MAC)`, e.g.
  `sf-94a9a811c2f4`. Stable across factory resets, **not secret** (it's a
  username, not a password).
- **Device credential**: 256-bit random token generated **server-side** at
  claim time, delivered once to the device over the claim-poll response (TLS),
  stored in NVS on the device, stored **only as SHA-256 hash** server-side.
  Presented as `Authorization: Bearer <token>` on every device API call.
- **Claim code**: 8 chars from an unambiguous alphabet
  (`ABCDEFGHJKMNPQRSTUVWXYZ23456789`, no 0/O/1/I/L), shown as `XXXX-XXXX`.
  ~2.8×10¹² combinations. TTL 10 minutes, single-use, rate-limited
  (5 attempts/min/IP), compared in constant time.

### 3.2 Pairing flow (the whole dance)

```
DEVICE (unpaired)                          SERVICE                    WEB CONSOLE
     |                                        |                            |
     |-- WiFi (captive portal if needed) --->|                            |
     |-- POST /v1/device/register {device_id, panel, fw} -->|             |
     |<-- 201 {claim_code, claim_url, poll_interval} -------|             |
     |-- e-ink: QR(claim_url) + "XXXX-XXXX" + instructions |             |
     |   (polls POST /v1/device/claim every 10 s)          |              |
     |                                        |<-- user signs in (Google)|
     |                                        |<-- enters XXXX-XXXX ------|
     |                                        |-- binds device->user ---->|
     |<-- 200 {device_token, device_id} ------|   (token shown NEVER again)|
     |-- stores token in NVS, reboots ------->|                            |
     |-- normal mode: Bearer token from here on                            |
```

- The claim poll response is identical (HTTP 200, `{"status":"pending"}`) until
  approval — no oracle for guessing codes.
- Unapproved claims expire after 10 min; the device then shows a fresh code
  (button 1) — no stale codes lying around.
- **Unpair** (web console or 10-s button hold with on-screen confirm): server
  deletes the token hash, device wipes NVS → back to pairing screen. A stolen
  device is bricked remotely in one tap.

### 3.3 Auth realms (no mixing)

| Caller | Credential | Verifier | Can access |
|---|---|---|---|
| Human browser | Session cookie (`httpOnly`, `Secure`, `SameSite=Lax`) minted after verified Google ID token; CSRF token on mutations | Server | Own user record, own devices, own photos |
| Device | `Authorization: Bearer <256-bit token>` | Server: SHA-256 → device lookup | **Only** its own `/v1/device/*` endpoints |

Rules:
- A device token never grants access to another device's data or to any
  user-scoped endpoint. Every device endpoint resolves token → device → owner
  and 404s otherwise (404, not 403, to avoid leaking device existence).
- A human session never grants access to device credentials; the token is shown
  zero times after issuance (only its last-4 for identification).
- All device traffic is HTTPS with **validated** certificates (CA bundle).
  `setInsecure()` is removed from the firmware entirely.

### 3.4 API contract v2 (extends PROTOCOL.md)

Human (session cookie):
- `GET /` → web console (redirects to `/login` when signed out)
- `GET /login`, `POST /api/auth/google` (ID token → session), `POST /api/auth/logout`
- `GET /api/devices` — my devices (id, name, panel, fw, last_seen, battery, source summary)
- `POST /api/devices/claim` `{code}` — claim a device to my account
- `PATCH /api/devices/{id}` — rename, set source, set refresh interval
- `DELETE /api/devices/{id}` — unpair (rotates token server-side)
- `POST /api/devices/{id}/photos/upload` — local file → that device's library
- `POST /api/devices/{id}/photos/upload` — phone upload → sets the **pinned
  override** (force-push, §3.6); takes precedence over the assigned source
- `DELETE /api/devices/{id}/photos/override` — clear the override, resume source
- `POST /api/devices/{id}/photos/refresh` — force re-render now
- `GET /api/devices/{id}/preview` — what the device currently shows

Device (Bearer token):
- `POST /v1/device/register` — **unauthenticated**, rate-limited; returns claim code. (The only unauthenticated device endpoint.)
- `POST /v1/device/claim` `{device_id, claim_code}` — poll; pending or credentials.
- `GET /v1/device/frame` — `If-None-Match` supported; returns the packed-4bpp frame **for that device** (per-device ETag).
- `POST /v1/device/status` — heartbeat: battery, rssi, fw version, current etag.

### 3.5 Photo pipeline per device (human-out-of-loop refresh)

Each device has an **assigned source** (chosen in the console): Google Photos
album cache, uploaded set, URL template, or dashboard. The server keeps
**per-device** rotation state (`seen.json` per device) and a per-device ETag.

Device wake cycle (unchanged rhythm, hardened transport):
wake → Wi-Fi → NTP → `GET /v1/device/frame` with Bearer token + `If-None-Match`
→ 304 (nothing new, back to sleep) or 200 (new frame, display, store ETag) →
deep sleep until next interval. The "automatic pull" is exactly this: the
server rotates the device's unseen-first queue on its own schedule, so every
wake can yield a fresh photo with nobody touching a phone.

Google Photos stays a **manual-pick-and-cache** flow (Picker API limitation,
unchanged) — but the *picking* is per user in the console, and the *serving* to
each device is automatic afterwards.

### 3.6 Priority override ("force push" from the phone)

From the web console (signed in), Chirag can upload a photo from his phone and
**force it onto a device immediately**, overriding whatever source is assigned
(Google Photos feed, etc.).

Honest physics note: the device deep-sleeps between wakes, so nothing can wake
its radio remotely. "Push" therefore means: the upload **instantly becomes the
device's current frame server-side** (a pinned override that takes precedence
over the rotation queue), and the device picks it up at its **next scheduled
wake**. Delivery latency = one wake interval. The console shows the device's
last-seen time and next expected check-in so the wait is visible, not mysterious.

- The override pins until Chirag clears it (or uploads a replacement) — it does
  not expire on its own and is not consumed by one display.
- Clearing the override resumes the assigned source where its rotation left off.
- `POST /api/devices/{id}/photos/upload` sets the override;
  `DELETE /api/devices/{id}/photos/override` clears it;
  `GET /api/devices/{id}/preview` reflects the override.

## 4. Plan review & risk assessment

**Reviewed against the hard requirement** ("no access without pairing"):

1. *Can an unpaired device read frames?* No — `/v1/device/frame` requires a
   Bearer token that only exists after a signed-in user claims the device.
2. *Can someone guess a claim code?* 8 chars ≈ 43 bits of entropy, 10-min TTL,
   5 tries/min/IP rate limit. Expected guesses in window: ~3000 — success
   probability ≈ 10⁻⁹. Even on success, the attacker only *registers* the
   device to their own account; they learn nothing about Chirag.
3. *Can a device token be replayed from another network?* Yes if stolen — that
   is what tokens are for — but theft requires physical access (NVS dump) or a
   TLS break (mitigated by CA-bundle validation). Unpair revokes instantly.
4. *Can a malicious server impersonate the service to the device?* Only with a
   CA-signed cert for our hostname — mitigated by full-chain validation; the
   old `setInsecure()` path is deleted.
5. *Can one user's device see another's photos?* Token → device → owner lookup
   on every request; device IDs are non-enumerable for data access (404 on
   mismatch). Firestore rules mirror this: `request.auth.uid == resource.data.owner`.
6. *Session theft?* `httpOnly`+`Secure`+`SameSite=Lax` cookies, CSRF tokens on
   state-changing routes, 24-h session expiry with re-verification.
7. **Residual risk (accepted, documented):** a device on an attacker-controlled
   Wi-Fi network during *initial* pairing shows its claim code on its own
   screen — physical proximity is required to exploit it, same as Chromecast.

**Alternatives considered and rejected:**
- mTLS with per-device client certs: stronger, but ESP32 client-cert management
  + rotation is heavy for v1; Bearer-over-validated-TLS matches Tesserae-class
  projects and is sufficient at this scale. Revisit if fleet > 20 devices.
- MQTT push instead of HTTPS pull: the device deep-sleeps; nothing can push to
  a sleeping radio. Pull-on-wake is the only pattern that fits the power
  budget. (Tesserae's ESP32 client does the same.)
- Keeping everything LAN-only: contradicts "pull automatically" from anywhere
  and the Firebase/hosted-service requirement.

## 5. Gap analysis — existing code vs. this plan

### Firmware (`~/workspace/spectra-frame/src/`)

| Needed | Today | Gap |
|---|---|---|
| Pairing-mode UI (claim code + QR on e-ink) | Status screens only | **New**: `ui/PairingScreen`, QR via vendored Nayuki qrcodegen |
| Claim polling + NVS credential store | Config has only `deviceName` | **New**: `app/PairingManager`, NVS keys for `device_id`/`token`/`server_url` |
| Bearer token on requests | Only spoofable `X-Device-Id` header | **Change** `FrameFetcher` → `Authorization: Bearer` |
| Validated TLS | `setInsecure()` | **Change**: CA bundle via `setCACertBundle()`; fail closed if validation fails |
| Factory-reset / unpair UX | None | **New**: long-press flow with on-screen confirm |

Unchanged: deep-sleep cycle, 4bpp pipeline, ETag/304 logic, OTA (OTA also moves
to Bearer auth + validated TLS).

### Service (`~/workspace/spectra-frame/server/`)

| Needed | Today | Gap |
|---|---|---|
| Google sign-in + sessions | None (open server) | **New**: `auth.py` — ID-token verification per §2.2, session cookies, CSRF |
| Device registry + token hashes | None | **New**: `devices.py` — register/claim/revoke, SHA-256 token storage |
| Per-device photo state | Single global source/state | **Change**: rotation state + ETag keyed by device_id |
| Storage abstraction (JSON now, Firestore later) | Direct JSON files | **New**: `store.py` interface with `JsonStore` impl; `FirestoreStore` later |
| Per-user Google Photos OAuth | Single global token file | **Change**: tokens keyed by user `sub` |
| Web console pairing/management UI | Source cards only | **Extend**: login, device list, claim page, per-device config |

### PROTOCOL.md
Bump to **v2**: adds `POST /v1/device/register`, `POST /v1/device/claim`,
`Authorization: Bearer` on all device endpoints, per-device ETags, and the
human session endpoints. v1 (anonymous `/frame`) is removed, not deprecated —
keeping it would violate the hard requirement.

## 6. Execution phases (after plan approval)

- **Phase 0 — Contract.** Write PROTOCOL v2. No code. (Review gate: Chirag signs
  off on the API + security rules in §3.)
- **Phase 1 — Service auth.** `auth.py` (Google ID-token verify, sessions,
  CSRF), `devices.py` (registry, claim codes, token hashing), `store.py`
  abstraction. Tests: forged-token rejection, expiry, claim-code entropy/TTL,
  cross-device 404s. The web console gains login + device list + claim page.
- **Phase 2 — Firmware pairing.** `PairingManager`, `PairingScreen` + vendored
  qrcodegen, Bearer auth in `FrameFetcher`, CA-bundle TLS (fail closed),
  NVS credentials, factory-reset UX. Tests: native suite extended; hardware
  checklist re-run.
- **Phase 3 — Per-device management.** Per-device sources/ETags, per-user
  Google Photos tokens, upload/preview/refresh in the console.
- **Phase 4 — Hosting + hardening (code complete 2026-10-02, deploy pending).**
  Firebase backend implemented behind the storage/auth/blob abstractions:
  Firestore (`store.py:FirestoreStore`), Cloud Storage (`blobs.py:GCSBlobStore`),
  Firebase Auth ID-token verification (`auth.py`, provider `firebase`), Hosting
  rewrites → Cloud Run (`firebase.json`), deny-all Firestore/Storage rules,
  lazy rotation for scale-to-zero, OAuth tokens in Firestore. Local dev without
  `firebase.project_id` is byte-for-byte the old behavior. Runbook:
  `docs/FIREBASE.md`. Blocked on: Firebase project creation + Blaze upgrade
  (billing attach — Chirag's click). After deploy, run the §4 checklist as
  live adversarial tests.
- **Phase 5 (later, optional).** Docker-Compose self-hosted variant for the
  home lab once umbrelOS lands.

**Estimate:** Phases 0–3 are the build; Phase 4 is deploy + adversarial test.
No calendar promises — each phase reports its verification before the next
starts, per the standing proof-checklist rule.

## 7. Decisions (recorded 2026-10-02)

1. **Hosting: Firebase.** Proceeding with Firebase (Cloud Run + Firestore;
   sign-in is direct Google ID-token verification with each user's own OAuth
   client -- no Firebase Authentication setup);
   keeping the server portable via the storage abstraction so a self-hosted
   Docker variant stays possible. If any Firebase step proves hard, flag it
   instead of pushing through.
2. **One device ↔ one user, strictly.** A device has exactly one owner at any
   time. Claiming an already-paired device fails unless the current owner
   unpairs it first (or the device is factory-reset, which revokes its token).
   Re-claiming transfers ownership: the old token is revoked atomically at
   claim time, so there is never a moment with two owners.
3. **Scope:** single-user allowlist (Chirag) with multi-user-capable schema —
   **superseded 2026-10-04 by the bring-your-own-OAuth decision:** the admin
   configures zero OAuth; each user brings their own Google OAuth client via
   the public welcome page. Accounts are per-user by construction (own client,
   own Photos tokens/cache, own devices, own source). `auth.allowlist`
   remains as an optional email gate (empty = anyone may sign in; recommended:
   Chirag-only for his deployment).
4. **Google Photos:** Picker-only for v1 — **confirmed** 2026-10-02.
5. **Force push (2026-10-02):** uploading a photo from the phone (signed in)
   must be able to override the device's assigned source immediately (§3.6).
   Implemented as a server-side pinned override; delivery latency = one device
   wake interval (deep sleep makes true remote wake impossible — documented
   honestly in the console UI).
