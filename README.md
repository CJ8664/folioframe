# SpectraFrame

Modular e-paper frame firmware combining the device-side feature superset of
7 community projects (guysie, philippwaller, tesserae, aitjcize, sven97,
josomm22, matthewfcarlson, michaelkurath). First target: **Seeed XIAO EE02 +
Good Display GDEB0709E01 7.09" Spectra 6**.

Wake → Wi-Fi → time → OTA → fetch → paint → deep sleep.

## Quick start

1. Install [PlatformIO](https://platformio.org/).
2. Open this folder. Select env `ee02`.
3. **Enable PSRAM** (required — the 960 KB frame buffer lives in PSRAM).
4. `pio run -t upload`, then `pio device monitor`.
5. First boot: join Wi-Fi `SF-Setup-SF-XXXXXX`, complete the portal.
6. Serve frames: `python3 tools/frame_server.py`, set Image URL to
   `http://<host>:8765/frame`.

## Layout

| Dir | Role | Swap rule |
|---|---|---|
| `src/hal/` | `Board` / `Panel` abstract interfaces + EE02 / GDEB0709E01 | New hardware = new subclass, nothing else changes |
| `src/core/` | Scheduler, QuietHours, BatteryCurve, UrlTemplate, OtaManifest, Validate | Pure C++17, no Arduino — natively unit-tested |
| `src/app/` | Config, TimeSync, FrameFetcher, OtaManager, Portal, PowerManager | Arduino behaviors composed from `hal` + `core` |
| `src/ui/` | StatusScreen | On-panel text screens via the `Panel` seam |

## Server protocol

Any server can feed the frame — see [PROTOCOL.md](PROTOCOL.md). Contract:
`GET /frame` → 960 000 bytes packed 4bpp + `ETag`; `304` skips the repaint.
OTA: `GET /version` → build number, `GET /firmware.bin` → app image.

## Companion server

`server/` is a working PROTOCOL.md server (Python + Pillow):

```bash
pip install -r server/requirements.txt
python3 server/spectra_server.py   # :8765, writes server/config.json
```

Sources: `folder` (local albums), `picsum`, `url` (templates), `dashboard`
(clock + Open-Meteo weather). Rotation engine with unseen-first history,
quiet hours, and ETag/304. Web UI at `/` with live preview; `/preview.png`,
`/debug`, `/api/next`, `/api/source`. Tests: `server/tests/run.sh` (22 cases).

## Verification

- **Level 1** — native unit tests: `tools/run_tests.sh` (24 cases, all `core/`)
- **Level 2** — full `src/` syntax check vs Arduino stubs: `tools/stub_compile.sh`
- **Level 3** — on-device: [docs/HARDWARE_CHECKLIST.md](docs/HARDWARE_CHECKLIST.md)

## Language choice

C++17 on Arduino: native speed for 960 KB frame ops, `setup()`/`loop()`
readability, and the libraries this needs (WiFiManager, ESP32 `Update`,
`Preferences`, official Seeed_GFX2 with 7.09" support). MicroPython was
rejected (too slow for e-paper frame ops), Rust (no GDEB0709E01 driver
ecosystem), ESP-IDF C (3–5× boilerplate for the same result), ESPHome YAML
(not code — custom logic still needs C++). Full analysis in [PLAN.md](PLAN.md).

## Roadmap (v2)

On-device JPEG decode (`Panel::drawJpeg` hook), BLE provisioning
(`app/Provisioner` seam), touch input, MQTT / native Home Assistant API.
