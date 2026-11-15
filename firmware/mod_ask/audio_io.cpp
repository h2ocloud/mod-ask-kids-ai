// audio_io.cpp — I2S 錄音／播放（Arduino-ESP32 3.x 的 ESP_I2S）
// SPDX-License-Identifier: MIT
#include "audio_io.h"

#include <Arduino.h>
#include <ESP_I2S.h>
#include <math.h>
#include <atomic>

#include "config.h"
#include "src/core/audio_dsp.h"
#include "src/core/wav.h"

namespace {

I2SClass i2sMic(I2S_NUM_0);
I2SClass i2sSpk(I2S_NUM_1);

constexpr size_t kFrameSamples = MIC_SAMPLE_RATE / 50;  // 20 ms
constexpr size_t kPrerollSamples = MIC_SAMPLE_RATE * REC_PREROLL_MS / 1000;
constexpr size_t kRecCapSamples = MIC_SAMPLE_RATE * REC_MAX_SECONDS;

uint8_t* wavMem = nullptr;  // [44 B 標頭][PCM...]，放 PSRAM
askcore::RecordBuffer rec;
int16_t preroll[kPrerollSamples];
size_t prerollPos = 0;
bool prerollFilled = false;
askcore::DcBlocker dc;

std::atomic<bool> wantRec{false};
std::atomic<bool> recActive{false};
std::atomic<bool> recFull{false};
std::atomic<uint8_t> levelBars{0};

int32_t gainQ15 = askcore::volumeToQ15(SPEAKER_VOLUME);
bool spkOn = false;
uint32_t spkRate = 0;

void captureTask(void*) {
  static int32_t raw[kFrameSamples];
  static int16_t pcm[kFrameSamples];
  for (;;) {
    size_t got = i2sMic.readBytes(reinterpret_cast<char*>(raw), sizeof raw);
    size_t n = got / sizeof(int32_t);
    if (n == 0) { vTaskDelay(1); continue; }
    for (size_t i = 0; i < n; ++i) pcm[i] = dc.step(askcore::mic32to16(raw[i], MIC_SHIFT));
    levelBars.store(askcore::peakToBars(askcore::peakAbs(pcm, n), 12));

    bool want = wantRec.load();
    if (want && !recActive.load()) {
      // 開始：先放入按下前的 200 ms（依時間順序）
      rec.clear();
      recFull.store(false);
      if (prerollFilled) rec.push(preroll + prerollPos, kPrerollSamples - prerollPos);
      rec.push(preroll, prerollPos);
      recActive.store(true);
    }
    if (recActive.load()) {
      if (!want) {
        recActive.store(false);
      } else if (rec.push(pcm, n) < n || rec.full()) {
        recFull.store(true);
      }
    }
    // 預錄環形緩衝（一直更新）
    for (size_t i = 0; i < n; ++i) {
      preroll[prerollPos++] = pcm[i];
      if (prerollPos == kPrerollSamples) { prerollPos = 0; prerollFilled = true; }
    }
  }
}

}  // namespace

bool audioBegin() {
  size_t bytes = askcore::kWavHeaderBytes + kRecCapSamples * sizeof(int16_t);
  wavMem = static_cast<uint8_t*>(ps_malloc(bytes));
  if (!wavMem) {
    Serial.printf("[AUDIO] ps_malloc(%u) failed: is PSRAM enabled (OPI)?\n", static_cast<unsigned>(bytes));
    return false;
  }
  rec.attach(reinterpret_cast<int16_t*>(wavMem + askcore::kWavHeaderBytes), kRecCapSamples);

  // INMP441：L/R 接 GND＝左聲道；資料 24 bit 放在 32 bit 槽（每個 WS 週期 64 個 SCK）
  i2sMic.setPins(PIN_MIC_SCK, PIN_MIC_WS, -1, PIN_MIC_SD);
  i2sMic.setTimeout(100);
  if (!i2sMic.begin(I2S_MODE_STD, MIC_SAMPLE_RATE, I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_MONO, I2S_STD_SLOT_LEFT)) {
    Serial.println("[AUDIO] mic I2S begin failed");
    return false;
  }
  xTaskCreatePinnedToCore(captureTask, "mic", 6144, nullptr, 3, nullptr, 0);
  return true;
}

void audioStartRecording() { wantRec.store(true); }

void audioStopRecording() {
  wantRec.store(false);
  for (int i = 0; i < 10 && recActive.load(); ++i) delay(5);
  recActive.store(false);
}

bool audioRecordFull() { return recFull.load(); }
uint32_t audioRecordedMs() { return rec.millis(MIC_SAMPLE_RATE); }
uint8_t audioLevelBars() { return levelBars.load(); }

const uint8_t* audioWavBuffer(size_t* outLen) {
  uint32_t dataBytes = static_cast<uint32_t>(rec.length() * sizeof(int16_t));
  askcore::wavHeaderPcm16Mono(wavMem, MIC_SAMPLE_RATE, dataBytes);
  *outLen = askcore::kWavHeaderBytes + dataBytes;
  return wavMem;
}

bool audioSpeakerBegin(uint32_t rate) {
  if (spkOn && rate == spkRate) return true;
  if (spkOn) audioSpeakerEnd();
  i2sSpk.setPins(PIN_SPK_BCLK, PIN_SPK_LRC, PIN_SPK_DIN);
  // MAX98357A 的 SD 腳浮接＝(L+R)/2：左右聲道送同一份，音量才不會減半
  if (!i2sSpk.begin(I2S_MODE_STD, rate, I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO, I2S_STD_SLOT_BOTH)) {
    Serial.println("[AUDIO] speaker I2S begin failed");
    return false;
  }
  spkOn = true;
  spkRate = rate;
  return true;
}

size_t audioSpeakerWrite(int16_t* s, size_t n) {
  if (!spkOn) return 0;
  askcore::applyGainQ15(s, n, gainQ15);
  return i2sSpk.write(reinterpret_cast<const uint8_t*>(s), n * sizeof(int16_t)) / sizeof(int16_t);
}

void audioSpeakerEnd() {
  if (!spkOn) return;
  static int16_t zeros[256] = {0};
  size_t total = spkRate / 20;  // 50 ms 靜音
  while (total > 0) {
    size_t k = total < 256 ? total : 256;
    i2sSpk.write(reinterpret_cast<const uint8_t*>(zeros), k * sizeof(int16_t));
    total -= k;
  }
  i2sSpk.end();
  spkOn = false;
  spkRate = 0;
}

void audioSetVolume(uint8_t vol) {
  if (vol > SPEAKER_VOLUME_MAX) vol = SPEAKER_VOLUME_MAX;
  gainQ15 = askcore::volumeToQ15(vol);
}

void audioBeep(uint16_t freqHz, uint16_t ms) {
  const uint32_t rate = 16000;
  if (!audioSpeakerBegin(rate)) return;
  int16_t buf[160];
  uint32_t total = rate * ms / 1000;
  float ph = 0.0f;
  const float step = 2.0f * static_cast<float>(M_PI) * freqHz / rate;
  uint32_t done = 0;
  while (done < total) {
    size_t k = total - done < 160 ? total - done : 160;
    for (size_t i = 0; i < k; ++i) {
      // 前後 10 ms 淡入淡出，避免爆音；振幅只有滿刻度的 1/4
      uint32_t idx = done + i;
      float env = 1.0f;
      uint32_t ramp = rate / 100;
      if (idx < ramp) env = static_cast<float>(idx) / ramp;
      if (total - idx < ramp) env = static_cast<float>(total - idx) / ramp;
      buf[i] = static_cast<int16_t>(8000.0f * env * sinf(ph));
      ph += step;
      if (ph > 2.0f * static_cast<float>(M_PI)) ph -= 2.0f * static_cast<float>(M_PI);
    }
    audioSpeakerWrite(buf, k);
    done += k;
  }
}
