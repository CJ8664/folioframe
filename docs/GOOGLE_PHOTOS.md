# Google Photos setup

The server pulls your photos through Google's **Picker API** — a
Google-hosted photo picker where you choose which photos the frame may use.

## Model: one service OAuth client, per-user data

The admin configures **one** Google OAuth client once, in the server
config. Every user then gets the familiar two-step flow and never sees
any Cloud Console, client IDs, or secrets:

1. Click the normal **Sign in with Google** button.
2. On the console, click **Connect Google Photos** and approve Google's
   consent screen.
3. Click **Pick more photos** → open the picker link → select photos →
   Done. The server polls, downloads originals into your private cache,
   and your `google_photos` source rotates from it (unseen-first).

Each user's tokens and photo cache stay isolated per Google account —
nobody else's photos are visible to you, and yours aren't visible to
them.

## One-time Google Cloud setup (admin only, ~5 minutes)

Done once per deployment, never per user:

1. In the [Google Cloud Console](https://console.cloud.google.com/),
   enable the **Photos Picker API** on your project (not "Photos Library
   API" — that's the restricted one).
2. **APIs & Services → OAuth consent screen**: External, app name, your
   email.
3. **APIs & Services → Credentials**: create a **Web application** OAuth
   client. Register the site's `/api/gphotos/callback` redirect URI.
4. Put the client ID and a client secret under `"google"` in
   `SPECTRA_CONFIG_JSON` (see `server/config.json.example`).

For a personal/family deployment the OAuth consent screen may stay in
Testing mode (add each user's account under **Test users**); Google
deletes testing-mode refresh tokens after 7 days, so for a long-lived
frame set the consent screen to **Production**.

## Honest limits (read first)

- **Manual pick, not live album sync.** Google removed third-party
  full-library access on March 31, 2025. No app — ours or anyone's — can
  "sync my album" anymore through the official API. You pick photos once
  (or whenever you want more); the server caches originals locally and the
  frame rotates from that cache.
- Picked download URLs expire after ~1 hour; the server downloads originals
  immediately, so this doesn't matter after import.
- Sessions expire if you don't finish picking; just start a new pick.

## Headless servers

The OAuth redirect URI is derived from the address **your browser** uses to
open the console (`location.origin`). If the server runs on another box,
open the console via an address your browser can reach (LAN IP, Tailscale
name, or public URL) and register that origin's `/api/gphotos/callback` —
no SSH tunnel needed.

## Disconnect

Click **Disconnect** in the web UI (deletes local tokens), and optionally
revoke access at [myaccount.google.com/permissions](https://myaccount.google.com/permissions).
