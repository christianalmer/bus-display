#ifndef EPD_DRIVER_H
#define EPD_DRIVER_H

#include <Arduino.h>

/*
 * Low-level driver for the Elecrow CrowPanel ESP32-S3 2.13" e-paper
 * (JD79661 controller, 122x250 B/W).
 *
 * Ported from Elecrow's demo:
 *   github.com/Elecrow-RD/CrowPanel-ESP32-2.13-E-paper-HMI-Display-with-122-250
 *   example/arduino-v1.2/main/{spi,EPD_Init}.{h,cpp}
 * Pin numbers and LUT waveform tables are copied verbatim; the only
 * addition is EPD_DisplayImage_DU() (fast partial-style refresh using
 * the demo's DU waveform, which its UI never called directly).
 *
 * The JD79661 is NOT SSD1680-compatible (different command set, BUSY is
 * active-low instead of active-high), which is why GxEPD2 isn't used.
 */

// Pins from Elecrow demo spi.h (bit-banged SPI, not the hardware SPI bus)
#define EPD_PIN_SCK   12
#define EPD_PIN_MOSI  11
#define EPD_PIN_RES   10
#define EPD_PIN_DC    13
#define EPD_PIN_CS    14
#define EPD_PIN_BUSY   9
#define EPD_PIN_PWR    7   // panel power gate ("屏电源" in demo setup())
#define EPD_PIN_LED   19   // board power LED

// Panel is 122x250 portrait. Each of the 250 gate rows is 16 bytes
// (128 bits, of which 122 are visible).
#define EPD_NATIVE_W       122
#define EPD_NATIVE_H       250
#define EPD_BYTES_PER_ROW   16
#define EPD_BUF_BYTES      (EPD_BYTES_PER_ROW * EPD_NATIVE_H)  // 4000

void EPD_PowerOn(void);                        // drive PWR + LED pins
void EPD_Init(void);                           // GPIO init + reset + register setup
void EPD_Sleep(void);                          // deep sleep; EPD_Init() wakes it
void EPD_Update(void);                         // trigger refresh, wait for BUSY
void EPD_DisplayImage(const uint8_t *buf);     // send frame, load GC (full) waveform
void EPD_DisplayImage_DU(const uint8_t *buf);  // send frame, load DU (fast) waveform

#endif
