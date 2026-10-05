# Hardware Checklist (Level 3 verification — run on the device)

Check off on real hardware. Anything failing here is a firmware bug until
proven otherwise.

## First flash
- [ ] Builds in PlatformIO with `seeed_xiao_esp32s3`, PSRAM enabled
- [ ] `Seeed_Product::Seeed_ePaper_7INCH09_C` compiles (if renamed, one-line fix
      in `src/hal/Gdeb0709e01Panel.cpp`)
- [ ] Flashes over USB-C (`pio run -t upload`); serial shows
      `SpectraFrame 2.0.0 build 2`
- [ ] First boot with no Wi-Fi creds → panel shows the setup screen with the
      `SF-Setup-sf-xxxxxxxxxxxx` AP name and `http://192.168.4.1`
- [ ] Web flash alternative: publish the four `server/firmware/*.bin` files,
      open the server's public `/flash` page in Chrome/Edge, flash over USB

## Provisioning & portal
- [ ] Join the setup AP → WiFiManager captive portal for Wi-Fi creds
- [ ] After Wi-Fi connects → panel shows the settings page URL (the frame's
      LAN IP, e.g. `http://192.168.1.42`) — open it on your phone/computer
- [ ] Enter the server URL (`https://frame.example.com`) → save → "Saved."
- [ ] Invalid server URL (`ftp://…`) → 400 with a clear message
- [ ] BTN1 → portal; BTN1 again exits the portal
- [ ] Panel shows the `XXXX-XXXX` claim code; enter it at `<server>/claim`
      → frame pairs and fetches its first photo

## Frame fetch & paint
- [ ] Panel paints the current frame (~30 s refresh)
- [ ] Serial shows `304: image unchanged` on the next wake (no repaint)
- [ ] Push a photo from the console → next wake paints it
- [ ] Unpair from the console → next wake shows "Unpaired", then re-pairs
      with a fresh claim code

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
