# OTA firmware binaries

Drop a built `firmware.bin` here and it gets baked into the Docker image
(the server looks for `server/firmware/firmware.bin`).

Build it with PlatformIO (`pio run` — the binary lands in
`.pio/build/ee02/firmware.bin`), copy it here as `firmware.bin`, bump
`"build"` in your server config to the firmware's `FW_BUILD` number, and
redeploy. Devices whose build is older will download, MD5-verify, and
flash it on their next wake.

Nothing is published until both the binary exists here AND the config
build number is higher than what the devices run.
