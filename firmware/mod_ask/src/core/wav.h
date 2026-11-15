// wav.h — WAV 標頭產生與「串流」解析（純邏輯，主機端可測）
// SPDX-License-Identifier: MIT
//
// 上傳：錄音前面加 44 B 標準 PCM 標頭。
// 下載：伺服器回的 WAV 可能分很多小段到達（chunked），也可能 RIFF/data 長度填 0 或 0xFFFFFFFF。
//       解析器一次吃任意長度的位元組，把 PCM 樣本（一定是完整的 16 bit）交給回呼。
#pragma once
#include <stddef.h>
#include <stdint.h>

namespace askcore {

inline void put16le(uint8_t* p, uint16_t v) { p[0] = static_cast<uint8_t>(v); p[1] = static_cast<uint8_t>(v >> 8); }
inline void put32le(uint8_t* p, uint32_t v) {
  p[0] = static_cast<uint8_t>(v); p[1] = static_cast<uint8_t>(v >> 8);
  p[2] = static_cast<uint8_t>(v >> 16); p[3] = static_cast<uint8_t>(v >> 24);
}
inline uint16_t get16le(const uint8_t* p) { return static_cast<uint16_t>(p[0] | (p[1] << 8)); }
inline uint32_t get32le(const uint8_t* p) {
  return static_cast<uint32_t>(p[0]) | (static_cast<uint32_t>(p[1]) << 8) |
         (static_cast<uint32_t>(p[2]) << 16) | (static_cast<uint32_t>(p[3]) << 24);
}

constexpr size_t kWavHeaderBytes = 44;

// 16 bit 單聲道 PCM 的 44 B 標頭
inline void wavHeaderPcm16Mono(uint8_t out[kWavHeaderBytes], uint32_t sampleRate, uint32_t dataBytes) {
  out[0] = 'R'; out[1] = 'I'; out[2] = 'F'; out[3] = 'F';
  put32le(out + 4, 36u + dataBytes);
  out[8] = 'W'; out[9] = 'A'; out[10] = 'V'; out[11] = 'E';
  out[12] = 'f'; out[13] = 'm'; out[14] = 't'; out[15] = ' ';
  put32le(out + 16, 16);             // fmt chunk 大小
  put16le(out + 20, 1);              // PCM
  put16le(out + 22, 1);              // 單聲道
  put32le(out + 24, sampleRate);
  put32le(out + 28, sampleRate * 2); // byte rate
  put16le(out + 32, 2);              // block align
  put16le(out + 34, 16);             // bits
  out[36] = 'd'; out[37] = 'a'; out[38] = 't'; out[39] = 'a';
  put32le(out + 40, dataBytes);
}

enum class WavError : uint8_t { None, NotRiff, NotWave, BadFmt, NotPcm16Mono, BadRate, DataBeforeFmt, HeaderTooBig };

// 串流 WAV 解析器。
// 用法：每收到一段位元組就呼叫 feed()；PCM 樣本經 onPcm(samples, count, ctx) 交出。
// onPcm 回傳 false 代表「要停」（例如使用者插話），feed() 會回傳 false。
class WavStreamParser {
 public:
  typedef bool (*PcmCallback)(const int16_t* samples, size_t count, void* ctx);

  static constexpr uint32_t kMinRate = 8000;
  static constexpr uint32_t kMaxRate = 48000;
  static constexpr size_t kMaxSkipChunk = 1u << 20;  // 其他 chunk 最多略過 1 MB，避免被灌爆

  void reset() {
    phase_ = Phase::RiffHeader; need_ = 12; have_ = 0; err_ = WavError::None;
    rate_ = 0; gotFmt_ = false; skipLeft_ = 0; dataLeft_ = 0;
    dataUnbounded_ = false; carry_ = false; pcmBytes_ = 0; stopped_ = false;
  }
  WavStreamParser() { reset(); }

  // 回傳 false：格式錯誤（看 error()）或 onPcm 要求停止（看 stopped()）
  bool feed(const uint8_t* p, size_t n, PcmCallback onPcm, void* ctx) {
    while (n > 0) {
      if (err_ != WavError::None || stopped_) return false;
      switch (phase_) {
        case Phase::RiffHeader:
        case Phase::ChunkHeader:
        case Phase::FmtBody: {
          size_t k = need_ - have_;
          if (k > n) k = n;
          for (size_t i = 0; i < k; ++i) hdr_[have_ + i] = p[i];
          have_ += k; p += k; n -= k;
          if (have_ == need_) {
            if (!onHeaderComplete()) return false;
          }
          break;
        }
        case Phase::Skip: {
          size_t k = skipLeft_ < n ? skipLeft_ : n;
          skipLeft_ -= k; p += k; n -= k;
          if (skipLeft_ == 0) toChunkHeader();
          break;
        }
        case Phase::Data: {
          size_t k = n;
          if (!dataUnbounded_ && dataLeft_ < k) k = dataLeft_;
          if (!emitPcm(p, k, onPcm, ctx)) { stopped_ = true; return false; }
          p += k; n -= k;
          if (!dataUnbounded_) {
            dataLeft_ -= k;
            if (dataLeft_ == 0) phase_ = Phase::Done;
          }
          break;
        }
        case Phase::Done:
          return true;  // data 之後的東西（例如 LIST）直接忽略
      }
    }
    return err_ == WavError::None && !stopped_;
  }

  bool inData() const { return phase_ == Phase::Data || phase_ == Phase::Done; }
  bool done() const { return phase_ == Phase::Done; }
  bool stopped() const { return stopped_; }
  WavError error() const { return err_; }
  uint32_t sampleRate() const { return rate_; }
  uint32_t pcmBytes() const { return pcmBytes_; }

 private:
  enum class Phase : uint8_t { RiffHeader, ChunkHeader, FmtBody, Skip, Data, Done };

  bool fail(WavError e) { err_ = e; return false; }
  void toChunkHeader() { phase_ = Phase::ChunkHeader; need_ = 8; have_ = 0; }

  bool onHeaderComplete() {
    if (phase_ == Phase::RiffHeader) {
      if (!(hdr_[0] == 'R' && hdr_[1] == 'I' && hdr_[2] == 'F' && hdr_[3] == 'F')) return fail(WavError::NotRiff);
      if (!(hdr_[8] == 'W' && hdr_[9] == 'A' && hdr_[10] == 'V' && hdr_[11] == 'E')) return fail(WavError::NotWave);
      toChunkHeader();
      return true;
    }
    if (phase_ == Phase::ChunkHeader) {
      uint32_t size = get32le(hdr_ + 4);
      bool isFmt = hdr_[0] == 'f' && hdr_[1] == 'm' && hdr_[2] == 't' && hdr_[3] == ' ';
      bool isData = hdr_[0] == 'd' && hdr_[1] == 'a' && hdr_[2] == 't' && hdr_[3] == 'a';
      if (isFmt) {
        if (size < 16) return fail(WavError::BadFmt);
        if (size > sizeof(hdr_)) return fail(WavError::HeaderTooBig);
        phase_ = Phase::FmtBody; need_ = size + (size & 1u); have_ = 0;  // 奇數長度要補 1 B
        if (need_ > sizeof(hdr_)) return fail(WavError::HeaderTooBig);
        return true;
      }
      if (isData) {
        if (!gotFmt_) return fail(WavError::DataBeforeFmt);
        phase_ = Phase::Data;
        // 串流回應常把長度填 0 或 0xFFFFFFFF：當成「播到連線結束」
        dataUnbounded_ = (size == 0 || size == 0xFFFFFFFFu);
        dataLeft_ = size & ~1u;  // 只收完整樣本
        if (!dataUnbounded_ && dataLeft_ == 0) phase_ = Phase::Done;
        return true;
      }
      // 其他 chunk（LIST、fact…）略過
      uint64_t skip = static_cast<uint64_t>(size) + (size & 1u);
      if (skip > kMaxSkipChunk) return fail(WavError::HeaderTooBig);
      skipLeft_ = static_cast<size_t>(skip);
      if (skipLeft_ == 0) toChunkHeader(); else phase_ = Phase::Skip;
      return true;
    }
    // FmtBody
    uint16_t fmt = get16le(hdr_);
    uint16_t ch = get16le(hdr_ + 2);
    uint32_t rate = get32le(hdr_ + 4);
    uint16_t bits = get16le(hdr_ + 14);
    if (!(fmt == 1 && ch == 1 && bits == 16)) return fail(WavError::NotPcm16Mono);
    if (rate < kMinRate || rate > kMaxRate) return fail(WavError::BadRate);
    rate_ = rate; gotFmt_ = true;
    toChunkHeader();
    return true;
  }

  // 把位元組轉成樣本；奇數邊界留一個位元組到下次
  bool emitPcm(const uint8_t* p, size_t n, PcmCallback cb, void* ctx) {
    int16_t buf[64];
    size_t m = 0;
    size_t i = 0;
    if (carry_ && n > 0) {
      buf[m++] = static_cast<int16_t>(static_cast<uint16_t>(carryByte_ | (p[0] << 8)));
      carry_ = false; i = 1; pcmBytes_ += 2;
    }
    for (; i + 1 < n; i += 2) {
      buf[m++] = static_cast<int16_t>(static_cast<uint16_t>(p[i] | (p[i + 1] << 8)));
      pcmBytes_ += 2;
      if (m == 64) {
        if (!cb(buf, m, ctx)) return false;
        m = 0;
      }
    }
    if (i < n) { carry_ = true; carryByte_ = p[i]; }
    if (m > 0 && !cb(buf, m, ctx)) return false;
    return true;
  }

  Phase phase_ = Phase::RiffHeader;
  uint8_t hdr_[40] = {0};  // fmt 最多 40 B（WAVE_FORMAT_EXTENSIBLE）
  size_t need_ = 12;
  size_t have_ = 0;
  WavError err_ = WavError::None;
  uint32_t rate_ = 0;
  bool gotFmt_ = false;
  size_t skipLeft_ = 0;
  uint32_t dataLeft_ = 0;
  bool dataUnbounded_ = false;
  bool carry_ = false;
  uint8_t carryByte_ = 0;
  uint32_t pcmBytes_ = 0;
  bool stopped_ = false;
};

}  // namespace askcore
