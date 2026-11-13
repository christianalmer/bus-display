#!/usr/bin/env python3
"""Pixel-accurate preview of the bus display layout (two routes).

Rendering harness (font parsing, canvas, PNG) lives in the crowpanel-epd
library; this file holds only the project's layouts. Edit draw_two_routes,
run, look at preview_proposed.png, and mirror final coordinates back into
render() in bus_display.ino.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path.home() / "Documents/Arduino/libraries/crowpanel-epd/preview"))
from epd_preview import Canvas, write_png  # noqa: E402

# Sample route numbers for the mock (real ones live in secrets.h)
LINES = ("5", "67")
DESTS = ("Downtown", "Mission")


def draw_row(c: Canvas, top, line, dest, minutes, minutes2, fetch_ok=True):
    """One route row, 61px tall. Keep in sync with drawRow() in firmware.

    badge 44x44 at x=8; text column x=64; info column right-aligned to 242."""
    BASE = top + 44        # shared baseline: minutes / NOW / No buses
    BX, BY, BW, BH = 8, top + 8, 44, 44
    LEFT = 64
    RIGHT_EDGE = 242

    c.fill_round_rect(BX, BY, BW, BH, 6, 1)
    wline = c.text_width("FreeSansBold12pt7b", line)
    # 12pt caps are ~17px tall; center-ish in the 44px badge
    c.text("FreeSansBold12pt7b", BX + (BW - wline) // 2, BY + 30, line, 0)

    if minutes < 0:
        c.text("FreeSansBold12pt7b", LEFT, BASE, "No buses" if fetch_ok else "No data", 1)
        return  # no right column when the row is empty
    elif minutes == 0:
        c.text("FreeSansBold18pt7b", LEFT, BASE, "NOW", 1)
    else:
        x = c.text("FreeSansBold18pt7b", LEFT, BASE, str(minutes), 1)
        c.text("FreeSansBold12pt7b", x + 5, BASE, "min", 1)

    info = f"next {minutes2}" if minutes2 >= 0 else dest
    c.text("FreeSans9pt7b", RIGHT_EDGE - c.text_width("FreeSans9pt7b", info), BASE, info, 1)


def draw_two_routes(c: Canvas, r1, r2, fetch_ok=True, reminder=None):
    draw_row(c, 0, LINES[0], DESTS[0], *r1, fetch_ok)
    if reminder:
        # Schedule-expiry notice in the free strip between the rows
        # (classic 5x7 font at y=56, centered; replaces the divider line)
        c.text_classic((250 - Canvas.text_classic_width(reminder)) // 2, 56,
                       reminder, 1)
    else:
        c.fill_rect(8, 60, 234, 1, 1)  # divider
    draw_row(c, 61, LINES[1], DESTS[1], *r2, fetch_ok)


if __name__ == "__main__":
    states = [
        ((12, 22), (5, 25), None),                             # normal
        ((7, -1), (0, 14), "SCHEDULE ENDS JAN 15 - UPDATE ME"),  # expiry near
        ((-1, -1), (3, -1), "SCHEDULE EXPIRED - RUN UPDATE"),    # expired
    ]
    variants = []
    for r1, r2, rem in states:
        c = Canvas()
        draw_two_routes(c, r1, r2, reminder=rem)
        variants.append(c)
    out = Path(__file__).parent / "preview_proposed.png"
    write_png(out, variants)
    print(f"wrote {out}")
