#!/bin/bash
# Refresh the baked-in Muni schedule and reflash the display.
# Run when a Muni signup ends (the display's schedule.h header shows the
# validity range; the firmware logs a warning once it's stale).
# Requires: the CrowPanel plugged in via USB.
set -e
cd "$(dirname "$0")/.."

FQBN="esp32:esp32:esp32s3:PSRAM=opi,FlashSize=8M,PartitionScheme=huge_app"
PORT=$(ls /dev/cu.wchusbserial* 2>/dev/null | head -1)
if [ -z "$PORT" ]; then
  echo "No CrowPanel found (no /dev/cu.wchusbserial*). Plug it in first." >&2
  exit 1
fi

python3 tools/gen_schedule.py
arduino-cli compile --fqbn "$FQBN" bus_display
arduino-cli upload -p "$PORT" --fqbn "$FQBN" bus_display
echo "Done — display reflashed with the new schedule."
