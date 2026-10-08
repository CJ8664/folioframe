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
   `https://github.com/CJ8664/folioframe`, compose path
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
git clone https://github.com/CJ8664/folioframe.git
cd folioframe
cp server/config.json.example server/config.json
# edit server/config.json:
#   public_url  -> your public HTTPS URL
#   auth.allowlist -> ["you@example.com"]  (empty = any Google account;
#                     NOT OAuth setup, just an email list)
#   google.client_id / google.client_secret -> the service's one OAuth
#                     client (create once in Google Cloud Console)
export SPECTRA_CONFIG_JSON="$(cat server/config.json)"
docker compose pull
docker compose up -d
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
docker compose pull
docker compose up -d
```

Your data (devices, pairings, photos) lives in the `spectra-data` volume
and survives image updates. For a local source build, use
`docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build`.

## GitHub Actions deployment

The server workflow builds and publishes the public
`ghcr.io/cj8664/folioframe` image, then asks Portainer CE to pull and redeploy
the configured stack. Configure these repository settings before enabling
production deployment:

- Secret `PORTAINER_API_KEY`: a Portainer API access token.
- Variable `PORTAINER_URL`: the Portainer API base URL, without a trailing
  slash.
- Variable `PORTAINER_ENDPOINT_ID`: the numeric Docker endpoint ID.
- Variable `PORTAINER_STACK_ID`: the numeric stack ID.
- Set the GHCR package visibility to **public** so the stack can pull the
  image without registry credentials.
- Optional `TRUSTED_PROXY_IPS`: comma-separated exact IP addresses of the
  reverse proxies directly connecting to the container. Requests from those
  peers may use `X-Forwarded-For` for per-client rate limits. Keep this list
  limited to trusted proxy addresses; do not add public or untrusted peers.

Only server code/assets and deployment configuration trigger the server
workflow. Firmware-source changes run a separate build/release workflow;
pull requests touching firmware paths only compile and never deploy.
After Portainer redeploys, the workflow checks `GET /healthz` for up to five
minutes.

## Backup

```bash
docker run --rm -v spectraframe_spectra-data:/data -v "$PWD":/backup \
  alpine tar czf /backup/spectra-data-$(date +%F).tgz /data
```

Keep `server/config.json` backed up too — it holds your OAuth client secret.

## Notes

- The device needs to reach the service too: set its server URL (in the
  Wi-Fi portal at `http://192.168.4.1` on first boot, or later via the
  portal) to the same public HTTPS host. First boot shows a claim code on
  the e-ink screen — enter it at `<your-url>/claim` in the console.
- Logs: `docker compose logs -f spectraframe`.
- The container writes structured JSON request/application logs to stdout;
  set `LOG_LEVEL` to adjust verbosity. `GET /healthz` is the lightweight
  liveness endpoint used by the container health check.
- Resource use is tiny: the container idles near zero and wakes to render
  frames on the rotation interval.

## Publishing firmware (OTA + web flash)

Firmware builds and server deployments are independent. On `main`, changes to
firmware source paths run the firmware workflow: it builds `ee02`, runs
`tools/package_firmware.sh`, and publishes a GitHub Release named
`folioframe-vX.Y.Z` using the manually maintained `FW_VERSION` and `FW_BUILD`
in `src/main.cpp`.

The server checks GitHub Releases in the background at startup. The public
`/flash` page also has **Check for firmware updates**, which calls
`POST /api/firmware/refresh`. This public, rate-limited endpoint is available
without a login so the public flasher can refresh its listing. The server
validates release metadata and firmware images before installing them and
keeps prior versioned binaries so the `/flash` version picker remains usable.
This flow does not require a Docker image rebuild or Portainer redeploy.

The `firmware` named volume persists across server redeploys. On first mount,
Docker seeds it from the image; subsequent GitHub Release refreshes update the
firmware files in that volume without removing older versions or replacing the
web-flash bootloader/partition assets.

Then two things work:

- **Web flash** — the server's public `/flash` page (no login) offers a
  browser-based USB flasher (esp-web-tools, self-hosted). Anyone can flash
  a frame and then point it at any SpectraFrame server in its Wi-Fi portal.
  The page hides itself until all four binaries exist.
- **OTA** — devices check `GET /v1/device/ota/version` on every wake.
  When the server's build number is higher than theirs, they download
  `firmware.bin`, verify its MD5 against the manifest, and flash it —
  never on a low battery. No binary published → the version endpoint just
  reports the build number and nothing happens.
