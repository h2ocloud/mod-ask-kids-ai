// net_ask.h — Wi-Fi 與協議 v1（docs/SERVER_API.md）的 HTTP 客戶端
// SPDX-License-Identifier: MIT
#pragma once
#include <stddef.h>
#include <stdint.h>

#include "src/core/proto.h"

// secrets.h 是否已填（至少一組 SSID，且伺服器網址是合法的 http(s)）
bool netConfigured();
bool netHasSecretsFile();

void netBegin();                          // Wi-Fi STA 模式、註冊 SSID（不會把帳密寫進 NVS）
bool netConnect(uint32_t timeoutMs);      // 阻塞式連線（開機用）
bool netConnected();
void netMaintain(uint32_t nowMs);         // 離線時定期重試
const char* netDeviceId();                // 16 位十六進位亂數 ID（存在 NVS，不是 MAC）

askcore::AskError netHealth();            // GET /v1/health

// 播放用回呼：由 netAsk 在收到語音時呼叫
struct AskHooks {
  void (*onResponseStart)(void* ctx);                         // 收到 200、開始播放前
  bool (*onPcm)(int16_t* samples, size_t n, uint32_t rate, void* ctx);  // 回 false＝停止
  bool (*poll)(void* ctx);                                     // 每讀一段呼叫；回 false＝停止（插話）
  void* ctx;
};

struct AskOutcome {
  askcore::AskError err = askcore::AskError::None;
  int httpStatus = 0;
  bool started = false;      // 是否已進入播放
  bool stopped = false;      // 被 onPcm/poll 要求停止（插話或播放上限）
  uint32_t pcmBytes = 0;
  uint32_t msToFirstByte = 0;
  uint32_t msTotal = 0;
};

// POST /v1/ask：上傳 wav、串流播放回答。阻塞到播完、出錯或被停止。
AskOutcome netAsk(const uint8_t* wav, size_t wavLen, const AskHooks& hooks);

// 最近一次回答附帶的顯示資料（沒有就回 nullptr）
const uint8_t* netLastBitmap();
const char* netLastAnswerText();
