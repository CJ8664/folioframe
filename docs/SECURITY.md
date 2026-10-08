# SpectraFrame security

This is the whole threat model on one page: what's protected, how, and
what we knowingly don't protect. If you find a hole in the "protected"
column, that's a bug — please report it.

## The shape of the system

Three parties: **your server** (you run it), **your frame** (on your wall),
**your browser** (the web console). There is no SpectraFrame cloud. An
attacker is anyone on the internet who finds your server's address.

## What's protected

**No anonymous access to anything.** The welcome page is the only public
route. Every frame, photo, and device control needs authentication.

**Devices** authenticate with a per-device 256-bit Bearer token:

- Issued once, at pairing, via a claim code (`XXXX-XXXX`) shown on the
  e-ink screen. 8 characters from an unambiguous alphabet (~43 bits of
  entropy), 10-minute TTL, single-use, constant-time comparison.
- `POST /v1/device/register` and `/v1/device/claim` are rate-limited
  (5/min per IP). Wrong codes get the identical response as "not yet
  claimed" — there's no oracle for guessing.
- Only the SHA-256 hash is stored server-side. The plaintext exists only
  between claim approval and the device's first poll, then is wiped.
- One device ↔ one user, strictly. Re-pairing revokes the old token
  atomically; unpairing (from the console or the device itself) revokes it
  immediately.

**Humans** authenticate with Google sign-in:

- The server verifies the Google ID token cryptographically: signature via
  Google's JWKS, `aud` == the service's own OAuth client ID, `iss` is
  Google, `exp` not passed, `email_verified`. A decoded-but-unverified JWT
  is never trusted.
- Sessions are server-side, 24-hour TTL, with an HMAC-signed cookie
  (`HttpOnly`, `Secure`, `SameSite=Lax`).
- Every state-changing web route requires a per-session CSRF token.
- An optional email allowlist restricts who may sign in. Without it,
  anyone with a Google account can create an account — but accounts are
  fully isolated (see below), so an open server leaks nothing across users.

**Per-user isolation.** Google Photos OAuth tokens, the photo cache, and
devices are all keyed by the Google `sub`. One user's tokens and photos are
never visible to another.

**Input hardening.**

- JSON request bodies capped at 1 MB; photo uploads at 25 MB.
- Image decodes capped at 50 megapixels (a 25 MB PNG can hide gigapixels).
- Google Photos and URL-source downloads are capped at 25 MB each.
- Device-reported telemetry (battery, signal, firmware version) is clamped
  to sane types and ranges at ingestion, so a rogue device can't stash
  markup that renders in the console. User-controlled strings in the
  console are HTML-escaped.
- Static files can't traverse out of `server/static/`.
- OAuth provider errors shown in the browser remain generic; provider details
  stay in the server log. If the service OAuth client is missing, the welcome
  page now tells the administrator which config keys to set.

**Storage.** The registry (users, devices, token hashes) is written
atomically with mode `0600`. OAuth tokens live in the same store, per user.

## Known tradeoffs (accepted, documented)

- **The device skips TLS certificate validation** (`setInsecure()`). The
  ESP32-S3 has no maintained CA bundle, so the link is encryption-only.
  Pair over a server you trust. Compensating: the Bearer token is useless
  to a passive observer beyond what the frame displays, and OTA binaries
  are MD5-verified against the server manifest when a hash is published.
  Contributions welcome.
- **Physical access to the frame** exposes its NVS-stored token (readable
  with a USB cable). It's a picture frame on your wall; the pairing secret
  is the claim code on its screen, and the owner can unpair/revoke anytime.
- **Behind a reverse proxy or tunnel**, the rate limiter sees one client
  IP, so per-IP limits behave as a global brake. Fine for a personal
  server; tune `RATE_LIMIT` in `server/devices.py` if you expose it widely.
- **Whoever administers your hosting** (e.g. Portainer) can read the Google
  OAuth client secret from the server config. That's inherent to
  self-hosting — keep admin access tight.

## Reporting

Open an issue with the details. If it's actively exploitable, say so in
the title and we'll prioritize it.
