# AGENTS.md — FolioFrame contributor guide for AI agents

This file is for AI coding agents (and the humans directing them) working on
this repo. Read it before changing anything. It covers what the project is,
how it's built and tested, the architecture, and the traps.

## What this is

FolioFrame is an open-source e-paper photo frame: ESP32-S3 firmware plus a
self-hosted Python companion server. The reference hardware is the
**Seeed XIAO EE02 driver board + Good Display GDEB0709E01 7.09" Spectra 6**
(6-color e-ink, 1200×1600).

The whole loop: `wake → Wi-Fi → time → pair (first boot) → OTA → fetch → paint → deep sleep`.

Two halves, one contract:

- **Firmware** (`src/`, C++/Arduino, PlatformIO env `ee02`) — runs on the frame.
- **Server** (`server/`, Python 3 + Pillow) — renders photos into the panel's
  native format and serves them. Any server implementing PROTOCOL.md can feed
  the frame, and vice versa.

## Quick commands

```bash
pio run -e ee02                    # build firmware
pio run -e ee02 -t upload          # flash over USB
pio device monitor                 # 115200 baud serial
tools/run_tests.sh                 # firmware unit tests (pure core/, host-native)
tools/stub_compile.sh              # compile src/ against Arduino API stubs
server/tests/run.sh                # server tests (incl. HTTP integration)
python3 server/spectra_server.py   # run server on :8765
tools/package_firmware.sh          # package /flash binaries + manifest
```

Docker: `docker compose up --build` (server on :8765). The server writes
`server/config.json` on first run; `server/config.json.example` documents it.

## Architecture

### Firmware (`src/`)

| Dir | Contents | Rule |
|---|---|---|
| `src/hal/` | `Board`/`Panel` interfaces + EE02 / GDEB0709E01 drivers | New hardware = new subclass, nothing else changes |
| `src/core/` | Scheduler, QuietHours, BatteryCurve, UrlTemplate, OtaManifest, Validate, JsonLite | Pure C++17, **no Arduino** — natively unit-tested |
| `src/app/` | Config, TimeSync, DeviceClient, FrameFetcher, OtaManager, Portal, PowerManager | Arduino behaviors composed from `hal` + `core` |
| `src/ui/` | StatusScreen | On-panel text screens through the `Panel` seam |

Key flows: claim-code pairing (`Portal`), authenticated OTA (`OtaManager`,
auto-install default ON, 40% battery gate, MD5 verification, inactive-partition
flash so a failed update keeps the old firmware), photo fetch with
`ETag`/`If-None-Match` (`FrameFetcher` — the ETag header must be collected
before the GET or every wake repaints).

### Server (`server/`)

- `spectra_server.py` — HTTP app: web console, pairing (`/claim`), device API
  (`/v1/device/*`), OTA manifest, public `/flash` page (web-USB flashing).
- `devices.py` — device registry, claim codes, Bearer <redacted>
- `pipeline.py` — photo render pipeline (dither to Spectra 6 palette).
- `sources/` — photo sources: Google Photos (Picker API), local folder,
  picsum, URL template, clock/weather dashboard.
- `auth.py`, `token_store.py`, `blobs.py`, `store.py` — Google OAuth,
  per-user token storage, photo cache.

### The contract

**PROTOCOL.md is law.** The versioned device↔server HTTP contract lives there.
If code and PROTOCOL.md disagree, fix the code (or update the doc deliberately
— never let them drift silently).

## Identity, pairing, security

- **Device ID**: `ff-` + 12 lowercase hex digits of the MAC
  (`src/hal/EE02Board.cpp::deviceId()`). It is a **username, not a secret**.
  The server validates the format strictly (`^ff-[0-9a-f]{12}$`); uppercase or
  short IDs are rejected at register time. Changing the prefix orphans every
  paired device (server treats it as brand-new) — never change it casually.
- **Pairing**: first boot shows a `XXXX-XXXX` claim code on the e-ink screen;
  the human enters it once in the web console. The server issues a 256-bit
  Bearer token, stored in NVS on the device. No accounts or passwords on the
  device, ever.
- **OTA safety**: NVS (Wi-Fi creds, server URL, device token) is untouched by
  firmware updates — pairing always survives OTA.
- **Server auth**: devices use their Bearer token; humans use Google sign-in
  (ID token cryptographically verified); state-changing web routes need CSRF
  tokens; uploads are size-capped.
- **Known tradeoff** (documented in `docs/SECURITY.md`): the device skips TLS
  certificate validation. Don't "fix" this without reading that doc — it's a
  deliberate resource tradeoff on the ESP32-S3, not an oversight.

## Naming: what is branding vs. what is identity

- **User-visible branding is "FolioFrame"** — web UI, PWA manifest, setup AP
  SSID prefix (`FF-Setup-`), on-screen text. If a user can see it, it says
  FolioFrame.
- **Internal identifiers are stable and MUST NOT be renamed**: the `ff-`
  device-ID prefix, NVS namespaces, partition labels, log tags. Renaming them
  wipes devices or forces re-pairing. Treat them like a wire protocol.

## Common tasks

- **Add a photo source**: new file in `server/sources/` following the existing
  source interface; register it where sources are listed; add a test in
  `server/tests/`.
- **Support a new panel/board**: subclass `hal::Panel` / `hal::Board`; wire it
  in `src/hal/`; add a PlatformIO env. Don't touch `core/` or `app/` — that's
  the point of the seam.
- **Change on-device screens**: `src/ui/StatusScreen`. Non-photo status
  screens draw a small bottom-right help QR; the photo display never shows a QR.
- **Web console changes**: the console is server-rendered. Keep the Warm Clay
  light theme / Ink Dark dark-mode styling consistent; repeated UI elements
  must stay at identical positions across screens.
- **Bump firmware version**: human version + monotonic OTA build number in the
  firmware sources, then `tools/package_firmware.sh` and update
  `server/firmware/VERSION`.

## Gotchas

- **PSRAM must be enabled** — the 960 KB frame buffer lives there. Builds
  succeed without it; the frame crashes at runtime.
- **Partition scheme is `default_8MB.csv`** (2 OTA app slots). Don't shrink it.
- **Quiet-hours logic fails open** when clock sync fails (deliberate).
- **Button wake must be re-armed on every sleep/error path** or the frame
  won't wake on button press.
- **`server/data/`, `server/.session_secret`, `server/.gphotos_token.json`,
  `server/config.json`** are gitignored runtime state — never commit them.
- **Never commit secrets.** The repo is public. Grep for `AIza`, `ya29.`,
  `ghp_`, `sk-` before pushing if you touched auth code.
- **Don't `git add -A` blindly** — check `git status` first.
- Docs worth reading before deep work: `PROTOCOL.md`, `docs/SECURITY.md`,
  `docs/SELFHOST.md`, `docs/GOOGLE_PHOTOS.md`, `docs/HARDWARE_CHECKLIST.md`,
  `TECHNICAL_REPORT_GDEB0709E01.md` (panel bring-up notes).

## License

MIT — see LICENSE. Fork it, self-host it, sell hardware running it.
