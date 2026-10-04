# Google Photos setup

The server pulls your photos through Google's **Picker API** — a
Google-hosted photo picker where you choose which photos the frame may use.

## Model: bring your own OAuth client

The admin configures **no** OAuth. Each user creates one Google OAuth
client (once, ~5 minutes) and uses it for both sign-in and Photos. Your
client secret, tokens, and photo cache are yours alone — never shared
with other accounts on the same server.

## One-time Google Cloud setup (5 minutes, per user)

You do steps 1–4 **before** signing in — the welcome page walks you
through them and shows the exact redirect URI for the deployment
(`<this-site>/api/gphotos/callback`).

1. Go to the [Google Cloud Console](https://console.cloud.google.com/) and
   create a project (any name, e.g. `spectra-frame`).
2. **APIs & Services → Library**: search for **Photos Picker API** and enable
   it. (Not "Photos Library API" — that's the restricted one.)
3. **APIs & Services → OAuth consent screen**: choose **External**, fill in
   the app name and your email. On the scopes step you don't need to add
   anything manually. Save.
   - While in **Testing** mode, add your Google account under **Test users**.
     (Publishing the app removes this step but requires verification.)
4. **APIs & Services → Credentials → Create Credentials → OAuth client ID**:
   - Application type: **Web application**
   - Authorized redirect URIs: add the URI shown on the welcome page
     (`http://localhost:8765/api/gphotos/callback` for local dev)
5. Copy the **Client ID** — paste it on the welcome page and sign in.

## Connect Photos (after sign-in)

1. Open your **account page** (the console). Under Google Photos you'll see
   your sign-in client ID — paste that client's **client secret** and save.
   (Write-only: it's stored server-side and never shown again.)
2. Click **Connect Google Photos** and approve the consent screen.
3. Click **Pick more photos** → open the picker link → select photos → Done.
   The server polls, downloads originals into your private cache, and your
   `google_photos` source rotates from it (unseen-first).
4. Switch your photo source to `google_photos` in the console.

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
open the console (`location.origin`), and the welcome page shows it to you.
If the server runs on another box, open the console via an address your
browser can reach (LAN IP, Tailscale name, or public URL) and register that
origin's `/api/gphotos/callback` — no SSH tunnel needed.

## Disconnect

Click **Disconnect** in the web UI (deletes local tokens), and optionally
revoke access at [myaccount.google.com/permissions](https://myaccount.google.com/permissions).
