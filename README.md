# Muni 23 bus departure display

E-paper desk device showing minutes until the next
[Muni 23 Monterey](https://www.sfmta.com/routes/23-monterey) bus leaves
Crescent Ave & Andover St (westbound, toward Glen Park), so I know when to
walk out the door.

## Hardware

- Elecrow CrowPanel 2.13" e-paper display, built-in ESP32-S3 (122×250 B/W,
  SSD1680 on this unit; newer revisions ship JD79661 — a vendored driver for
  those lives in `bus_display/extras/jd79661/`)
- USB-C powered, no wiring

## How it works

- Polls the [511.org](https://511.org/open-data) StopMonitoring API every 65 s
  for live predictions
- Merges them with the Muni GTFS schedule baked into `bus_display/schedule.h`,
  matched by trip id — 511 only reports actively *tracked* buses, so untracked
  ("on time") departures come from the schedule
- A weekly [GitHub Action](.github/workflows/refresh-schedule.yml) regenerates
  the schedule from fresh GTFS and commits `schedule.json`; the device
  downloads it daily and caches it in flash, so the schedule never goes stale
  without reflashing
- Fast partial refresh on minute changes (panel's factory OTP Mode-2
  waveform), full refresh every 5 partials to clear ghosting

## Building

1. Copy `bus_display/secrets.h.example` to `bus_display/secrets.h`, fill in
   WiFi credentials and a free [511 token](https://511.org/open-data/token)
2. Install libraries: Adafruit GFX, ArduinoJson (v7); esp32 core ≥ 3.x
3. ```
   arduino-cli compile --fqbn "esp32:esp32:esp32s3:PSRAM=opi,FlashSize=8M,PartitionScheme=huge_app" bus_display
   arduino-cli upload -p /dev/cu.wchusbserial* --fqbn "esp32:esp32:esp32s3:PSRAM=opi,FlashSize=8M,PartitionScheme=huge_app" bus_display
   ```
   (macOS needs [WCH's CH34x driver](https://github.com/WCHSoftGroup/ch34xser_macos) —
   the board's CH340K reports USB id 0x7522, which the built-in driver ignores)

## Layout iteration

`preview/preview.py` parses the real Adafruit GFX font headers and replicates
the firmware's `render()` pixel-for-pixel into PNGs — design changes without
flashing. Keep `draw_layout_v2` in sync with the sketch.

## Adapting to another stop/route

Change `STOP_CODE`/`LINE_REF` in the sketch and `STOP_ID`/`ROUTE_ID` in
`tools/gen_schedule.py`, regenerate (`tools/update_schedule.sh`), and update
`SCHEDULE_URL` to your own fork. Find stop ids on
[511.org](https://511.org/open-data) — beware paired stops: each direction has
its own id.
