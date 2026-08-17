#!/usr/bin/env python3
"""Pixel-accurate preview of the bus display layout.

Rendering harness (font parsing, canvas, PNG) lives in the crowpanel-epd
library; this file holds only the project's layouts. Edit draw_layout_v2,
run, look at preview_proposed.png, and mirror final coordinates back into
render() in bus_display.ino.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path.home() / "Documents/Arduino/libraries/crowpanel-epd/preview"))
from epd_preview import Canvas, write_png  # noqa: E402


def draw_layout_v2(c: Canvas, minutes, minutes2, fetch_ok=True):
    """The layout in firmware render() — keep in sync with bus_display.ino.

    Centered on the widest state "NOW" (117px): badge 62 + gap 16 + 117 = 195
    -> badge x = 27, text column x = 105."""
    BX, BY, BW_, BH = 27, 30, 62, 62
    BASE = 77          # shared baseline for badge "23" and the big number
    SUB_BASE = 112     # bottom info line baseline
    LEFT = 105         # left edge of the text column

    c.fill_round_rect(BX, BY, BW_, BH, 8, 1)
    w23 = c.text_width("FreeSansBold24pt7b", "23")
    c.text("FreeSansBold24pt7b", BX + (BW_ - w23) // 2, BASE, "23", 0)

    if minutes < 0:
        c.text("FreeSansBold12pt7b", LEFT, BASE, "No buses" if fetch_ok else "No data", 1)
    elif minutes == 0:
        c.text("FreeSansBold24pt7b", LEFT, BASE, "NOW", 1)
    else:
        x = c.text("FreeSansBold24pt7b", LEFT, BASE, str(minutes), 1)
        c.text("FreeSansBold12pt7b", x + 6, BASE, "min", 1)

    if minutes2 >= 0:
        c.text("FreeSans9pt7b", LEFT, SUB_BASE, f"next: {minutes2} min", 1)
    else:
        c.text("FreeSans9pt7b", LEFT, SUB_BASE, "Glen Park", 1)


if __name__ == "__main__":
    variants = []
    for args in [(12, 22), (7, -1), (0, 9), (-1, -1)]:
        c = Canvas()
        draw_layout_v2(c, *args)
        variants.append(c)
    out = Path(__file__).parent / "preview_proposed.png"
    write_png(out, variants)
    print(f"wrote {out}")
