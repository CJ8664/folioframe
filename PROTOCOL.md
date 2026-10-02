# SpectraFrame Device ↔ Server Protocol v1

Small, versioned HTTP contract. Any server (Python, Node, Cloudflare Worker,
Tesserae renderer, static file host) can feed the frame by implementing it.

## Frame fetch

```
GET <image_endpoint>            (default: /frame)
```

**Request headers (device → server):**

| Header | Example | Purpose |
|---|---|---|
| `X-Device-Id` | `SF-A1B2C3` | Stable device id (from MAC) |
| `X-Device-Panel` | `gdeb0709e01` | Panel kind; server picks correct variant |
| `X-Device-Width` / `X-Device-Height` | `1200` / `1600` | Panel-native geometry |
| `X-Firmware-Version` | `1.0.0` | For server-side fleet views |
| `X-Battery-Mv` / `X-Battery-Pct` | `4050` / `87` | Telemetry |
| `If-None-Match` | `"abc123"` | Sent when the device has a cached ETag |

**Success response:**

| Header | Value |
|---|---|
| `200 OK` | |
| `Content-Type` | `application/octet-stream` |
| `ETag` | opaque version string, quoted |
| `X-Frame-Format` | `packed4bpp` |

Body: exactly `width × height / 2` bytes (960 000 for 1200×1600).
**Packed 4bpp layout:** two pixels per byte, high nibble first, rows top→bottom,
left→right. Nibble values: `0x0` white, `0x2` green, `0x6` red, `0xB` yellow,
`0xD` blue, `0xF` black (UC8179 hardware codes).

**Not-modified response:** `304 Not Modified` (no body) → device skips the
~30 s panel refresh and goes back to sleep. This is the single biggest power
saver in the protocol.

**Errors:** `4xx/5xx` → device keeps the current image, backs off, retries next
wake. `404` with an empty queue is normal: keep image, sleep.

## OTA

```
GET <ota_base>/version        → 200 text/plain, e.g. "1.2.0"
GET <ota_base>/firmware.bin   → 200 application/octet-stream (ESP32 app image)
```

Response may include `X-Firmware-MD5` (32 lowercase hex chars); the device
verifies before flashing. Any version string differing from the running
version triggers an update — publishing an older version is a deliberate
rollback. `404` on `/version` means "no update channel", silently skipped.

## Debug

```
GET /debug   → 200 application/json (served by the device, not the server)
{"device":"SF-A1B2C3","fw":"1.0.0","battery_mv":4050,"battery_pct":87,
 "rssi":-61,"uptime_s":42,"last_error":"","panel":"gdeb0709e01"}
```

## Versioning

Breaking changes bump the `vN` in this document and the `X-Frame-Format`
negotiation. v1 servers and v1 devices are mutually compatible.
