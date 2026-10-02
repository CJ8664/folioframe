# Google Photos setup

The server pulls your photos through Google's **Picker API** — a
Google-hosted photo picker where you choose which photos the frame may use.

## Honest limits (read first)

- **Manual pick, not live album sync.** Google removed third-party
  full-library access on March 31, 2025. No app — ours or anyone's — can
  "sync my album" anymore through the official API. You pick photos once
  (or whenever you want more); the server caches originals locally and the
  frame rotates from that cache.
- Picked download URLs expire after ~1 hour; the server downloads originals
  immediately, so this doesn't matter after import.
- Sessions expire if you don't finish picking; just start a new pick.

## One-time Google Cloud setup (5 minutes)

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
   - Authorized redirect URIs: add
     `http://localhost:8765/api/gphotos/callback`
     (use your server's port if you changed it in `config.json`)
5. Copy the **Client ID** and **Client secret**.

## Connect the server

1. In `server/config.json`, add:
   ```json
   "google_photos": {
     "client_id": "YOUR_ID.apps.googleusercontent.com",
     "client_secret": "YOUR_SECRET"
   }
   ```
2. Restart the server, open its web UI, and click **Connect Google Photos**.
3. Approve the consent screen. The server stores tokens in
   `server/.gphotos_token.json` (mode `0600`, gitignored).
4. Click **Pick more photos** → open the picker link → select photos → Done.
   The server polls, downloads originals into `server/data/gphotos/`, and
   the `google_photos` source rotates from that cache.
5. Switch the active source to `google_photos` in the web UI.

## Headless servers

The OAuth callback goes to `localhost:<port>` **of the machine whose browser
you use**. If the server runs on another box (Pi, NAS), either open the web
UI in a browser on that box, or forward the port over SSH:
`ssh -L 8765:localhost:8765 pi@your-server`.

## Disconnect

Click **Disconnect** in the web UI (deletes local tokens), and optionally
revoke access at [myaccount.google.com/permissions](https://myaccount.google.com/permissions).
