// display.h — OLED（SSD1315／SSD1306 相容，128×64，I2C）狀態畫面
// SPDX-License-Identifier: MIT
//
// 畫面由獨立的 FreeRTOS 工作每秒重畫約 8 次：主程式卡在 HTTP 等待時，臉的動畫照樣會動。
// 主程式只呼叫 ui*() 更新「要顯示什麼」，不直接碰 I2C。
#pragma once
#include <stdint.h>

#include "src/core/ask_state.h"
#include "src/core/proto.h"

void uiBegin();                                   // 初始化 OLED 並啟動繪圖工作
void uiSetState(askcore::State s);                // 換狀態（同時清掉上一題的回答文字／圖）
void uiSetError(askcore::AskError e);             // 錯誤種類（Error 狀態用）
void uiSetLevel(uint8_t bars);                    // 聆聽中的音量條 0–12
void uiSetRecordLeft(uint8_t seconds);            // 聆聽中剩幾秒
void uiSetAnswerBitmap(const uint8_t* bm512);     // 伺服器給的 128×32 點陣（nullptr＝清除）
void uiSetAnswerAscii(const char* text);          // 純 ASCII 的回答文字（nullptr＝清除）
