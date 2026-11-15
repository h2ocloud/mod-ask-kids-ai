// net_ask.cpp — Wi-Fi 多組設定＋協議 v1 HTTP 客戶端
// SPDX-License-Identifier: MIT
#include "net_ask.h"

#include <Arduino.h>
#include <HTTPClient.h>
#include <NetworkClientSecure.h>
#include <Preferences.h>
#include <WiFi.h>
#include <WiFiMulti.h>
#include <esp_random.h>
#include <string.h>

#include "config.h"
#include "src/core/chunked.h"
#include "src/core/wav.h"

static_assert(HTTPC_ERROR_READ_TIMEOUT == askcore::kHttpcReadTimeout, "HTTPClient 錯誤碼變了，請更新 proto.h");

// 有 secrets.h 就用；沒有就用範本（全空 → 尚未設定），讓沒有帳密也能編譯
#if __has_include("secrets.h")
#include "secrets.h"
#define MOD_ASK_HAS_SECRETS 1
#else
#include "secrets.example.h"
#define MOD_ASK_HAS_SECRETS 0
#endif

using askcore::AskError;

namespace {

WiFiMulti wifiMulti;
char deviceId[17] = "0000000000000000";
uint32_t lastWifiTry = 0;

uint8_t lastBitmap[askcore::kBitmapBytes];
bool lastBitmapValid = false;
char lastText[201] = {0};

const char* kCollect[] = {"Content-Type", "Transfer-Encoding", "X-Answer-Text", "X-Display-Bitmap", "X-Request-Id"};

const char* const kSsids[] = {WIFI_SSID_1, WIFI_SSID_2, WIFI_SSID_3};
const char* const kPasses[] = {WIFI_PASS_1, WIFI_PASS_2, WIFI_PASS_3};

bool hasAnySsid() {
  for (const char* s : kSsids)
    if (s && s[0]) return true;
  return false;
}

// 依網址決定 http 或 https 客戶端。https 預設用內建根憑證清單驗證。
NetworkClient* makeClient(const char* url, NetworkClientSecure& tls, NetworkClient& plain) {
  if (askcore::isHttpsUrl(url)) {
#if ASK_TLS_INSECURE
    tls.setInsecure();  // 只限區網測試
#else
    if (strlen(ASK_SERVER_ROOT_CA) > 0) tls.setCACert(ASK_SERVER_ROOT_CA);
    else tls.useBuiltinCACertBundle();
#endif
    return &tls;
  }
  return &plain;
}

void addCommonHeaders(HTTPClient& http) {
  if (strlen(ASK_DEVICE_TOKEN) > 0) http.addHeader("Authorization", String("Bearer ") + ASK_DEVICE_TOKEN);
  http.addHeader("X-Device-Id", deviceId);
  http.addHeader("X-Fw-Version", MOD_ASK_FW_VERSION);
}

void loadDeviceId() {
  Preferences p;
  if (!p.begin("modask", false)) return;
  uint64_t id = p.getULong64("did", 0);
  if (id == 0) {
    // Wi-Fi 已啟動，esp_random() 是硬體真亂數
    id = (static_cast<uint64_t>(esp_random()) << 32) | esp_random();
    if (id == 0) id = 1;
    p.putULong64("did", id);
  }
  p.end();
  askcore::deviceIdHex(id, deviceId);
}

struct StreamCtx {
  askcore::WavStreamParser wav;
  const AskHooks* hooks;
  bool started;
};

bool onPcmThunk(const int16_t* s, size_t n, void* vctx) {
  StreamCtx* c = static_cast<StreamCtx*>(vctx);
  // WavStreamParser 給的是 const；播放前要就地套用音量，複製到小緩衝
  int16_t tmp[64];
  while (n > 0) {
    size_t k = n < 64 ? n : 64;
    memcpy(tmp, s, k * sizeof(int16_t));
    if (!c->hooks->onPcm(tmp, k, c->wav.sampleRate(), c->hooks->ctx)) return false;
    s += k;
    n -= k;
  }
  return true;
}

bool onBodyThunk(const uint8_t* p, size_t n, void* vctx) {
  StreamCtx* c = static_cast<StreamCtx*>(vctx);
  return c->wav.feed(p, n, onPcmThunk, c);
}

}  // namespace

bool netHasSecretsFile() { return MOD_ASK_HAS_SECRETS == 1; }

bool netConfigured() {
  char probe[256];
  return hasAnySsid() && askcore::joinUrl(ASK_SERVER_URL, "/v1/ask", probe, sizeof probe);
}

void netBegin() {
  WiFi.persistent(false);  // 帳密不寫進 NVS
  WiFi.mode(WIFI_STA);
  WiFi.setHostname("mod-ask");
  WiFi.setSleep(false);    // 串流播放時避免省電模式造成斷續
  WiFi.setAutoReconnect(true);
  for (size_t i = 0; i < 3; ++i)
    if (kSsids[i] && kSsids[i][0]) wifiMulti.addAP(kSsids[i], kPasses[i]);
  loadDeviceId();
  if (askcore::isHttpUrl(ASK_SERVER_URL))
    Serial.println("[NET] WARNING: server URL is plain http (not encrypted). Use https for real use.");
#if ASK_TLS_INSECURE
  Serial.println("[NET] WARNING: ASK_TLS_INSECURE=1, TLS certificate is NOT verified.");
#endif
}

bool netConnect(uint32_t timeoutMs) {
  lastWifiTry = millis();
  uint32_t t0 = millis();
  while (millis() - t0 < timeoutMs) {
    if (wifiMulti.run(5000) == WL_CONNECTED) return true;
    delay(200);
  }
  return WiFi.status() == WL_CONNECTED;
}

bool netConnected() { return WiFi.status() == WL_CONNECTED; }

void netMaintain(uint32_t now) {
  if (netConnected()) return;
  if (now - lastWifiTry < WIFI_RETRY_INTERVAL_MS) return;
  lastWifiTry = now;
  wifiMulti.run(5000);
}

const char* netDeviceId() { return deviceId; }

AskError netHealth() {
  char url[256];
  if (!askcore::joinUrl(ASK_SERVER_URL, "/v1/health", url, sizeof url)) return AskError::NoConfig;
  if (!netConnected()) return AskError::NoWifi;
  NetworkClientSecure tls;
  NetworkClient plain;
  HTTPClient http;
  http.setConnectTimeout(ASK_CONNECT_TIMEOUT_MS);
  http.setTimeout(HEALTH_TIMEOUT_MS);
  if (!http.begin(*makeClient(url, tls, plain), url)) return AskError::Connect;
  addCommonHeaders(http);
  int code = http.GET();
  AskError e = askcore::errorFromHttp(code);
  if (code == 200) {
    String body = http.getString();
    if (body.indexOf("\"mod-ask/1") < 0) e = AskError::BadResponse;  // 協議版本不符
  }
  http.end();
  Serial.printf("[NET] health -> %d (%s)\n", code, askcore::errorShort(e));
  return e;
}

AskOutcome netAsk(const uint8_t* wav, size_t wavLen, const AskHooks& hooks) {
  AskOutcome out;
  lastBitmapValid = false;
  lastText[0] = '\0';
  char url[256];
  if (!askcore::joinUrl(ASK_SERVER_URL, "/v1/ask", url, sizeof url)) { out.err = AskError::NoConfig; return out; }
  if (!netConnected()) { out.err = AskError::NoWifi; return out; }

  uint32_t t0 = millis();
  for (int attempt = 0;; ++attempt) {
    NetworkClientSecure tls;
    NetworkClient plain;
    HTTPClient http;
    http.setConnectTimeout(ASK_CONNECT_TIMEOUT_MS);
    http.setTimeout(ASK_RESPONSE_TIMEOUT_MS);
    http.setReuse(false);
    if (!http.begin(*makeClient(url, tls, plain), url)) { out.err = AskError::Connect; return out; }
    http.collectHeaders(kCollect, sizeof(kCollect) / sizeof(kCollect[0]));
    addCommonHeaders(http);
    http.addHeader("Content-Type", "audio/wav");
    http.addHeader("Accept", "audio/wav");

    int code = http.POST(const_cast<uint8_t*>(wav), wavLen);
    out.httpStatus = code;
    out.msToFirstByte = millis() - t0;
    Serial.printf("[NET] POST /v1/ask %u B -> %d (%u ms)\n", static_cast<unsigned>(wavLen), code,
                  static_cast<unsigned>(out.msToFirstByte));

    if (code != 200) {
      if (askcore::shouldRetry(code, attempt, ASK_MAX_RETRIES)) {
        http.end();
        Serial.println("[NET] no response yet, retrying once");
        continue;
      }
      char ecode[32] = {0};
      if (code > 0) {
        String body = http.getString();
        askcore::extractErrorCode(body.c_str(), ecode, sizeof ecode);
      }
      out.err = askcore::errorFromHttp(code, ecode);
      Serial.printf("[NET] error code=%s -> %s\n", ecode[0] ? ecode : "-", askcore::errorShort(out.err));
      http.end();
      out.msTotal = millis() - t0;
      return out;
    }

    // 200：檢查型別、取出顯示資料
    String ctype = http.header("Content-Type");
    if (ctype.indexOf("audio/wav") < 0 && ctype.indexOf("audio/x-wav") < 0 && ctype.indexOf("audio/wave") < 0) {
      out.err = AskError::BadResponse;
      http.end();
      return out;
    }
    String text = http.header("X-Answer-Text");
    if (text.length()) {
      askcore::percentDecode(text.c_str(), lastText, sizeof lastText);
      Serial.printf("[ASK] answer: %s\n", lastText);
    }
    String bm = http.header("X-Display-Bitmap");
    if (bm.length()) {
      lastBitmapValid = askcore::base64Decode(bm.c_str(), lastBitmap, sizeof lastBitmap) == askcore::kBitmapBytes;
    }
    String rid = http.header("X-Request-Id");
    if (rid.length()) Serial.printf("[ASK] request id: %s\n", rid.c_str());

    bool chunked = http.header("Transfer-Encoding").indexOf("chunked") >= 0;
    int contentLen = http.getSize();  // -1 = 未知
    NetworkClient* s = http.getStreamPtr();

    StreamCtx ctx{askcore::WavStreamParser(), &hooks, false};
    askcore::ChunkedDecoder dechunk;
    hooks.onResponseStart(hooks.ctx);
    out.started = true;

    uint8_t buf[1024];
    uint32_t lastData = millis();
    int left = contentLen;
    bool ok = true;
    for (;;) {
      if (!hooks.poll(hooks.ctx)) { out.stopped = true; break; }
      int avail = s ? s->available() : 0;
      if (avail > 0) {
        int want = avail < static_cast<int>(sizeof buf) ? avail : static_cast<int>(sizeof buf);
        if (!chunked && left >= 0 && want > left) want = left;
        int n = s->read(buf, want);
        if (n <= 0) {
          if (millis() - lastData > ASK_STREAM_IDLE_TIMEOUT_MS) { out.err = AskError::Timeout; break; }
          delay(1);
          continue;
        }
        lastData = millis();
        bool fed = chunked ? dechunk.feed(buf, n, onBodyThunk, &ctx) : onBodyThunk(buf, n, &ctx);
        if (!fed) {
          if (ctx.wav.stopped()) { out.stopped = true; }
          else { ok = false; }
          break;
        }
        if (!chunked && left >= 0) { left -= n; if (left <= 0) break; }
        if (chunked && dechunk.done()) break;
        if (ctx.wav.done()) break;
      } else {
        if (!s || !s->connected()) break;
        if (millis() - lastData > ASK_STREAM_IDLE_TIMEOUT_MS) { out.err = AskError::Timeout; break; }
        delay(1);
      }
    }
    out.pcmBytes = ctx.wav.pcmBytes();
    if (!ok && out.err == AskError::None) out.err = AskError::BadResponse;
    if (out.err == AskError::None && !out.stopped && out.pcmBytes == 0) out.err = AskError::BadResponse;
    http.end();
    out.msTotal = millis() - t0;
    Serial.printf("[NET] played %u B, total %u ms, err=%s%s\n", static_cast<unsigned>(out.pcmBytes),
                  static_cast<unsigned>(out.msTotal), askcore::errorShort(out.err), out.stopped ? " (stopped)" : "");
    return out;
  }
}

const uint8_t* netLastBitmap() { return lastBitmapValid ? lastBitmap : nullptr; }
const char* netLastAnswerText() { return lastText[0] ? lastText : nullptr; }
