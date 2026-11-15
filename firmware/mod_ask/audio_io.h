// audio_io.h — INMP441 錄音（I2S 輸入）與 MAX98357A 播放（I2S 輸出）
// SPDX-License-Identifier: MIT
#pragma once
#include <stddef.h>
#include <stdint.h>

// 開機呼叫一次：配置 PSRAM 錄音緩衝、啟動麥克風 I2S 與擷取工作。失敗回 false（多半是沒開 PSRAM）。
bool audioBegin();

// 錄音：按下時 start、放開時 stop。擷取工作在背景把聲音寫進 PSRAM 緩衝。
void audioStartRecording();
void audioStopRecording();           // 會等擷取工作停好（最多約 50 ms）
bool audioRecordFull();              // 到達錄音上限
uint32_t audioRecordedMs();
uint8_t audioLevelBars();            // 最近一格的音量條 0–12

// 取得「WAV 標頭＋PCM」連續記憶體，直接拿去 HTTP POST。呼叫前必須已 stop。
const uint8_t* audioWavBuffer(size_t* outLen);

// 播放：rate 由伺服器 WAV 決定。write 會阻塞到 DMA 有空位（天然節流）。
bool audioSpeakerBegin(uint32_t rate);
size_t audioSpeakerWrite(int16_t* samples, size_t count);  // 會就地套用音量
void audioSpeakerEnd();              // 補一小段靜音再關，避免「啵」聲
void audioSetVolume(uint8_t vol);    // 0–100，超過 SPEAKER_VOLUME_MAX 會被壓回上限

// 本機提示音（離線時用；不需要網路）
void audioBeep(uint16_t freqHz, uint16_t ms);
