# Hardware Checklist (Level 3 verification — run on the device)

Check off on real hardware. Anything failing here is a firmware bug until
proven otherwise.

## First flash
- [ ] Builds in PlatformIO with `seeed_xiao_esp32s3`, PSRAM enabled
- [ ] `Seeed_Product::Seeed_ePaper_7INCH09_C` compiles (if renamed, one-line fix
      in `src/hal/Gdeb0709e01Panel.cpp`)
- [ ] Flashes over USB-C; serial shows `SpectraFrame 1.0.0 build 1`
- [ ] First boot with no Wi-Fi creds → panel shows setup screen, AP
      `SF-Setup-SF-XXXXXX` appears

## Provisioning & portal
- [ ] Join the setup AP → captive portal opens (or browse http://192.168.4.1)
- [ ] Enter 2.4 GHz Wi-Fi creds → device connects, portal shows settings page
- [ ] Settings page: change interval to 15 min, save → "Saved."
- [ ] Invalid URL (`ftp://…`) → 400 with a clear message
- [ ] BTN1 exits the portal

## Frame fetch & paint
- [ ] Run `python3 tools/frame_server.py` on the LAN
- [ ] Set Image URL to `http://<host>:8765/frame`, exit portal
- [ ] Panel paints the 6-bar test pattern (~30 s refresh)
- [ ] Serial shows `304: image unchanged` on the next wake (no repaint)
- [ ] Change `BUILD`/frame content → next wake repaints
- [ ] Point URL at a 404 → panel keeps the old image, retries next wake

## Power
- [ ] **Multimeter check:** compare `battery_mv` in `/debug` against a meter
      on J3 (pin 1 = +). If off, fix `EE02_BAT_*` in `include/board_config.h`
      — defaults are from the EE04 reference circuit, UNVERIFIED for EE02.
- [ ] Deep-sleep current in the low-µA range (USB meter)
- [ ] Timer wake happens on schedule; `/debug` shows sane `uptime_s`
- [ ] Quiet hours: set 22:00–07:00, wake inside → no fetch, sleeps to 07:00

## Buttons
- [ ] BTN2 wake → immediate fetch
- [ ] BTN3 wake → toggles pin; pinned timer wakes skip fetch
- [ ] BTN1 wake → portal opens

## OTA
- [ ] Set OTA base URL to a server with `/version` = `2` → device downloads
      and flashes, reboots into build 2
- [ ] Publish `/version` = `1` → device rolls back to build 1
- [ ] Battery < 40% → OTA skipped with "battery too low" in serial log
- [ ] Flash a bad image → bootloader rolls back to the previous partition
