// proto.h — 協議 v1（docs/SERVER_API.md）的裝置端小工具（純邏輯，主機端可測）
// SPDX-License-Identifier: MIT
#pragma once
#include <stddef.h>
#include <stdint.h>
#include <string.h>

namespace askcore {

// ---------- 錯誤分類 ----------
enum class AskError : uint8_t {
  None,
  NoConfig,      // 沒填伺服器網址
  NoWifi,        // 沒有網路
  Connect,       // 連不上（DNS、TCP、TLS）
  Timeout,       // 逾時
  BadAudio,      // 400 bad_audio／415
  TooShort,      // 400 too_short
  Unauthorized,  // 401
  NotFound,      // 404（多半是網址設錯）
  TooLong,       // 413
  NoSpeech,      // 422
  RateLimited,   // 429
  Server,        // 5xx
  BadResponse,   // 200 但不是可播的 WAV
};

// 用 HTTP 狀態碼（與選用的錯誤 code 字串）判斷錯誤種類。
// status <= 0 代表 HTTPClient 的連線層錯誤（還沒拿到狀態碼）。
// Arduino HTTPClient 的負數錯誤碼：-11 = HTTPC_ERROR_READ_TIMEOUT（送出了，但等不到回應）
constexpr int kHttpcReadTimeout = -11;

inline AskError errorFromHttp(int status, const char* code = nullptr) {
  if (status == 200) return AskError::None;
  if (status == kHttpcReadTimeout) return AskError::Timeout;
  if (status <= 0) return AskError::Connect;
  switch (status) {
    case 400:
      if (code && strcmp(code, "too_short") == 0) return AskError::TooShort;
      return AskError::BadAudio;
    case 401: case 403: return AskError::Unauthorized;
    case 404: return AskError::NotFound;
    case 408: return AskError::Timeout;
    case 413: return AskError::TooLong;
    case 415: return AskError::BadAudio;
    case 422: return AskError::NoSpeech;
    case 429: return AskError::RateLimited;
    default: break;
  }
  if (status >= 500) return (status == 504) ? AskError::Timeout : AskError::Server;
  return AskError::BadResponse;
}

// 重試規則：只有「連線層失敗、還沒拿到任何 HTTP 狀態碼」才重送，最多 maxRetries 次。
// - 等回應逾時（-11）不重送：伺服器可能已經在處理，再等一輪會讓小孩乾等 40 秒。
// - 拿到任何狀態碼（含 5xx）都不重送：伺服器已經處理過，重送只會重複計費／重複紀錄。
inline bool shouldRetry(int status, int attempt, int maxRetries) {
  return status < 0 && status != kHttpcReadTimeout && attempt < maxRetries;
}

// OLED 錯誤畫面用的 ASCII 短字（中文字樣由 display 用點陣圖另外畫）
inline const char* errorShort(AskError e) {
  switch (e) {
    case AskError::None: return "OK";
    case AskError::NoConfig: return "NO CONFIG";
    case AskError::NoWifi: return "NO WIFI";
    case AskError::Connect: return "CONNECT";
    case AskError::Timeout: return "TIMEOUT";
    case AskError::BadAudio: return "AUDIO FMT";
    case AskError::TooShort: return "TOO SHORT";
    case AskError::Unauthorized: return "AUTH";
    case AskError::NotFound: return "URL?";
    case AskError::TooLong: return "TOO LONG";
    case AskError::NoSpeech: return "NO SPEECH";
    case AskError::RateLimited: return "REST";
    case AskError::Server: return "SERVER";
    case AskError::BadResponse: return "BAD REPLY";
  }
  return "?";
}

// ---------- 網址 ----------
inline bool startsWith(const char* s, const char* prefix) {
  return s && strncmp(s, prefix, strlen(prefix)) == 0;
}
inline bool isHttpsUrl(const char* url) { return startsWith(url, "https://"); }
inline bool isHttpUrl(const char* url) { return startsWith(url, "http://"); }

// base（例如 https://ai.example.com/ask-api/）＋ path（例如 /v1/ask）→ out
// base 空字串、不是 http(s)、或含空白／控制字元時回 false。
inline bool joinUrl(const char* base, const char* path, char* out, size_t cap) {
  if (!base || !path || !out || cap == 0) return false;
  out[0] = '\0';
  if (!(isHttpsUrl(base) || isHttpUrl(base))) return false;
  size_t bl = strlen(base);
  for (size_t i = 0; i < bl; ++i) {
    unsigned char c = static_cast<unsigned char>(base[i]);
    if (c <= 0x20 || c == 0x7F) return false;
  }
  size_t schemeLen = isHttpsUrl(base) ? 8 : 7;
  while (bl > schemeLen && base[bl - 1] == '/') --bl;
  if (bl <= schemeLen) return false;  // 只有 "https://"
  while (*path == '/') ++path;
  size_t pl = strlen(path);
  if (bl + 1 + pl + 1 > cap) return false;
  memcpy(out, base, bl);
  out[bl] = '/';
  memcpy(out + bl + 1, path, pl);
  out[bl + 1 + pl] = '\0';
  return true;
}

// ---------- X-Answer-Text：百分比編碼解碼 ----------
inline int hexVal(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  return -1;
}

// 解碼到 out（一定以 '\0' 結尾）；回傳解碼後長度。格式錯誤的 % 原樣保留。
inline size_t percentDecode(const char* in, char* out, size_t cap) {
  if (!out || cap == 0) return 0;
  size_t o = 0;
  for (size_t i = 0; in && in[i] && o + 1 < cap; ++i) {
    if (in[i] == '%' && in[i + 1] && in[i + 2]) {
      int h = hexVal(in[i + 1]), l = hexVal(in[i + 2]);
      if (h >= 0 && l >= 0) {
        out[o++] = static_cast<char>((h << 4) | l);
        i += 2;
        continue;
      }
    }
    out[o++] = in[i];
  }
  out[o] = '\0';
  return o;
}

inline bool isPrintableAscii(const char* s) {
  if (!s || !*s) return false;
  for (; *s; ++s) {
    unsigned char c = static_cast<unsigned char>(*s);
    if (c < 0x20 || c > 0x7E) return false;
  }
  return true;
}

// ---------- X-Display-Bitmap：base64 解碼 ----------
inline int b64Val(char c) {
  if (c >= 'A' && c <= 'Z') return c - 'A';
  if (c >= 'a' && c <= 'z') return c - 'a' + 26;
  if (c >= '0' && c <= '9') return c - '0' + 52;
  if (c == '+') return 62;
  if (c == '/') return 63;
  return -1;
}

// 標準 base64（含 = 補位）。任何非法字元或長度不對都回 0。
inline size_t base64Decode(const char* in, uint8_t* out, size_t cap) {
  if (!in || !out) return 0;
  size_t len = strlen(in);
  if (len == 0 || len % 4 != 0) return 0;
  size_t pad = 0;
  if (in[len - 1] == '=') ++pad;
  if (in[len - 2] == '=') ++pad;
  size_t outLen = len / 4 * 3 - pad;
  if (outLen > cap) return 0;
  size_t o = 0;
  for (size_t i = 0; i < len; i += 4) {
    int v[4];
    for (int j = 0; j < 4; ++j) {
      char c = in[i + j];
      if (c == '=') {
        if (i + 4 != len || j < 2) return 0;      // = 只能出現在最後一組的後兩格
        if (j == 2 && in[i + 3] != '=') return 0;  // "x=y" 不合法
        v[j] = 0;
      } else {
        v[j] = b64Val(c);
        if (v[j] < 0) return 0;
      }
    }
    uint32_t t = (static_cast<uint32_t>(v[0]) << 18) | (static_cast<uint32_t>(v[1]) << 12) |
                 (static_cast<uint32_t>(v[2]) << 6) | static_cast<uint32_t>(v[3]);
    if (o < outLen) out[o++] = static_cast<uint8_t>(t >> 16);
    if (o < outLen) out[o++] = static_cast<uint8_t>(t >> 8);
    if (o < outLen) out[o++] = static_cast<uint8_t>(t);
  }
  return o;
}

constexpr int kBitmapW = 128;
constexpr int kBitmapH = 32;
constexpr size_t kBitmapBytes = kBitmapW / 8 * kBitmapH;  // 512

// 1 bpp、逐列、MSB 在左：(x,y) 是否亮
inline bool bitmapPixel(const uint8_t* bm, int x, int y) {
  if (x < 0 || y < 0 || x >= kBitmapW || y >= kBitmapH) return false;
  return (bm[y * (kBitmapW / 8) + x / 8] >> (7 - (x & 7))) & 1u;
}

// ---------- 裝置 ID（亂數，不是 MAC） ----------
inline void deviceIdHex(uint64_t v, char out[17]) {
  static const char* hex = "0123456789abcdef";
  for (int i = 15; i >= 0; --i) { out[i] = hex[v & 0xF]; v >>= 4; }
  out[16] = '\0';
}

}  // namespace askcore
