// audio_dsp.h — 錄音／播放的小型訊號處理（純邏輯，定點數）
// SPDX-License-Identifier: MIT
#pragma once
#include <stddef.h>
#include <stdint.h>

namespace askcore {

inline int16_t clamp16(int32_t v) {
  if (v > 32767) return 32767;
  if (v < -32768) return -32768;
  return static_cast<int16_t>(v);
}

// INMP441 送出 24 bit 資料，放在 32 bit 槽的高位（左對齊）。
// 右移 shift 位得到 16 bit；shift 越小越大聲（14＝放大 4 倍、16＝原始高 16 位）。
// 用算術右移（帶號）；C++20 起保證，C++17 下 GCC/Clang 也是算術右移。
inline int16_t mic32to16(int32_t raw, int shift) {
  if (shift < 0) shift = 0;
  if (shift > 31) shift = 31;
  return clamp16(raw >> shift);
}

// 一階直流阻隔（高通）：y[n] = x[n] - x[n-1] + a*y[n-1]，a = 0.995（Q15 = 32604）
// 截止約 fs*(1-a)/(2π) ≈ 13 Hz @16 kHz，去掉麥克風的直流偏移，不影響人聲。
struct DcBlocker {
  int32_t x1 = 0;
  int32_t y1 = 0;
  static constexpr int32_t kA = 32604;
  int16_t step(int16_t x) {
    int32_t y = static_cast<int32_t>(x) - x1 + static_cast<int32_t>((static_cast<int64_t>(kA) * y1) >> 15);
    x1 = x;
    int16_t out = clamp16(y);
    y1 = out;  // 用截斷後的值回授，避免爆量後累積
    return out;
  }
  void reset() { x1 = 0; y1 = 0; }
};

// 音量 0–100 → Q15 增益。用平方曲線，聽感比較線性；100 = 原音量（不放大）。
inline int32_t volumeToQ15(uint8_t vol) {
  if (vol > 100) vol = 100;
  return static_cast<int32_t>((static_cast<uint32_t>(vol) * vol * 32768u) / 10000u);
}

inline void applyGainQ15(int16_t* s, size_t n, int32_t gainQ15) {
  if (gainQ15 >= 32768) return;  // 原音量，不動
  for (size_t i = 0; i < n; ++i) {
    s[i] = clamp16(static_cast<int32_t>((static_cast<int64_t>(s[i]) * gainQ15) >> 15));
  }
}

// 峰值（給 OLED 聆聽中的音量條用）
inline uint16_t peakAbs(const int16_t* s, size_t n) {
  uint16_t p = 0;
  for (size_t i = 0; i < n; ++i) {
    int32_t v = s[i] < 0 ? -static_cast<int32_t>(s[i]) : s[i];
    if (v > 32767) v = 32767;
    if (static_cast<uint16_t>(v) > p) p = static_cast<uint16_t>(v);
  }
  return p;
}

// 0–32767 的峰值換成 0–bars 格（對數感：每格約 -4 dB）
inline uint8_t peakToBars(uint16_t peak, uint8_t bars) {
  uint8_t b = 0;
  uint32_t th = 32767;
  // 由最大格往下找；每格門檻約乘 0.63
  for (uint8_t i = bars; i > 0; --i) {
    if (peak >= th) { b = i; break; }
    th = th * 63 / 100;
  }
  return b;
}

// ---------- 播放取樣率 ----------
// MAX98357A 的 LRCLK 只支援 8/16/32/44.1/48/88.2/96 kHz（datasheet：11.025/12/22.05/24 kHz 不支援）。
// 很多 TTS 預設輸出 24 kHz 或 22.05 kHz，所以這些用「整數倍線性內插升頻」轉成 48 k／44.1 k 再播。
inline bool ampNativeRate(uint32_t r) {
  return r == 8000 || r == 16000 || r == 32000 || r == 44100 || r == 48000;
}
// 回傳升頻倍數；0 = 不支援
inline uint8_t upsampleFactor(uint32_t r) {
  if (ampNativeRate(r)) return 1;
  if (r == 22050 || r == 24000) return 2;
  if (r == 11025 || r == 12000) return 4;
  return 0;
}

class Upsampler {
 public:
  void reset(uint8_t factor) { f_ = factor ? factor : 1; prev_ = 0; hasPrev_ = false; }
  uint8_t factor() const { return f_; }
  // out 至少要 n*factor 格；回傳輸出樣本數。每個輸入樣本 x 產生 f 個點：從上一個樣本線性走到 x。
  size_t process(const int16_t* in, size_t n, int16_t* out) {
    size_t o = 0;
    for (size_t i = 0; i < n; ++i) {
      int32_t x = in[i];
      int32_t p = hasPrev_ ? prev_ : x;
      for (uint8_t k = 1; k <= f_; ++k) out[o++] = static_cast<int16_t>(p + (x - p) * k / f_);
      prev_ = x;
      hasPrev_ = true;
    }
    return o;
  }

 private:
  uint8_t f_ = 1;
  int32_t prev_ = 0;
  bool hasPrev_ = false;
};

// 錄音緩衝（外部配置的記憶體，通常在 PSRAM；核心只管索引與上限）
class RecordBuffer {
 public:
  RecordBuffer() = default;
  void attach(int16_t* mem, size_t capSamples) { mem_ = mem; cap_ = capSamples; len_ = 0; }
  void clear() { len_ = 0; }
  // 回傳實際寫入的樣本數；寫滿就停（不覆蓋舊資料）
  size_t push(const int16_t* s, size_t n) {
    if (!mem_) return 0;
    size_t room = cap_ - len_;
    size_t k = n < room ? n : room;
    for (size_t i = 0; i < k; ++i) mem_[len_ + i] = s[i];
    len_ += k;
    return k;
  }
  bool full() const { return mem_ && len_ >= cap_; }
  size_t length() const { return len_; }
  size_t capacity() const { return cap_; }
  const int16_t* data() const { return mem_; }
  int16_t* data() { return mem_; }
  uint32_t millis(uint32_t rate) const { return rate ? static_cast<uint32_t>((static_cast<uint64_t>(len_) * 1000u) / rate) : 0; }

 private:
  int16_t* mem_ = nullptr;
  size_t cap_ = 0;
  size_t len_ = 0;
};

}  // namespace askcore
