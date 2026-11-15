// config.h — 腳位與可調參數（不含任何帳密或網址；那些放 secrets.h）
// SPDX-License-Identifier: MIT
#pragma once
#include <stdint.h>

#include "src/core/pins_guard.h"

#define MOD_ASK_FW_VERSION "0.1.0"

// ---------------- 腳位（ESP32-S3-DevKitC-1 N16R8；接線見 wiring/PINMAP.md） ----------------
// INMP441 麥克風（I2S 輸入；L/R 接 GND＝左聲道）
constexpr int PIN_MIC_WS = 4;    // J1-4
constexpr int PIN_MIC_SCK = 5;   // J1-5
constexpr int PIN_MIC_SD = 6;    // J1-6（麥克風資料 → ESP32）
// MAX98357A 功放（I2S 輸出）
constexpr int PIN_SPK_DIN = 7;   // J1-7（ESP32 → 功放資料）
constexpr int PIN_SPK_BCLK = 15; // J1-8
constexpr int PIN_SPK_LRC = 16;  // J1-9
// OLED（I2C，模組自帶上拉）
constexpr int PIN_OLED_SDA = 41; // J3-7
constexpr int PIN_OLED_SCL = 42; // J3-6
// 按住說話按鈕（另一腳接 GND，用內部上拉）
constexpr int PIN_BUTTON = 47;   // J3-17

static_assert(!askcore::pinForbidden(PIN_MIC_WS) && !askcore::pinForbidden(PIN_MIC_SCK) &&
                  !askcore::pinForbidden(PIN_MIC_SD) && !askcore::pinForbidden(PIN_SPK_DIN) &&
                  !askcore::pinForbidden(PIN_SPK_BCLK) && !askcore::pinForbidden(PIN_SPK_LRC) &&
                  !askcore::pinForbidden(PIN_OLED_SDA) && !askcore::pinForbidden(PIN_OLED_SCL) &&
                  !askcore::pinForbidden(PIN_BUTTON),
              "腳位踩到 strapping／USB／PSRAM／RGB LED／UART0，請看 wiring/PINMAP.md");

// ---------------- 錄音 ----------------
constexpr uint32_t MIC_SAMPLE_RATE = 16000;   // 協議 v1 固定 16 kHz
constexpr int MIC_SHIFT = 14;                 // 32→16 bit 右移位數；聲音太小改 13，爆音改 15
constexpr uint32_t REC_MAX_SECONDS = 12;      // 按住最多錄幾秒（PSRAM 緩衝 = 秒數 × 32 KB）
constexpr uint32_t REC_MIN_MS = 300;          // 短於此視為誤觸，不送出
constexpr uint32_t REC_PREROLL_MS = 200;      // 按下前先留的聲音（避免吃掉第一個字）
static_assert(REC_MAX_SECONDS >= 1 && REC_MAX_SECONDS <= 60, "錄音上限 1–60 秒");

// ---------------- 播放 ----------------
constexpr uint8_t SPEAKER_VOLUME = 60;        // 預設音量 0–100
constexpr uint8_t SPEAKER_VOLUME_MAX = 80;    // 硬上限：保護小朋友耳朵與 USB 供電（見 wiring/PINMAP.md §3）
constexpr uint32_t PLAY_MAX_SECONDS = 60;     // 單次回答播放上限
static_assert(SPEAKER_VOLUME <= SPEAKER_VOLUME_MAX && SPEAKER_VOLUME_MAX <= 100, "音量設定錯誤");

// ---------------- 網路（協議 docs/SERVER_API.md §4） ----------------
constexpr uint32_t ASK_CONNECT_TIMEOUT_MS = 5000;
constexpr uint16_t ASK_RESPONSE_TIMEOUT_MS = 20000;   // 上傳後等第一個位元組
constexpr uint32_t ASK_STREAM_IDLE_TIMEOUT_MS = 5000; // 播放中資料間隔
constexpr int ASK_MAX_RETRIES = 1;                    // 只在沒拿到狀態碼時重送
constexpr uint16_t HEALTH_TIMEOUT_MS = 5000;
constexpr uint32_t WIFI_CONNECT_TIMEOUT_MS = 20000;   // 開機找 Wi-Fi 的時間
constexpr uint32_t WIFI_RETRY_INTERVAL_MS = 30000;    // 離線時多久重掃一次

// ---------------- 顯示 ----------------
constexpr uint8_t OLED_I2C_ADDR = 0x3C;       // 少數模組是 0x3D（背面跳線）
constexpr bool OLED_ROTATE_180 = true;        // 外殼裡 OLED 倒裝（排針朝下）；平放測試時改 false
constexpr uint32_t ERROR_SHOW_MS = 3000;      // 錯誤畫面停留時間
constexpr uint32_t BUTTON_DEBOUNCE_MS = 30;
