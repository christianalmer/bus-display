#include "epd_driver.h"

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

/* BUSY is active-low on this controller: wait while the line is low.
 * delay(1) keeps the idle task fed during multi-second GC refreshes.
 * 15s timeout so a dead/mismatched panel can't hang the sketch silently. */
static void EPD_READBUSY(void) {
  uint32_t t0 = millis();
  while (digitalRead(EPD_PIN_BUSY) == 0) {
    if (millis() - t0 > 15000) {
      Serial.println("EPD: BUSY timeout (panel not responding?)");
      return;
    }
    delay(1);
  }
  Serial.printf("EPD: refresh done in %lu ms\n", (unsigned long)(millis() - t0));
}

/* ---------------- waveform LUTs (copied verbatim from demo) ------------- */

static const unsigned char lut_R20_GC[56] = {
  0x01, 0x00, 0x14, 0x14, 0x01, 0x00, 0x00, 0x01,
};
static const unsigned char lut_R21_GC[56] = {
  0x01, 0x60, 0x14, 0x14, 0x01, 0x00, 0x00, 0x01,
};
static const unsigned char lut_R22_GC[56] = {
  0x01, 0x20, 0x14, 0x14, 0x01, 0x00, 0x00, 0x01,
};
static const unsigned char lut_R23_GC[56] = {
  0x01, 0x10, 0x14, 0x14, 0x01, 0x00, 0x00, 0x01,
};
static const unsigned char lut_R24_GC[56] = {
  0x01, 0x90, 0x14, 0x14, 0x01, 0x00, 0x00, 0x01,
};

// DU ("direct update") ~300 ms waveform, used for the per-minute refresh
static const unsigned char lut_R20_DU[56] = {
  0x01, 0x00, 0x14, 0x01, 0x01, 0x00, 0x00, 0x00,
};
static const unsigned char lut_R21_DU[56] = {
  0x01, 0x00, 0x14, 0x01, 0x01, 0x00, 0x00, 0x00,
};
static const unsigned char lut_R22_DU[56] = {
  0x01, 0x80, 0x14, 0x01, 0x01, 0x00, 0x00, 0x00,
};
static const unsigned char lut_R23_DU[56] = {
  0x01, 0x40, 0x14, 0x01, 0x01, 0x00, 0x00, 0x00,
};
static const unsigned char lut_R24_DU[56] = {
  0x01, 0x00, 0x14, 0x01, 0x01, 0x00, 0x00, 0x00,
};

/* The demo alternates which of R22/R23 gets which table on every refresh
 * (polarity rotation); preserved as-is. */
static uint8_t lut_flag = 0;

static void lut_write(const unsigned char *r20, const unsigned char *r21,
                      const unsigned char *r22, const unsigned char *r23,
                      const unsigned char *r24) {
  uint8_t count;
  EPD_WR_REG(0x20);
  for (count = 0; count < 56; count++) EPD_WR_DATA8(r20[count]);
  EPD_WR_REG(0x21);
  for (count = 0; count < 56; count++) EPD_WR_DATA8(r21[count]);
  EPD_WR_REG(0x24);
  for (count = 0; count < 56; count++) EPD_WR_DATA8(r24[count]);
  if (lut_flag == 0) {
    EPD_WR_REG(0x22);
    for (count = 0; count < 56; count++) EPD_WR_DATA8(r22[count]);
    EPD_WR_REG(0x23);
    for (count = 0; count < 56; count++) EPD_WR_DATA8(r23[count]);
    lut_flag = 1;
  } else {
    EPD_WR_REG(0x22);
    for (count = 0; count < 56; count++) EPD_WR_DATA8(r23[count]);
    EPD_WR_REG(0x23);
    for (count = 0; count < 56; count++) EPD_WR_DATA8(r22[count]);
    lut_flag = 0;
  }
}

static void lut_GC(void) {
  lut_write(lut_R20_GC, lut_R21_GC, lut_R22_GC, lut_R23_GC, lut_R24_GC);
}

static void lut_DU(void) {
  lut_write(lut_R20_DU, lut_R21_DU, lut_R22_DU, lut_R23_DU, lut_R24_DU);
}

/* ---------------- panel control (from demo EPD_Init.cpp) ---------------- */

void EPD_PowerOn(void) {
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

/* Hardware reset — also required to wake from EPD_Sleep() */
static void EPD_HW_SW_RESET(void) {
  delay(100);
  digitalWrite(EPD_PIN_RES, HIGH);
  delay(10);
  digitalWrite(EPD_PIN_RES, LOW);
  delay(100);
  digitalWrite(EPD_PIN_RES, HIGH);
  delay(100);
}

void EPD_Init(void) {
  EPD_GPIOInit();
  EPD_HW_SW_RESET();

  EPD_WR_REG(0x00);      // panel setting
  EPD_WR_DATA8(0xF7);
  EPD_WR_DATA8(0x8A);

  EPD_WR_REG(0x01);      // power setting
  EPD_WR_DATA8(0x03);
  EPD_WR_DATA8(0x00);
  EPD_WR_DATA8(0x3F);
  EPD_WR_DATA8(0x3F);
  EPD_WR_DATA8(0x03);

  EPD_WR_REG(0x03);
  EPD_WR_DATA8(0x00);

  EPD_WR_REG(0x06);      // booster
  EPD_WR_DATA8(0x27);
  EPD_WR_DATA8(0x27);
  EPD_WR_DATA8(0x2F);

  EPD_WR_REG(0x30);
  EPD_WR_DATA8(0x0D);

  EPD_WR_REG(0x60);
  EPD_WR_DATA8(0x22);

  EPD_WR_REG(0x82);
  EPD_WR_DATA8(0x07);

  EPD_WR_REG(0xE3);
  EPD_WR_DATA8(0x88);

  EPD_WR_REG(0x41);
  EPD_WR_DATA8(0x00);

  EPD_WR_REG(0x61);      // resolution: 128 x 250
  EPD_WR_DATA8(0x80);
  EPD_WR_DATA8(0x00);
  EPD_WR_DATA8(0xFA);

  EPD_WR_REG(0x65);
  EPD_WR_DATA8(0x00);
  EPD_WR_DATA8(0x00);
  EPD_WR_DATA8(0x00);

  EPD_WR_REG(0x50);      // border / VCOM
  EPD_WR_DATA8(0xB7);
}

void EPD_Sleep(void) {
  EPD_WR_REG(0x07);
  EPD_WR_DATA8(0xA5);
  delay(20);
}

void EPD_Update(void) {
  EPD_WR_REG(0x17);      // display refresh
  EPD_WR_DATA8(0xA5);
  EPD_READBUSY();
}

static void send_frame(const uint8_t *buf) {
  EPD_WR_REG(0x50);
  EPD_WR_DATA8(0xD7);
  EPD_WR_REG(0x13);      // new-frame RAM
  for (uint32_t i = 0; i < EPD_BUF_BYTES; i++) EPD_WR_DATA8(buf[i]);
}

void EPD_DisplayImage(const uint8_t *buf) {
  send_frame(buf);
  lut_GC();
}

void EPD_DisplayImage_DU(const uint8_t *buf) {
  send_frame(buf);
  lut_DU();
}
