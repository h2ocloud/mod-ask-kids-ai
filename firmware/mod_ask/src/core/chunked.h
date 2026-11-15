// chunked.h — HTTP/1.1 chunked 傳輸解碼（純邏輯，主機端可測）
// SPDX-License-Identifier: MIT
//
// 為什麼自己解：Arduino HTTPClient 的 writeToStream() 在伺服器「卡住但不斷線」時會一直等，
// 沒有資料間隔逾時；問答機要能在 5 秒沒資料時停播，所以自己讀 socket、自己解 chunked。
#pragma once
#include <stddef.h>
#include <stdint.h>

namespace askcore {

class ChunkedDecoder {
 public:
  typedef bool (*DataCallback)(const uint8_t* p, size_t n, void* ctx);

  void reset() { st_ = St::Size; size_ = 0; left_ = 0; digits_ = 0; err_ = false; lineLen_ = 0; }
  ChunkedDecoder() { reset(); }

  // 回傳 false：格式錯誤（error()）或回呼要求停止
  bool feed(const uint8_t* p, size_t n, DataCallback cb, void* ctx) {
    for (size_t i = 0; i < n;) {
      if (err_) return false;
      uint8_t c = p[i];
      switch (st_) {
        case St::Size: {
          int v = hex(c);
          if (v >= 0) {
            if (digits_ >= 8) return fail();  // 超過 4 GB 的 chunk 不合理
            size_ = (size_ << 4) | static_cast<uint32_t>(v);
            ++digits_;
          } else if (c == ';' || c == ' ' || c == '\t') {
            if (digits_ == 0) return fail();
            st_ = St::Ext;
          } else if (c == '\r') {
            if (digits_ == 0) return fail();
            st_ = St::SizeLF;
          } else {
            return fail();
          }
          ++i;
          break;
        }
        case St::Ext:  // chunk extension：略過到 CR
          if (c == '\r') st_ = St::SizeLF;
          ++i;
          break;
        case St::SizeLF:
          if (c != '\n') return fail();
          ++i;
          if (size_ == 0) { st_ = St::Trailer; lineLen_ = 0; }
          else { left_ = size_; st_ = St::Data; }
          break;
        case St::Data: {
          size_t k = n - i;
          if (k > left_) k = left_;
          if (!cb(p + i, k, ctx)) return false;
          i += k; left_ -= static_cast<uint32_t>(k);
          if (left_ == 0) st_ = St::DataCR;
          break;
        }
        case St::DataCR:
          if (c != '\r') return fail();
          st_ = St::DataLF; ++i;
          break;
        case St::DataLF:
          if (c != '\n') return fail();
          st_ = St::Size; size_ = 0; digits_ = 0; ++i;
          break;
        case St::Trailer:  // 0 長度 chunk 之後：可能有 trailer 行，空行代表結束
          if (c == '\r') { st_ = St::TrailerLF; }
          else { ++lineLen_; }
          ++i;
          break;
        case St::TrailerLF:
          if (c != '\n') return fail();
          ++i;
          if (lineLen_ == 0) st_ = St::Done; else { lineLen_ = 0; st_ = St::Trailer; }
          break;
        case St::Done:
          return true;  // 後面的位元組不屬於這個回應，忽略
      }
    }
    return !err_;
  }

  bool done() const { return st_ == St::Done; }
  bool error() const { return err_; }

 private:
  enum class St : uint8_t { Size, Ext, SizeLF, Data, DataCR, DataLF, Trailer, TrailerLF, Done };
  static int hex(uint8_t c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
  }
  bool fail() { err_ = true; return false; }

  St st_ = St::Size;
  uint32_t size_ = 0;
  uint32_t left_ = 0;
  uint8_t digits_ = 0;
  bool err_ = false;
  uint32_t lineLen_ = 0;
};

// 從錯誤 JSON（{"error":{"code":"too_long",...}}）取出 code，不需要 JSON 函式庫。
// 找第一個 "code" 鍵後面的字串值；取不到回 false。
inline bool extractErrorCode(const char* json, char* out, size_t cap) {
  if (!json || !out || cap == 0) return false;
  out[0] = '\0';
  const char* k = json;
  for (; *k; ++k) {
    if (k[0] == '"' && k[1] == 'c' && k[2] == 'o' && k[3] == 'd' && k[4] == 'e' && k[5] == '"') break;
  }
  if (!*k) return false;
  const char* p = k + 6;
  while (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n') ++p;
  if (*p != ':') return false;
  ++p;
  while (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n') ++p;
  if (*p != '"') return false;
  ++p;
  size_t o = 0;
  while (*p && *p != '"') {
    char c = *p++;
    bool ok = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_' || c == '-';
    if (!ok) return false;  // code 只允許簡單識別字
    if (o + 1 >= cap) return false;
    out[o++] = c;
  }
  if (*p != '"' || o == 0) { out[0] = '\0'; return false; }
  out[o] = '\0';
  return true;
}

}  // namespace askcore
