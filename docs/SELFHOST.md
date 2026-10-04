# SpectraFrame self-hosting guide (Docker)

The service is a single Python container with zero cloud dependencies by
default: local JSON registry, on-disk photo storage, Google sign-in verified
directly against Google's keys. Firebase is strictly opt-in
(`docs/FIREBASE.md`); nothing here needs it.

## What you need

- Any Docker host: umbrelOS, a Linux box, a VPS. (~300 MB RAM is plenty.)
- A **public HTTPS URL** for the console, e.g.
  `https://frame.example.com`. Google sign-in requires it: the sign-in
  button only works on HTTPS origins registered in your OAuth client, and
  the Photos OAuth callback must be a public HTTPS URL. On umbrelOS the
  usual route is your existing Cloudflare tunnel pointed at the host's
  port 8765.
- A Google OAuth **Web** client (free, one per install):
  https://console.cloud.google.com/apis/credentials
  - Authorized JavaScript origins: `https://frame.example.com`
  - Authorized redirect URIs: `https://frame.example.com/api/gphotos/callback`
    (only needed if you use the Google Photos source)

## Deploy via Portainer

Two options — the web editor is simplest (no git credentials needed):

**Option 1 — Web editor (recommended):**
1. **Stacks → Add stack**, name it `spectraframe`.
2. Build method: **Web editor** — paste the contents of
   [`docker-compose.yml`](../docker-compose.yml).
3. **Environment variables** → add `SPECTRA_CONFIG_JSON` with your full
   config JSON (same keys as `server/config.json.example`: `public_url`,
   `auth`, …).
4. **Deploy the stack**.

**Option 2 — Git repository:**
1. **Stacks → Add stack** → **Repository** → URL
   `https://github.com/CJ8664/spectra-frame`, compose path
   `docker-compose.yml`. (Private repo: add your GitHub personal access
   token under Portainer's git credentials.)
2. Add the `SPECTRA_CONFIG_JSON` environment variable as above.
3. **Deploy the stack**.

If you see an OCI "mount ... not a directory" error about
`server/config.json`: you're on an old compose file that bind-mounted the
config file. Re-paste the current `docker-compose.yml` (no file mounts —
config comes from the env var) and deploy again.

## Deploy via SSH

```bash
git clone https://github.com/CJ8664/spectra-frame.git
cd spectra-frame
cp server/config.json.example server/config.json
# edit server/config.json:
#   public_url  -> your public HTTPS URL
#   auth.allowlist -> ["you@example.com"]  (empty = any Google account;
#                     NOT OAuth setup, just an email list)
#   google.client_id / google.client_secret -> the service's one OAuth
#                     client (create once in Google Cloud Console)
SPECTRA_CONFIG_JSON="$(cat server/config.json)" docker compose up -d --build
```

Open the site: the public **welcome page** has a normal Sign in with
Google button. After sign-in users get their account page: connect Google
Photos with one click, pair devices, push photos. Users never touch any
Cloud Console or OAuth setup.

Open `https://frame.example.com/login`, sign in, pair the device with the
claim code from its screen (`/claim`).

## On umbrelOS specifically

SSH into the umbrel host and run the commands above from any directory
(e.g. `~/spectra-frame`). umbrelOS is Debian-based with Docker preinstalled,
so plain `docker compose` works — no app-store packaging needed.

## Updating

```bash
cd spectra-frame
git pull
docker compose up -d --build
```

Your data (devices, pairings, photos) lives in the `spectra-data` volume
and survives rebuilds.

## Backup

```bash
docker run --rm -v spectraframe_spectra-data:/data -v "$PWD":/backup \
  alpine tar czf /backup/spectra-data-$(date +%F).tgz /data
```

Keep `server/config.json` backed up too — it holds your OAuth client secret.

## Notes

- The device needs to reach the service too: point its server URL at the
  same public HTTPS host. (The firmware side of pairing is Phase 2.)
- Logs: `docker compose logs -f spectraframe`.
- Resource use is tiny: the container idles near zero and wakes to render
  frames on the rotation interval.
