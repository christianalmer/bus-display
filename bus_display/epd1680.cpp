#include "epd1680.h"

/* ---------------- bit-banged SPI bus (from demo spi.cpp) ---------------- */

static void EPD_WR_Bus(uint8_t dat) {
  digitalWrite(EPD_PIN_CS, LOW);
  for (uint8_t i = 0; i < 8; i++) {
    digitalWrite(EPD_PIN_SCK, LOW);
    digitalWrite(EPD_PIN_MOSI, (dat & 0x80) ? HIGH : LOW);
    digitalWrite(EPD_PIN_SCK, HIGH);
    dat <<= 1;
  }
  digitalWrite(EPD_PIN_CS, HIGH);
}

static void EPD_WR_REG(uint8_t reg) {
  digitalWrite(EPD_PIN_DC, LOW);
  EPD_WR_Bus(reg);
  digitalWrite(EPD_PIN_DC, HIGH);
}

static void EPD_WR_DATA8(uint8_t dat) {
  digitalWrite(EPD_PIN_DC, HIGH);
  EPD_WR_Bus(dat);
}

/* SSD1680 BUSY is active-HIGH: wait while high (opposite of the JD79661).
 * 15s timeout so a dead panel can't hang the sketch silently. */
static void EPD_READBUSY(void) {
  uint32_t t0 = millis();
  while (digitalRead(EPD_PIN_BUSY) == 1) {
    if (millis() - t0 > 15000) {
      Serial.println("EPD: BUSY timeout (panel not responding?)");
      return;
    }
    delay(1);
  }
  delayMicroseconds(100);
}

/* ---------------- panel control (from demo EPD_Init.cpp) ---------------- */

void EPD1680_PowerOn(void) {
  pinMode(EPD_PIN_PWR, OUTPUT);
  digitalWrite(EPD_PIN_PWR, HIGH);
  pinMode(EPD_PIN_LED, OUTPUT);
  digitalWrite(EPD_PIN_LED, HIGH);
}

static void EPD_GPIOInit(void) {
  pinMode(EPD_PIN_SCK, OUTPUT);
  pinMode(EPD_PIN_MOSI, OUTPUT);
  pinMode(EPD_PIN_RES, OUTPUT);
  pinMode(EPD_PIN_DC, OUTPUT);
  pinMode(EPD_PIN_CS, OUTPUT);
  pinMode(EPD_PIN_BUSY, INPUT);
}

/* Hardware + software reset — also required to wake from deep sleep */
static void EPD_HW_SW_RESET(void) {
  delay(100);
  digitalWrite(EPD_PIN_RES, HIGH);
  delay(10);
  digitalWrite(EPD_PIN_RES, LOW);
  delay(10);
  digitalWrite(EPD_PIN_RES, HIGH);
  delay(10);
  EPD_READBUSY();
  EPD_WR_REG(0x12);  // SWRESET
  EPD_READBUSY();
}

void EPD1680_Init(void) {
  EPD_GPIOInit();
  EPD_HW_SW_RESET();

  EPD_WR_REG(0x01);   // driver output control: 250 gate lines
  EPD_WR_DATA8(0xF9);
  EPD_WR_DATA8(0x00);
  EPD_WR_DATA8(0x00);

  EPD_WR_REG(0x11);   // data entry mode: x/y increment
  EPD_WR_DATA8(0x03);

  EPD_WR_REG(0x44);   // RAM x window: 0..15 (16 bytes = 128 bits)
  EPD_WR_DATA8(0x00);
  EPD_WR_DATA8(0x0F);

  EPD_WR_REG(0x45);   // RAM y window: 0..249
  EPD_WR_DATA8(0x00);
  EPD_WR_DATA8(0x00);
  EPD_WR_DATA8(0xF9);
  EPD_WR_DATA8(0x00);

  EPD_WR_REG(0x3C);   // border waveform
  EPD_WR_DATA8(0x01);
  EPD_READBUSY();

  EPD_WR_REG(0x18);   // internal temperature sensor
  EPD_WR_DATA8(0x80);

  EPD_WR_REG(0x4E);   // RAM x address counter
  EPD_WR_DATA8(0x00);
  EPD_WR_REG(0x4F);   // RAM y address counter
  EPD_WR_DATA8(0x00);
  EPD_WR_DATA8(0x00);

  EPD_READBUSY();
}

void EPD1680_Sleep(void) {
  EPD_WR_REG(0x10);   // deep sleep mode 1: RAM retained
  EPD_WR_DATA8(0x01);
  EPD_WR_REG(0x3C);
  EPD_WR_DATA8(0x01);
  delay(20);
}

/* Reset the RAM address counter, then write one inverted frame.
 * target: 0x24 = current frame, 0x26 = previous frame.
 * Our buffer uses bit set = black; SSD1680 wants 1 = white, hence ~. */
static void writeRam(uint8_t target, const uint8_t *buf) {
  EPD_WR_REG(0x4E);
  EPD_WR_DATA8(0x00);
  EPD_WR_REG(0x4F);
  EPD_WR_DATA8(0x00);
  EPD_WR_DATA8(0x00);
  EPD_WR_REG(target);
  for (uint32_t i = 0; i < EPD_BUF_BYTES; i++) EPD_WR_DATA8(~buf[i]);
}

/* Shadow of the frame currently on the glass, kept in MCU RAM so partial
 * refreshes never depend on the controller retaining RAM 0x26 through
 * sleep/reset (some panels don't). */
static uint8_t prevFrame[EPD_BUF_BYTES];
static bool prevValid = false;

/* Full refresh: OTP Mode-1 waveform (0xF4, as in Elecrow's EPD_Update) */
void EPD1680_DisplayFull(const uint8_t *buf) {
  writeRam(0x24, buf);
  writeRam(0x26, buf);  // previous := current, clean base for next partial
  EPD_WR_REG(0x22);
  EPD_WR_DATA8(0xF4);
  EPD_WR_REG(0x20);
  EPD_READBUSY();
  memcpy(prevFrame, buf, EPD_BUF_BYTES);
  prevValid = true;
}

/* Fast partial: OTP Mode-2 waveform (0xFC, as in Elecrow's EPD_PartUpdate).
 * Diffs 0x24 (new) against 0x26 (old) — both rewritten explicitly here. */
void EPD1680_DisplayPartial(const uint8_t *buf) {
  if (!prevValid) {           // never partial onto unknown glass content
    EPD1680_DisplayFull(buf);
    return;
  }
  writeRam(0x26, prevFrame);  // exact on-glass frame as the diff base
  writeRam(0x24, buf);
  EPD_WR_REG(0x22);
  EPD_WR_DATA8(0xFC);
  EPD_WR_REG(0x20);
  EPD_READBUSY();
  EPD_WR_REG(0x3C);
  EPD_WR_DATA8(0x01);
  memcpy(prevFrame, buf, EPD_BUF_BYTES);
}
