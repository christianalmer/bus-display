# Muni 23 bus departure display

E-paper desk device showing minutes until the next 23 bus leaves the stop near my house, so I know when to walk out the door.

## Hardware

- Elecrow CrowPanel 2.13" e-paper display with built-in ESP32 (Amazon ASIN B0H25DMJ8M)
- Panel: 122x250 B/W, SSD1680-family driver, SPI
- USB-C powered, no external wiring

## Data source

- 511.org SF Bay API, StopMonitoring endpoint (real-time Muni predictions)
- `GET https://api.511.org/transit/StopMonitoring?api_key=KEY&agency=SF&stopcode=14189&format=json`
- Stop: Crescent Ave & Andover St, **511 stop ID 14189** = westbound, toward Glen Park / SF Zoo
  (14190 is the same intersection eastbound toward Bayview — do not use)
- Route filter: LineRef "23"
- Free token from 511.org/open-data/token; rate limit 60 requests/hour → poll once per minute
- **API quirks (all handled in firmware):**
  - Responses are always gzip-compressed, even without Accept-Encoding
  - JSON body starts with a UTF-8 BOM (3 bytes) that breaks ArduinoJson unless skipped
  - At this stop `ExpectedDepartureTime` is usually null — the real-time prediction
    is in `ExpectedArrivalTime`; `AimedDepartureTime` is just the schedule.
    Fallback chain: ExpectedDeparture → ExpectedArrival → AimedDeparture
  - Late evening the feed often has only one predicted bus (bottom line then
    falls back to "Glen Park" — by design, not a bug)
  - **StopMonitoring only returns actively tracked vehicles** — untracked buses
    (shown as scheduled/"on time" in Google/Muni apps) are absent entirely.
    Fixed by merging a baked-in GTFS schedule (`bus_display/schedule.h`, generated
    by `tools/gen_schedule.py`) with live predictions, matched by trip id
    (numeric prefix of `DatedVehicleJourneyRef`, e.g. "12065578_M11" → 12065578).
    Predictions win for their trip; schedule fills the untracked gaps.
  - The 511 StopTimetable endpoint always returns HTTP 412 (broken/gated) — that's
    why the schedule is baked in rather than fetched.
  - **schedule.h expires**: GTFS covers ~5 weeks per Muni signup (current table ends
    2026-08-28). Refresh with `tools/update_schedule.sh` (regenerates schedule.h from
    fresh GTFS, recompiles, reflashes — board must be plugged in). After expiry the
    firmware logs a warning and falls back to predictions-only.

## Behavior

- Poll 511 every 65s (60s = exactly the rate limit, no headroom for manual testing); NTP-synced clock (TZ: America/Los_Angeles)
- Display shows whole minutes, not seconds (e-paper can't sustain 1 Hz refreshes)
- Partial refresh only when the displayed minute changes; full refresh every 5 partials to clear ghosting
- Partial refresh correctness depends on RAM 0x26 holding the on-glass frame: `epd1680.cpp` rewrites it after every refresh and sleeps in deep-sleep mode 1 (RAM retained). Don't switch to mode-2 sleep or cut panel power between updates
- Departures that pass between polls are dropped locally so the countdown never goes negative
- States: "N min" + "next: M min" / "NOW" under a minute / "No buses" overnight (bottom line falls back to "Glen Park")

## Display layout (landscape, 250x122)

- Left: black rounded square badge with "23" in white, static
- Center: large minutes number + small "min" label — the only region that changes per minute
- Bottom right: second departure ("next: 22 min")
- Fonts: Adafruit GFX FreeSansBold24pt / 12pt / FreeSans9pt
- Composition horizontally centered on the widest state ("NOW", 117px): badge x=27 (its "23" at x=32; glyphs 52px wide), text column x=105. Shared baselines: badge "23" / big number / NOW / No buses at y=77; bottom line at y=112
- **Iterate on layout with `preview/preview.py`** — parses the real Adafruit GFX font headers and replicates render() pixel-for-pixel into PNGs (no flashing needed). `draw_layout_v2` is the version in firmware; keep them in sync

## Firmware status

**WORKING — flashed and verified on hardware 2026-08-11.** Sketch lives in `bus_display/` (folder name must match .ino for arduino-cli). Stack: Arduino (esp32 core 3.3.11), vendored Elecrow SSD1680 driver (`epd1680.{h,cpp}`) + Adafruit GFX (GFXcanvas1) + ArduinoJson (v7), gzip inflate via `tinfl_decompress_mem_to_mem` (in ESP32-S3 ROM, `#include "miniz.h"` — NOT `rom/miniz.h`, which doesn't exist on the S3 core).

**GxEPD2 was tried and dropped** (still installed as a library, unused): `GxEPD2_213_BN` full refresh worked but partial refresh ghosted badly — that class uploads a custom LUT tuned for DEPG0213BN glass, which doesn't match this panel. `epd1680.cpp` follows Elecrow's own flow: partial refresh via the panel's factory OTP Mode-2 waveform (`0x22 = 0xFC`), previous frame maintained in RAM 0x26 after every refresh, deep-sleep mode 1 between updates (retains RAM, so the diff base survives).

**Hardware findings (verified against both Elecrow demo repos + on-device):**
- Pins, same on ALL board revisions: SCK 12, MOSI 11, RST 10, DC 13, CS 14, BUSY 9, panel power 7 (must be HIGH), power LED 19. Elecrow demos bit-bang these; we route them to hardware SPI via `SPI.begin(12, -1, 11, 14)`.
- Two panel revisions exist with identical wiring: older = **SSD1680** (Elecrow repo `ESP32_S3-Ink-Screen`), newer = **JD79661**, UC8151-style, BUSY inverted (repo `CrowPanel-ESP32-2.13-E-paper-HMI-Display-with-122-250`, example/arduino-v1.2). GxEPD2 supports only the SSD1680 one.
- **This unit is the older SSD1680 revision** (full refresh ~2.1s, BUSY active-high). Diagnostic: JD79661-protocol writes get zero BUSY response ("refresh done in 0 ms").
- A vendored JD79661 driver (port of Elecrow's demo, plus a DU fast-refresh variant) is kept in `bus_display/extras/jd79661/` in case a future/replacement unit is the newer revision — swap it in and draw via GFXcanvas1 (see git-less history: it compiled and ran, just no panel response on this unit).
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
