# Muni bus departure display

E-paper desk device showing minutes until the next buses leave the stops near my house, so I know when to walk out the door. **Two routes since 2026-11-13**, one display row each; both configured in gitignored `secrets.h` (route 2 = `SECRET_*_2`).

## Hardware

- Elecrow CrowPanel 2.13" e-paper display with built-in ESP32 (Amazon ASIN B0H25DMJ8M)
- Panel: 122x250 B/W, SSD1680-family driver, SPI
- USB-C powered, no external wiring

## Data source

- 511.org SF Bay API, StopMonitoring endpoint (real-time Muni predictions)
- `GET https://api.511.org/transit/StopMonitoring?api_key=KEY&agency=SF&stopcode=STOPCODE&format=json`
- Stop/route/destination label live in gitignored `bus_display/secrets.h` (SECRET_STOP_CODE etc.) — keep them out of committed files, the repo is public. Generated `schedule.h`/`schedule.json` are gitignored for the same reason (departure times fingerprint the stop)
  (14190 is the same intersection eastbound toward Bayview — do not use)
- Route filter: LineRef = SECRET_LINE_REF from secrets.h
- **Direction filter (SECRET_DIR_REF, 511 `DirectionRef`)**: terminal/loop stops serve
  BOTH directions of a line — arriving buses that end there appear in the feed too.
  Without the filter the row shows buses you can't board. SECRET_GTFS_DIR is the
  matching GTFS `direction_id` for gen_schedule.py (pick by `trip_headsign` in
  trips.txt). Empty string = no filtering (single-direction stops)
- Free token from 511.org/open-data/token; rate limit 60 requests/hour → the loop
  polls ONE route per 65s tick, alternating, so each route updates every ~130s
- **API quirks (all handled in firmware):**
  - Responses are always gzip-compressed, even without Accept-Encoding
  - JSON body starts with a UTF-8 BOM (3 bytes) that breaks ArduinoJson unless skipped
  - At this stop `ExpectedDepartureTime` is usually null — the real-time prediction
    is in `ExpectedArrivalTime`; `AimedDepartureTime` is just the schedule.
    Fallback chain: ExpectedDeparture → ExpectedArrival → AimedDeparture
  - Late evening the feed often has only one predicted bus (bottom line then
    falls back to the destination label — by design, not a bug)
  - **StopMonitoring only returns actively tracked vehicles** — untracked buses
    (shown as scheduled/"on time" in Google/Muni apps) are absent entirely.
    Fixed by merging a baked-in GTFS schedule (`bus_display/schedule.h`, generated
    by `tools/gen_schedule.py`) with live predictions, matched by trip id
    (numeric prefix of `DatedVehicleJourneyRef`, e.g. "12065578_M11" → 12065578).
    Predictions win for their trip; schedule fills the untracked gaps.
  - The 511 StopTimetable endpoint always returns HTTP 412 (broken/gated) — that's
    why the schedule is baked in rather than fetched.
  - **Schedule stays fresh automatically**: a GitHub Actions cron
    (`.github/workflows/refresh-schedule.yml`, Mondays ~4am Pacific, 511 key in repo
    secret `API_KEY_511`) regenerates `schedule.json` + `schedule.h`; the device
    downloads `schedule.json` from raw.githubusercontent.com daily (hourly retry on
    failure), caches it in NVS, and falls back to the baked-in `schedule.h`.
    `tools/update_schedule.sh` still works for manual USB refresh.
  - Repo: github.com/christianalmer/bus-display (public — secrets live in gitignored
    `bus_display/secrets.h`; `.claude/` is gitignored too since approved commands
    embed the API key). Push via SSH.

## Behavior

- One 511 request per 65s tick, alternating between the two routes; NTP-synced clock (TZ: America/Los_Angeles). Predictions considered stale after 6 min (route poll period is ~130s)
- Display shows whole minutes, not seconds (e-paper can't sustain 1 Hz refreshes)
- Partial refresh when ANY row's displayed minute changes; full refresh every 5 partials to clear ghosting
- Partial refresh correctness depends on RAM 0x26 holding the on-glass frame: `epd1680.cpp` rewrites it after every refresh and sleeps in deep-sleep mode 1 (RAM retained). Don't switch to mode-2 sleep or cut panel power between updates
- Departures that pass between polls are dropped locally so the countdown never goes negative
- States: "N min" + "next: M min" / "NOW" under a minute / "No buses" overnight (bottom line falls back to the destination label)

## Display layout (landscape, 250x122, two rows)

- One 61px row per route, divider line at y=60 (x 8..242)
- Per row (top = 0 or 61): badge 44x44 at x=8 y=top+8 (route number
  FreeSansBold12pt centered at runtime, baseline top+38), countdown
  FreeSansBold18pt + "min" 12pt at x=64 baseline top+44, info column
  (FreeSans9pt, "next M" or the destination label) right-aligned to x=242
  on the same baseline
- Row states: "N min" / "NOW" (18pt) / "No buses" / "No data" (12pt, right
  column suppressed)
- **Schedule-expiry reminder**: starting 14 days before the baked table runs out
  (`REMINDER_DAYS`), a classic-5x7-font line replaces the divider (top-left y=56,
  centered): "SCHEDULE ENDS <MON> <D> - UPDATE ME", then "SCHEDULE EXPIRED - RUN
  UPDATE" past the date. Disappears after `tools/update_schedule.sh` + reflash.
  Classic-font preview support lives in the library harness (`text_classic`)
- **Iterate on layout with `preview/preview.py`** — replicates render() pixel-for-pixel into PNGs (no flashing needed). The font/canvas/PNG harness lives in the crowpanel-epd library (`preview/epd_preview.py`); this project's file holds only `draw_layout_v2`, which must stay in sync with firmware render()

## Firmware status

**WORKING — flashed and verified on hardware 2026-08-11.** Sketch lives in `bus_display/` (folder name must match .ino for arduino-cli). Stack: Arduino (esp32 core 3.3.11), **shared `crowpanel-epd` library** (drivers + `epdCanvasToPanel()` + preview harness; cloned at `~/Documents/Arduino/libraries/crowpanel-epd`, repo github.com/christianalmer/crowpanel-epd — edit there, push once, all display projects pick it up) + Adafruit GFX (GFXcanvas1) + ArduinoJson (v7), gzip inflate via `tinfl_decompress_mem_to_mem` (in ESP32-S3 ROM, `#include "miniz.h"` — NOT `rom/miniz.h`, which doesn't exist on the S3 core).

**2026-08-17: hardware layer extracted to the crowpanel-epd library** (shared with bike-display). Library-based build flashed and verified on hardware same day.

**2026-11-13: two-route rework, flashed + verified on a NEW panel unit** (also the SSD1680 revision — clean BUSY handshake, full refresh ~2.4s). One row per route; per-route prediction/schedule state; alternating fetch; DirectionRef filter (route 2's stop is a terminal loop serving both directions — IB = departing). `gen_schedule.py` now emits `SCHED_TABLES[]` for all routes (+ v2 schedule.json) and trims the day table to start yesterday (GTFS validity can exceed the RS_MAX_DAYS=70 cap). **Baked schedule valid through 2027-01-15** — regenerate with `tools/update_schedule.sh` around then (remote-fetch URL is retired; SECRET_SCHEDULE_URL empty, machinery still in place and now expects v2 JSON).

**GxEPD2 was tried and dropped** (still installed as a library, unused): `GxEPD2_213_BN` full refresh worked but partial refresh ghosted badly — that class uploads a custom LUT tuned for DEPG0213BN glass, which doesn't match this panel. `epd1680.cpp` follows Elecrow's own flow: partial refresh via the panel's factory OTP Mode-2 waveform (`0x22 = 0xFC`), previous frame maintained in RAM 0x26 after every refresh, deep-sleep mode 1 between updates (retains RAM, so the diff base survives).

**Hardware findings (verified against both Elecrow demo repos + on-device):**
- Pins, same on ALL board revisions: SCK 12, MOSI 11, RST 10, DC 13, CS 14, BUSY 9, panel power 7 (must be HIGH), power LED 19. Elecrow demos bit-bang these; we route them to hardware SPI via `SPI.begin(12, -1, 11, 14)`.
- Two panel revisions exist with identical wiring: older = **SSD1680** (Elecrow repo `ESP32_S3-Ink-Screen`), newer = **JD79661**, UC8151-style, BUSY inverted (repo `CrowPanel-ESP32-2.13-E-paper-HMI-Display-with-122-250`, example/arduino-v1.2). GxEPD2 supports only the SSD1680 one.
- **This unit is the older SSD1680 revision** (full refresh ~2.1s, BUSY active-high). Diagnostic: JD79661-protocol writes get zero BUSY response ("refresh done in 0 ms").
- A vendored JD79661 driver (port of Elecrow's demo, plus a DU fast-refresh variant) lives in the crowpanel-epd library under `src/jd79661/` in case a future/replacement unit is the newer revision — swap the include and draw via GFXcanvas1 (it compiled and ran, just no panel response on this unit).
- USB is a CH340K reporting idProduct **0x7522**, which macOS's built-in CH34x driver does NOT match (it only matches 0x7523/0x55D4) — needs WCH's CH34xVCPDriver from github.com/WCHSoftGroup/ch34xser_macos, approved in System Settings → General → Login Items & Extensions → Driver Extensions (no notification appears). Port shows as `/dev/cu.wchusbserial*`.

Build/flash:
- FQBN: `esp32:esp32:esp32s3:PSRAM=opi,FlashSize=8M,PartitionScheme=huge_app`
- `arduino-cli compile --fqbn <fqbn> bus_display` from repo root; `arduino-cli upload -p /dev/cu.wchusbserial110 --fqbn <fqbn> bus_display`
- Serial monitor: pyserial with `setDTR(False); setRTS(False)` (arduino-cli monitor buffers badly when backgrounded); pulse RTS True→False to reset the board

Remaining/untested:
1. ~~Overnight "No buses" state~~ — observed working 2026-08-11 night
2. Ghosting: GxEPD2's partial LUT was the main culprit (fixed by vendored driver + OTP Mode-2 waveform + shadow prev-frame in MCU RAM); verify partials stay clean over a full day
3. WiFi credentials + 511 token are real values in the sketch — don't commit publicly
4. Serial port renumbers between sessions (`/dev/cu.wchusbserial110` vs `210`) — check `ls /dev/cu.wchusbserial*`

## Ideas for later

- Dim or blank the display at night
- LED or visual alert for "leave now or miss it"
- Show departure clock time alongside the countdown
