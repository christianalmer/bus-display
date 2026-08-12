#!/usr/bin/env python3
"""Pixel-accurate preview of the bus display layout.

Parses the actual Adafruit GFX font headers the firmware uses and
replicates render() from bus_display.ino, so the PNG matches the e-paper
pixel for pixel. Edit LAYOUT below, run, look at preview.png, and mirror
the final coordinates back into bus_display.ino.
"""

import re
import sys
from pathlib import Path

FONT_DIR = Path.home() / "Documents/Arduino/libraries/Adafruit_GFX_Library/Fonts"
W, H = 250, 122
SCALE = 4


# ---------------- GFX font parsing ----------------

def parse_font(path: Path):
    text = path.read_text()
    bitmaps = [int(v, 16) for v in re.findall(r"0x([0-9A-Fa-f]{2})",
               re.search(r"Bitmaps\[\]\s*PROGMEM\s*=\s*\{(.*?)\};", text, re.S).group(1))]
    glyphs = []
    for m in re.finditer(r"\{\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+),\s*(-?\d+),\s*(-?\d+)\s*\}",
                         re.search(r"Glyphs\[\]\s*PROGMEM\s*=\s*\{(.*?)\};", text, re.S).group(1)):
        glyphs.append(tuple(int(g) for g in m.groups()))
    font_meta = re.search(r"\{\s*\(uint8_t\s*\*\)\S+,\s*\(GFXglyph\s*\*\)\S+,\s*(0x[0-9A-Fa-f]+),\s*(0x[0-9A-Fa-f]+),\s*(\d+)\s*\}", text)
    first, last, y_advance = int(font_meta.group(1), 16), int(font_meta.group(2), 16), int(font_meta.group(3))
    return {"bitmaps": bitmaps, "glyphs": glyphs, "first": first, "last": last, "y_advance": y_advance}


FONTS = {
    "bold24": parse_font(FONT_DIR / "FreeSansBold24pt7b.h"),
    "bold12": parse_font(FONT_DIR / "FreeSansBold12pt7b.h"),
    "sans9":  parse_font(FONT_DIR / "FreeSans9pt7b.h"),
}


# ---------------- 1-bit canvas with GFX semantics ----------------

class Canvas:
    def __init__(self):
        self.px = [[0] * W for _ in range(H)]  # 1 = black

    def set(self, x, y, color):
        if 0 <= x < W and 0 <= y < H:
            self.px[y][x] = color

    def fill_rect(self, x, y, w, h, color):
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                self.set(xx, yy, color)

    def fill_circle_quads(self, x0, y0, r, quads, color):
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if dx * dx + dy * dy <= r * r:
                    if (dx <= 0 and dy <= 0 and 1 in quads) or \
                       (dx >= 0 and dy <= 0 and 2 in quads) or \
                       (dx <= 0 and dy >= 0 and 3 in quads) or \
                       (dx >= 0 and dy >= 0 and 4 in quads):
                        self.set(x0 + dx, y0 + dy, color)

    def fill_round_rect(self, x, y, w, h, r, color):
        self.fill_rect(x + r, y, w - 2 * r, h, color)
        self.fill_rect(x, y + r, r, h - 2 * r, color)
        self.fill_rect(x + w - r, y + r, r, h - 2 * r, color)
        self.fill_circle_quads(x + r, y + r, r, {1}, color)
        self.fill_circle_quads(x + w - r - 1, y + r, r, {2}, color)
        self.fill_circle_quads(x + r, y + h - r - 1, r, {3}, color)
        self.fill_circle_quads(x + w - r - 1, y + h - r - 1, r, {4}, color)

    def draw_char(self, font, x, y, ch, color):
        f = FONTS[font]
        code = ord(ch)
        if not (f["first"] <= code <= f["last"]):
            return x
        off, gw, gh, x_adv, x_off, y_off = f["glyphs"][code - f["first"]]
        bit = 0
        for yy in range(gh):
            for xx in range(gw):
                byte = f["bitmaps"][off + bit // 8]
                if byte & (0x80 >> (bit % 8)):
                    self.set(x + x_off + xx, y + y_off + yy, color)
                bit += 1
        return x + x_adv

    def text(self, font, x, y, s, color):
        for ch in s:
            x = self.draw_char(font, x, y, ch, color)
        return x

    def text_width(self, font, s):
        f = FONTS[font]
        return sum(f["glyphs"][ord(c) - f["first"]][3] for c in s
                   if f["first"] <= ord(c) <= f["last"])


# ---------------- the layout (mirror of render() in bus_display.ino) ----------------

def draw_layout(c: Canvas, minutes, minutes2, fetch_ok=True):
    # Route badge
    c.fill_round_rect(6, 30, 62, 62, 8, 1)
    c.text("bold24", 12, 74, "23", 0)

    if minutes < 0:
        c.text("bold12", 84, 60, "No buses" if fetch_ok else "No data", 1)
    elif minutes == 0:
        c.text("bold24", 84, 70, "NOW", 1)
    else:
        x = c.text("bold24", 84, 70, str(minutes), 1)
        c.text("bold12", x, 70, " min", 1)

    if minutes2 >= 0:
        c.text("sans9", 84, 108, f"next: {minutes2} min", 1)
    else:
        c.text("sans9", 84, 108, "Glen Park", 1)


# ---------------- PNG output (no dependencies) ----------------

def write_png(path, states):
    import zlib, struct
    gap = 12
    img_w = W * SCALE + 2 * gap
    img_h = (H * SCALE + gap) * len(states) + gap
    rows = [[200] * img_w for _ in range(img_h)]  # grey background between panels

    for i, canvas in enumerate(states):
        oy = gap + i * (H * SCALE + gap)
        for y in range(H * SCALE):
            for x in range(W * SCALE):
                v = 30 if canvas.px[y // SCALE][x // SCALE] else 245
                rows[oy + y][gap + x] = v

    raw = b"".join(b"\x00" + bytes(r) for r in rows)

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data))

    with open(path, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n")
        fh.write(chunk(b"IHDR", struct.pack(">IIBBBBB", img_w, img_h, 8, 0, 0, 0, 0)))
        fh.write(chunk(b"IDAT", zlib.compress(raw)))
        fh.write(chunk(b"IEND", b""))


def draw_layout_v2(c: Canvas, minutes, minutes2, fetch_ok=True):
    """Cleaned-up layout: optically centered badge text, shared baselines."""
    # Centered: widest state is "NOW" (117px) -> badge 62 + gap 16 + 117 = 195
    # -> badge x = (250-195)/2 = 27, text column at 27+62+16 = 105
    BX, BY, BW_, BH = 27, 30, 62, 62
    BASE = 77          # shared baseline for badge "23" and the big number
    SUB_BASE = 112     # bottom info line baseline
    LEFT = 105         # left edge of the text column

    c.fill_round_rect(BX, BY, BW_, BH, 8, 1)
    w23 = c.text_width("bold24", "23")
    c.text("bold24", BX + (BW_ - w23) // 2, BASE, "23", 0)

    if minutes < 0:
        c.text("bold12", LEFT, BASE, "No buses" if fetch_ok else "No data", 1)
    elif minutes == 0:
        c.text("bold24", LEFT, BASE, "NOW", 1)
    else:
        x = c.text("bold24", LEFT, BASE, str(minutes), 1)
        c.text("bold12", x + 6, BASE, "min", 1)

    if minutes2 >= 0:
        c.text("sans9", LEFT, SUB_BASE, f"next: {minutes2} min", 1)
    else:
        c.text("sans9", LEFT, SUB_BASE, "Glen Park", 1)


if __name__ == "__main__":
    states = [(12, 22), (7, -1), (0, 9), (-1, -1)]
    for name, fn in [("current", draw_layout), ("proposed", draw_layout_v2)]:
        variants = []
        for args in states:
            c = Canvas()
            fn(c, *args)
            variants.append(c)
        out = Path(__file__).parent / f"preview_{name}.png"
        write_png(out, variants)
        print(f"wrote {out}")
