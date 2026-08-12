#ifndef EPD1680_H
#define EPD1680_H

#include <Arduino.h>

/*
 * Low-level driver for the Elecrow CrowPanel ESP32-S3 2.13" e-paper,
 * OLDER revision with SSD1680 controller (122x250 B/W) — the one this
 * unit has (verified on hardware).
 *
 * Ported from Elecrow's demo repo ESP32_S3-Ink-Screen,
 * "2.13 Inch_ESP32_S3/Example Code/2.13_partial_refresh".
 *
 * Why not GxEPD2: its GxEPD2_213_BN class uploads a custom partial-refresh
 * LUT tuned for the DEPG0213BN panel. This panel ghosts badly with it.
 * Elecrow's flow instead loads the panel's OWN factory-calibrated Mode-2
 * waveform from OTP (0x22 = 0xFC), which refreshes clean.
 *
 * RAM convention: SSD1680 has two frame RAMs — 0x24 (current) and 0x26
 * (previous). The Mode-2 partial waveform diffs them, so after every
 * refresh the current frame must be copied into 0x26. Deep sleep mode 1
 * (0x10, 0x01) retains RAM, so the diff survives sleep between updates.
 *
 * Buffer format (same as the newer panel's): landscape framebuffer is
 * translated to 250 rows x 16 bytes, bit set = black; bytes are inverted
 * on the wire (SSD1680: 1 = white).
 */

// Pins shared by all CrowPanel 2.13 revisions (from Elecrow demo spi.h)
#define EPD_PIN_SCK   12
#define EPD_PIN_MOSI  11
#define EPD_PIN_RES   10
#define EPD_PIN_DC    13
#define EPD_PIN_CS    14
#define EPD_PIN_BUSY   9
#define EPD_PIN_PWR    7   // panel power gate
#define EPD_PIN_LED   19   // board power LED

#define EPD_BYTES_PER_ROW   16
#define EPD_ROWS           250
#define EPD_BUF_BYTES      (EPD_BYTES_PER_ROW * EPD_ROWS)  // 4000

void EPD1680_PowerOn(void);                       // drive PWR + LED pins
void EPD1680_Init(void);                          // reset + register setup (also wakes from sleep)
void EPD1680_Sleep(void);                         // deep sleep mode 1 (RAM retained)
void EPD1680_DisplayFull(const uint8_t *buf);     // full refresh (OTP Mode-1 waveform)
void EPD1680_DisplayPartial(const uint8_t *buf);  // fast partial (OTP Mode-2 waveform)

#endif
