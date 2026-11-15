// display.cpp — OLED 畫面（U8g2，BSD-2-Clause）
// SPDX-License-Identifier: MIT
#include "display.h"

#include <Arduino.h>
#include <U8g2lib.h>
#include <Wire.h>
#include <string.h>

#include "config.h"
#include "labels_zh.h"

using askcore::AskError;
using askcore::State;

namespace {

// SSD1315 與 SSD1306 指令相容，用 U8g2 的 SSD1306 驅動；全畫面緩衝（1 KB）
U8G2_SSD1306_128X64_NONAME_F_HW_I2C oled(OLED_ROTATE_180 ? U8G2_R2 : U8G2_R0, U8X8_PIN_NONE, PIN_OLED_SCL,
                                         PIN_OLED_SDA);

struct UiModel {
  State state = State::ConnectingWifi;
  AskError err = AskError::None;
  uint8_t bars = 0;
  uint8_t recLeft = 0;
  bool hasBitmap = false;
  uint8_t bitmap[askcore::kBitmapBytes] = {0};
  char ascii[64] = {0};
};

UiModel model;
SemaphoreHandle_t lock = nullptr;
bool ready = false;

const ZhLabel& titleFor(State s) {
  switch (s) {
    case State::NoConfig: return T_NOCONFIG;
    case State::ConnectingWifi: return T_WIFI;
    case State::Offline: return T_OFFLINE;
    case State::Idle: return T_IDLE;
    case State::Listening: return T_LISTEN;
    case State::Thinking: return T_THINK;
    case State::Speaking: return T_SPEAK;
    case State::Error: return T_ERROR;
  }
  return T_BOOT;
}

const ZhLabel& hintFor(State s) {
  switch (s) {
    case State::NoConfig: return H_NOCONFIG;
    case State::ConnectingWifi: return H_WIFI;
    case State::Offline: return H_OFFLINE;
    case State::Idle: return H_IDLE;
    case State::Listening: return H_LISTEN;
    case State::Thinking: return H_THINK;
    case State::Speaking: return H_SPEAK;
    case State::Error: return E_SERVER;
  }
  return H_IDLE;
}

const ZhLabel& errorLabel(AskError e) {
  switch (e) {
    case AskError::NoConfig: return H_NOCONFIG;
    case AskError::NoWifi: return E_NOWIFI;
    case AskError::Connect: return E_CONNECT;
    case AskError::Timeout: return E_TIMEOUT;
    case AskError::BadAudio: return E_BADAUDIO;
    case AskError::TooShort: return E_TOOSHORT;
    case AskError::Unauthorized: return E_AUTH;
    case AskError::NotFound: return E_NOTFOUND;
    case AskError::TooLong: return E_TOOLONG;
    case AskError::NoSpeech: return E_NOSPEECH;
    case AskError::RateLimited: return E_RATELIMIT;
    case AskError::Server: return E_SERVER;
    case AskError::BadResponse: return E_BADREPLY;
    case AskError::None: break;
  }
  return E_SERVER;
}

void drawLabel(const ZhLabel& l, int x, int y) { oled.drawXBM(x, y, l.w, l.h, l.bits); }

// 左上角 30×30 的臉。tick 每格約 125 ms，用來做簡單動畫。
void drawFace(State s, uint32_t tick) {
  const int cx = 14, cy = 15, r = 13;
  oled.drawCircle(cx, cy, r);
  switch (s) {
    case State::Idle:
    case State::ConnectingWifi: {
      bool blink = (tick % 24) == 0;  // 約 3 秒眨一次眼
      if (blink) {
        oled.drawHLine(7, 12, 5);
        oled.drawHLine(17, 12, 5);
      } else {
        oled.drawDisc(9, 12, 2);
        oled.drawDisc(19, 12, 2);
      }
      oled.drawCircle(cx, 16, 6, U8G2_DRAW_LOWER_LEFT | U8G2_DRAW_LOWER_RIGHT);  // 微笑
      break;
    }
    case State::Listening:
      oled.drawDisc(9, 11, 2);
      oled.drawDisc(19, 11, 2);
      oled.drawCircle(cx, 21, 3);  // 「喔」嘴
      break;
    case State::Thinking:
      oled.drawDisc(10 + (tick % 4 == 1 ? 1 : 0), 9, 2);  // 眼睛往上看、左右飄
      oled.drawDisc(20 + (tick % 4 == 1 ? 1 : 0), 9, 2);
      oled.drawHLine(10, 21, 9);
      break;
    case State::Speaking: {
      oled.drawDisc(9, 11, 2);
      oled.drawDisc(19, 11, 2);
      int open = (tick % 3);  // 嘴巴開合
      oled.drawFilledEllipse(cx, 21, 5, open + 1);
      break;
    }
    case State::Offline:
      oled.drawDisc(9, 12, 2);
      oled.drawDisc(19, 12, 2);
      oled.drawCircle(cx, 25, 6, U8G2_DRAW_UPPER_LEFT | U8G2_DRAW_UPPER_RIGHT);  // 難過
      break;
    case State::Error:
      oled.drawLine(7, 9, 11, 13); oled.drawLine(11, 9, 7, 13);    // X 眼
      oled.drawLine(17, 9, 21, 13); oled.drawLine(21, 9, 17, 13);
      oled.drawCircle(cx, 25, 6, U8G2_DRAW_UPPER_LEFT | U8G2_DRAW_UPPER_RIGHT);
      break;
    case State::NoConfig:
      oled.setFont(u8g2_font_6x10_tf);
      oled.drawStr(7, 15, "?");
      oled.drawStr(17, 15, "?");
      oled.drawHLine(10, 21, 9);
      break;
  }
}

void render(const UiModel& m, uint32_t tick) {
  oled.clearBuffer();
  drawFace(m.state, tick);
  drawLabel(titleFor(m.state), 32, 2);

  // 下半部（y 32–63）：伺服器點陣 > ASCII 回答 > 狀態提示
  if (m.state == State::Speaking && m.hasBitmap) {
    for (int y = 0; y < askcore::kBitmapH; ++y)
      for (int x = 0; x < askcore::kBitmapW; ++x)
        if (askcore::bitmapPixel(m.bitmap, x, y)) oled.drawPixel(x, 32 + y);
  } else if (m.state == State::Speaking && m.ascii[0]) {
    oled.setFont(u8g2_font_6x10_tf);
    char line[22];
    size_t n = strlen(m.ascii);
    for (int row = 0; row < 3; ++row) {
      size_t off = static_cast<size_t>(row) * 21;
      if (off >= n) break;
      size_t k = n - off < 21 ? n - off : 21;
      memcpy(line, m.ascii + off, k);
      line[k] = '\0';
      oled.drawStr(0, 42 + row * 10, line);
    }
  } else if (m.state == State::Error) {
    drawLabel(errorLabel(m.err), 0, 36);
    oled.setFont(u8g2_font_6x10_tf);
    oled.drawStr(0, 62, askcore::errorShort(m.err));
  } else {
    drawLabel(hintFor(m.state), 0, 35);
    if (m.state == State::Listening) {
      for (uint8_t i = 0; i < 12; ++i) {  // 音量條
        int x = i * 8;
        if (i < m.bars) oled.drawBox(x, 54, 6, 8);
        else oled.drawFrame(x, 58, 6, 4);
      }
      char sec[8];
      snprintf(sec, sizeof sec, "%us", static_cast<unsigned>(m.recLeft));
      oled.setFont(u8g2_font_6x10_tf);
      oled.drawStr(104, 62, sec);
    } else if (m.state == State::Thinking || m.state == State::ConnectingWifi) {
      for (uint32_t i = 0; i < 3; ++i) {  // 跑動的三個點
        int x = 52 + static_cast<int>(i) * 10;
        if (tick % 4 == i) oled.drawDisc(x, 56, 3);
        else oled.drawCircle(x, 56, 2);
      }
    }
  }
  oled.sendBuffer();
}

void uiTask(void*) {
  uint32_t tick = 0;
  UiModel local;
  for (;;) {
    if (xSemaphoreTake(lock, pdMS_TO_TICKS(50)) == pdTRUE) {
      local = model;
      xSemaphoreGive(lock);
    }
    render(local, tick++);
    vTaskDelay(pdMS_TO_TICKS(125));
  }
}

template <typename F>
void withLock(F f) {
  if (!lock) return;
  if (xSemaphoreTake(lock, pdMS_TO_TICKS(100)) == pdTRUE) {
    f();
    xSemaphoreGive(lock);
  }
}

}  // namespace

void uiBegin() {
  lock = xSemaphoreCreateMutex();
  oled.setI2CAddress(OLED_I2C_ADDR * 2);  // U8g2 用 8-bit 位址
  oled.setBusClock(400000);
  ready = oled.begin();
  if (!ready) {
    Serial.println("[OLED] init failed (check SDA/SCL wiring and I2C address)");
  }
  // 優先權 1、釘在 core 1（和 loop 同核，靠 FreeRTOS 時間切片）
  xTaskCreatePinnedToCore(uiTask, "ui", 4096, nullptr, 1, nullptr, 1);
}

void uiSetState(State s) {
  withLock([&] {
    if (model.state != s && s != State::Speaking) {
      model.hasBitmap = false;
      model.ascii[0] = '\0';
    }
    model.state = s;
    if (s != State::Listening) model.bars = 0;
  });
}

void uiSetError(AskError e) { withLock([&] { model.err = e; }); }
void uiSetLevel(uint8_t bars) { withLock([&] { model.bars = bars > 12 ? 12 : bars; }); }
void uiSetRecordLeft(uint8_t seconds) { withLock([&] { model.recLeft = seconds; }); }

void uiSetAnswerBitmap(const uint8_t* bm) {
  withLock([&] {
    if (bm) {
      memcpy(model.bitmap, bm, askcore::kBitmapBytes);
      model.hasBitmap = true;
    } else {
      model.hasBitmap = false;
    }
  });
}

void uiSetAnswerAscii(const char* text) {
  withLock([&] {
    if (text) {
      strncpy(model.ascii, text, sizeof(model.ascii) - 1);
      model.ascii[sizeof(model.ascii) - 1] = '\0';
    } else {
      model.ascii[0] = '\0';
    }
  });
}
