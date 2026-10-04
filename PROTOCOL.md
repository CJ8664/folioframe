# SpectraFrame Device ↔ Server Protocol v2.1

Replaces v1. The anonymous `GET /frame` is **removed** — every device endpoint
requires authentication, and every human endpoint requires a signed-in session.
There is no unauthenticated path to any frame, photo, or device control.

v2.1 change: **bring-your-own OAuth.** The admin configures zero OAuth. Each
user brings their own Google OAuth client ID (one-time setup via the public
welcome page); the server verifies ID tokens against the user's own client.
Google Photos credentials, tokens, and photo cache are per-user and isolated.

Small, versioned HTTP contract. Any server can feed the frame by implementing it.

## Identities

- `device_id`: `sf-` + lowercase 12-hex-digit ESP32-S3 MAC, e.g. `sf-94a9a811c2f4`.
  A username, **not** a secret.
- Device credential: 256-bit random Bearer token, issued by the server at claim
  time, stored hashed (SHA-256) server-side. Sent as
  `Authorization: Bearer <token>` on every device request.
- Human: Google account, via the user's **own** OAuth client (bring-your-own;
  entered once on the public welcome page). The server verifies the Google ID
  token (signature via Google JWKS, `aud` == the user's client ID,
  `iss` is Google, `exp` not passed, `email_verified`), then mints an
  `httpOnly` + `Secure` + `SameSite=Lax` session cookie. The Google `sub`
  claim is the stable user key. The account is bound to the client ID it was
  created with (rotatable from the account page).
- **One device ↔ one user, strictly.** A device has exactly one owner at any
  time. Claiming an already-paired device fails unless the owner unpaired it
  first (or the device was factory-reset, which revokes its token).

## Pairing (claim-code flow)

```
DEVICE                                        SERVER                    CONSOLE
  |-- POST /v1/device/register ---------------→|                            |
  |   {device_id, panel, fw}                   |                            |
  |←-- 201 {claim_code, expires_in} -----------|                            |
  |   (shows QR + XXXX-XXXX on e-ink;          |                            |
  |    polls POST /v1/device/claim every 10s)  |                            |
  |                                            |←-- signed-in user enters --|
  |                                            |   code at /claim          |
  |                                            |-- binds device → user ----→|
  |←-- 200 {status:"claimed",                  |                            |
  |         device_token, device_id} ----------|                            |
  |   (stores token in NVS, reboots to normal mode)                         |
```

- `POST /v1/device/register` is the **only** unauthenticated device endpoint.
  Rate-limited (5/min/IP). Re-registering an already-paired device issues a
  fresh code but keeps the old token valid until the new claim completes —
  ownership transfer requires physical access to read the new code.
- Claim codes: 8 chars from `ABCDEFGHJKMNPQRSTUVWXYZ23456789`, shown as
  `XXXX-XXXX`. TTL 10 minutes, single-use, constant-time comparison.
- The claim poll returns `{"status":"pending"}` until approval — identical
  shape for bad codes (no guessing oracle). The token is delivered **once**;
  after delivery the code is burned.
- Unpair: console `DELETE /api/devices/{id}` (owner only), or the device
  itself `POST /v1/device/unpair` (Bearer; used by factory reset). Both revoke
  the token immediately.

## Device API (all require `Authorization: Bearer <token>`)

| Method | Path | Notes |
|---|---|---|
| `POST` | `/v1/device/register` | unauthenticated, rate-limited; starts claim flow |
| `POST` | `/v1/device/claim` | `{device_id, claim_code}`; `pending` or `claimed`+token |
| `GET` | `/v1/device/frame` | packed-4bpp frame **for this device**; `If-None-Match` → `304` |
| `POST` | `/v1/device/status` | heartbeat `{battery_mv, battery_pct, rssi, fw}` |
| `POST` | `/v1/device/unpair` | device-initiated unpair (factory reset) |
| `GET` | `/v1/device/ota/version` | plain-text build number |
| `GET` | `/v1/device/ota/firmware.bin` | ESP32 app image (when published) |

Auth failures return `401`; a valid token addressing anything outside its own
device returns `404` (never `403`, to avoid leaking device existence).

### Frame fetch

**Request headers (device → server):**

| Header | Example | Purpose |
|---|---|---|
| `Authorization` | `Bearer <256-bit token>` | device identity (required) |
| `X-Device-Panel` | `gdeb0709e01` | panel kind; server picks correct variant |
| `X-Device-Width` / `X-Device-Height` | `1200` / `1600` | panel-native geometry |
| `X-Firmware-Version` | `2.0.0` | fleet views |
| `If-None-Match` | `"abc123"` | sent when the device has a cached ETag |

**Success response:**

| Header | Value |
|---|---|
| `200 OK` | |
| `Content-Type` | `application/octet-stream` |
| `ETag` | opaque version string, quoted (per-device) |
| `X-Frame-Format` | `packed4bpp` |

Body: exactly `width × height / 2` bytes (960 000 for 1200×1600).
**Packed 4bpp layout:** two pixels per byte, high nibble first, rows top→bottom,
left→right. Nibble values: `0x0` white, `0x2` green, `0x6` red, `0xB` yellow,
`0xD` blue, `0xF` black (UC8179 hardware codes).

**Not-modified:** `304 Not Modified` (no body) → device skips the ~30 s panel
refresh and goes back to sleep. This is the single biggest power saver.

**Transport:** HTTPS only, with full certificate-chain validation on the
device (CA bundle). `setInsecure()` and plain HTTP are not permitted.

**Errors:** `4xx/5xx` → device keeps the current image, backs off, retries next
wake. `404` with an empty queue is normal: keep image, sleep.

## Human API (all require signed-in session; mutations require CSRF token)

| Method | Path | Notes |
|---|---|---|
| `GET` | `/` | **public** welcome page (setup steps + sign-in); console when signed in |
| `GET` | `/login` | redirects to `/` (kept for old bookmarks) |
| `POST` | `/api/auth/token` | `{id_token, client_id}` → session cookie (client is the user's own) |
| `POST` | `/api/auth/logout` | destroys session |
| `GET` | `/claim` | enter a device claim code |
| `GET` | `/api/session` | `{email, csrf}` for the console JS |
| `GET` | `/api/account` | account: email, client ID, source, Photos state |
| `PATCH` | `/api/account/client` | rotate the account's OAuth client ID |
| `GET` | `/api/devices` | my devices + status |
| `POST` | `/api/devices/claim` | `{code}` → claims device to me |
| `PATCH` | `/api/devices/{id}` | rename |
| `DELETE` | `/api/devices/{id}` | unpair (revokes token) |
| `POST` | `/api/devices/{id}/photos/upload` | multipart photo → **pinned override** (force push) |
| `DELETE` | `/api/devices/{id}/photos/override` | clear override, resume assigned source |
| `GET` | `/api/devices/{id}/preview` | PNG of what the device currently shows |
| `POST` | `/api/gphotos/setup` | `{client_secret}` — the user's own (write-only) |
| `GET` | `/api/gphotos/connect` | → Google consent (user's client; `?origin=` validated) |
| `GET` | `/api/gphotos/callback` | OAuth callback (per-user, state-bound redirect) |
| `GET` | `/api/gphotos/status` | per-user Photos state (secret never exposed) |
| `POST` | `/api/gphotos/pick` | start a picker import (per user) |
| `POST` | `/api/gphotos/disconnect` | revoke per-user Photos tokens |
| `POST` | `/api/next` | rotate my devices' frames now |
| `POST` | `/api/source` | `{name}` — set my photo source |

## Priority override ("force push")

Uploading a photo from the console pins it as the device's current frame
**immediately, server-side**, overriding the assigned source (Google Photos
feed, etc.). The device picks it up at its next scheduled wake — delivery
latency is one wake interval, because a deep-sleeping radio cannot be woken
remotely. The override pins until cleared or replaced; clearing resumes the
assigned source where its rotation left off.

## Versioning

The major version in this document's title is the contract version. Breaking
changes bump it; the device sends `X-Frame-Format` and firmware version so the
server can reject mismatches explicitly.
