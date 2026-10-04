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

## Deploy

```bash
git clone https://github.com/CJ8664/spectra-frame.git
cd spectra-frame
cp server/config.json.example server/config.json
# edit server/config.json:
#   public_url  -> your public HTTPS URL
#   auth.client_id -> your OAuth client ID
#   auth.allowlist -> ["you@example.com"]  (empty = any Google account)
#   google_photos.client_id / client_secret -> same OAuth client
docker compose up -d --build
```

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
