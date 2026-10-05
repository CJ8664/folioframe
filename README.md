# SpectraFrame

An open-source e-paper photo frame: ESP32-S3 firmware plus a self-hosted
companion server. First hardware target: **Seeed XIAO EE02 + Good Display
GDEB0709E01 7.09" Spectra 6** (6-color e-ink).

The frame wakes up, fetches a dithered photo from your server, paints it,
and goes back to deep sleep. That's the whole loop:

```
Wake → Wi-Fi → time → pair (first boot) → OTA → fetch → paint → deep sleep
```

## How it works

- **You run the server** — on a home server, a VPS, anywhere with Python.
  It renders photos into the panel's native format and serves them.
- **The frame pairs with a claim code** — first boot shows `XXXX-XXXX` on
  the e-ink screen; you type it into the web console once. From then on the
  frame authenticates with its own Bearer token. No accounts or passwords
  on the device, ever.
- **Photos come from sources you pick** — Google Photos (via Google's
  Picker API), a local folder, picsum, a URL template, or a clock/weather
  dashboard. You can also push a photo from your phone to pin it immediately.

The HTTP contract is versioned and documented in [PROTOCOL.md](PROTOCOL.md) —
any server can feed the frame, and any frame can talk to the server.

## Quick start

### 1. Run the server

```bash
pip install -r server/requirements.txt   # Pillow + google-auth
python3 server/spectra_server.py         # :8765, writes server/config.json
```

Open `http://localhost:8765`, sign in with Google, and you're in the
console. For Google sign-in and Google Photos you configure **one** Google
OAuth client, once, as the admin — users never touch the Cloud Console.
See [docs/SELFHOST.md](docs/SELFHOST.md) and
[docs/GOOGLE_PHOTOS.md](docs/GOOGLE_PHOTOS.md).

### 2. Flash the frame

1. Install [PlatformIO](https://platformio.org/), open this folder, env `ee02`.
2. **Enable PSRAM** (required — the 960 KB frame buffer lives there).
3. `pio run -t upload`, then `pio device monitor`.
4. First boot: join the `SF-Setup-…` Wi-Fi network, open `http://192.168.4.1`,
   enter your Wi-Fi details **and your server URL**
   (e.g. `https://frame.example.com`).
5. The screen shows a claim code — enter it at `<server>/claim` in the
   console. Done. The frame fetches its first photo and sleeps.

No PlatformIO? If the admin published the binaries, the server's public
`/flash` page (no login) flashes the frame over USB straight from Chrome
or Edge — then point it at any server in its Wi-Fi portal.

## Layout

| Dir | What's inside | Swap rule |
|---|---|---|
| `src/hal/` | `Board` / `Panel` interfaces + EE02 / GDEB0709E01 drivers | New hardware = new subclass, nothing else changes |
| `src/core/` | Scheduler, QuietHours, BatteryCurve, UrlTemplate, OtaManifest, Validate, JsonLite | Pure C++17, no Arduino — natively unit-tested |
| `src/app/` | Config, TimeSync, DeviceClient, FrameFetcher, OtaManager, Portal, PowerManager | Arduino behaviors built from `hal` + `core` |
| `src/ui/` | StatusScreen | On-panel text screens through the `Panel` seam |
| `server/` | The companion server (Python + Pillow) | Implements PROTOCOL.md |

## Security

Short version: no anonymous access to anything. Devices authenticate with a
per-device 256-bit Bearer token from the claim-code pairing flow; humans
with a Google sign-in session (ID token cryptographically verified);
state-changing web routes need a CSRF token; uploads are size-capped;
Google Photos tokens are per-user and isolated. The full model, including
the known tradeoffs (device skips TLS cert validation — see the honest
notes), is in [docs/SECURITY.md](docs/SECURITY.md).

## Verification

- **Firmware unit tests** — `tools/run_tests.sh` (pure `core/`, runs on your
  machine, no hardware)
- **Firmware syntax check** — `tools/stub_compile.sh` (compiles all of
  `src/` against Arduino API stubs)
- **Server tests** — `server/tests/run.sh` (92 cases, incl. HTTP integration)
- **On-device** — [docs/HARDWARE_CHECKLIST.md](docs/HARDWARE_CHECKLIST.md)

## Docs

- [PROTOCOL.md](PROTOCOL.md) — the versioned device↔server contract
- [docs/SECURITY.md](docs/SECURITY.md) — threat model and hardening notes
- [docs/SELFHOST.md](docs/SELFHOST.md) — deploying the server (Docker,
  Firebase/Cloud Run is opt-in)
- [docs/GOOGLE_PHOTOS.md](docs/GOOGLE_PHOTOS.md) — the one-time Google setup
- [docs/HARDWARE_CHECKLIST.md](docs/HARDWARE_CHECKLIST.md) — bringing up the
  EE02 + panel hardware

## License

MIT — see [LICENSE](LICENSE). Self-host it, fork it, sell it; it's yours.
