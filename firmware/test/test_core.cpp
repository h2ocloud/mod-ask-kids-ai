// test_core.cpp — 韌體純邏輯（src/core/*.h）的主機端單元測試
// SPDX-License-Identifier: MIT
// 編譯：見 run_tests.sh（clang++ -std=c++17 -Wall -Wextra -Wpedantic -Werror -fsanitize=address,undefined）
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

#include "../mod_ask/src/core/ask_state.h"
#include "../mod_ask/src/core/audio_dsp.h"
#include "../mod_ask/src/core/button.h"
#include "../mod_ask/src/core/chunked.h"
#include "../mod_ask/src/core/pins_guard.h"
#include "../mod_ask/src/core/proto.h"
#include "../mod_ask/src/core/wav.h"

using namespace askcore;

static int g_fail = 0;
static int g_checks = 0;
#define CHECK(cond)                                                       \
  do {                                                                    \
    ++g_checks;                                                           \
    if (!(cond)) {                                                        \
      ++g_fail;                                                           \
      std::printf("  FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);       \
    }                                                                     \
  } while (0)

struct TestCase { const char* name; void (*fn)(); };

// ---------------- 狀態機 ----------------
static void test_state_happy_path() {
  State s = State::ConnectingWifi;
  s = next(s, Event::WifiUp, true);          CHECK(s == State::Idle);
  s = next(s, Event::ButtonDown, true);      CHECK(s == State::Listening);
  s = next(s, Event::ButtonUp, true);        CHECK(s == State::Thinking);
  s = next(s, Event::ResponseStart, true);   CHECK(s == State::Speaking);
  s = next(s, Event::PlayDone, true);        CHECK(s == State::Idle);
}

static void test_state_edges() {
  // 沒設定：任何事件都留在 NoConfig
  for (int e = 0; e <= static_cast<int>(Event::ErrorTimeout); ++e)
    CHECK(next(State::NoConfig, static_cast<Event>(e), true) == State::NoConfig);
  // 思考中再按：忽略
  CHECK(next(State::Thinking, Event::ButtonDown, true) == State::Thinking);
  // 錄到上限也送出
  CHECK(next(State::Listening, Event::RecordLimit, true) == State::Thinking);
  // 誤觸太短：回待機；斷線時回離線
  CHECK(next(State::Listening, Event::RecordTooShort, true) == State::Idle);
  CHECK(next(State::Listening, Event::RecordTooShort, false) == State::Offline);
  // 插話
  CHECK(next(State::Speaking, Event::ButtonDown, true) == State::Listening);
  CHECK(next(State::Speaking, Event::ButtonDown, false) == State::Offline);
  // 失敗 → 錯誤 → 時間到回待機或離線
  CHECK(next(State::Thinking, Event::RequestFailed, true) == State::Error);
  CHECK(next(State::Error, Event::ErrorTimeout, true) == State::Idle);
  CHECK(next(State::Error, Event::ErrorTimeout, false) == State::Offline);
  CHECK(next(State::Error, Event::ButtonDown, true) == State::Listening);
  // 待機中背景請求（health）失敗
  CHECK(next(State::Idle, Event::RequestFailed, true) == State::Error);
  // 待機斷線、離線恢復
  CHECK(next(State::Idle, Event::WifiDown, false) == State::Offline);
  CHECK(next(State::Offline, Event::WifiUp, true) == State::Idle);
  CHECK(next(State::Offline, Event::ButtonDown, false) == State::Offline);
  // 待機按下但其實已斷線（WifiDown 事件還沒到）
  CHECK(next(State::Idle, Event::ButtonDown, false) == State::Offline);
  // 名稱表完整
  for (int i = 0; i <= static_cast<int>(State::Error); ++i) CHECK(std::strcmp(stateName(static_cast<State>(i)), "?") != 0);
  for (int i = 0; i <= static_cast<int>(Event::ErrorTimeout); ++i) CHECK(std::strcmp(eventName(static_cast<Event>(i)), "?") != 0);
}

// ---------------- 按鈕去彈跳 ----------------
static void test_debounce() {
  Debouncer d(30);
  CHECK(d.update(true, 0) == Edge::None);
  CHECK(d.update(false, 5) == Edge::None);   // 彈跳
  CHECK(d.update(true, 10) == Edge::None);
  CHECK(d.update(true, 39) == Edge::None);   // 還沒穩定 30 ms
  CHECK(d.update(true, 40) == Edge::Down);
  CHECK(d.pressed());
  CHECK(d.heldMs(1040) == 1000);
  CHECK(d.update(true, 60) == Edge::None);   // 只報一次
  CHECK(d.update(false, 100) == Edge::None);
  CHECK(d.update(false, 129) == Edge::None);
  CHECK(d.update(false, 130) == Edge::Up);
  CHECK(!d.pressed());
  CHECK(d.heldMs(200) == 0);
  // millis() 回繞
  Debouncer w(30);
  w.update(true, 0xFFFFFFF0u);
  CHECK(w.update(true, 0x0000000Eu) == Edge::Down);  // 經過 30 ms
}

// ---------------- 訊號處理 ----------------
static void test_dsp() {
  CHECK(mic32to16(0x7FFFFF00, 16) == 0x7FFF);
  CHECK(mic32to16(-0x10000, 16) == -1);
  CHECK(mic32to16(0x40000000, 14) == 32767);   // 放大後截斷
  CHECK(mic32to16(-0x40000000, 14) == -32768);
  CHECK(mic32to16(1 << 20, 14) == 64);
  // 直流阻隔：固定直流輸入會衰減到接近 0
  DcBlocker dc;
  int16_t y = 0;
  for (int i = 0; i < 16000; ++i) y = dc.step(1000);
  CHECK(y > -5 && y < 5);
  // 音量
  CHECK(volumeToQ15(100) == 32768);
  CHECK(volumeToQ15(0) == 0);
  CHECK(volumeToQ15(50) == 8192);
  CHECK(volumeToQ15(200) == 32768);  // 超過 100 當 100
  int16_t s[4] = {32767, -32768, 1000, -1000};
  applyGainQ15(s, 4, volumeToQ15(50));
  CHECK(s[0] == 8191 && s[1] == -8192 && s[2] == 250 && s[3] == -250);
  int16_t t[2] = {1234, -1234};
  applyGainQ15(t, 2, 32768);
  CHECK(t[0] == 1234 && t[1] == -1234);
  // 峰值與音量條
  int16_t pk[3] = {10, -32768, 5};
  CHECK(peakAbs(pk, 3) == 32767);
  CHECK(peakToBars(32767, 12) == 12);
  CHECK(peakToBars(0, 12) == 0);
  CHECK(peakToBars(1000, 12) > 0 && peakToBars(1000, 12) < 12);
  CHECK(peakToBars(20000, 12) >= peakToBars(5000, 12));
}

static void test_upsample() {
  CHECK(upsampleFactor(16000) == 1 && upsampleFactor(48000) == 1 && upsampleFactor(44100) == 1);
  CHECK(upsampleFactor(24000) == 2 && upsampleFactor(22050) == 2);
  CHECK(upsampleFactor(12000) == 4 && upsampleFactor(11025) == 4);
  CHECK(upsampleFactor(96000) == 0 && upsampleFactor(20000) == 0);
  CHECK(!ampNativeRate(24000) && !ampNativeRate(22050) && ampNativeRate(8000) && ampNativeRate(32000));
  Upsampler u;
  u.reset(2);
  int16_t in[4] = {0, 100, 100, -100};
  int16_t out[8];
  CHECK(u.process(in, 4, out) == 8);
  // 第一個樣本沒有前一點：重複自己；之後從上一點線性走到這一點
  const int16_t want[8] = {0, 0, 50, 100, 100, 100, 0, -100};
  bool same = true;
  for (int i = 0; i < 8; ++i) same = same && out[i] == want[i];
  CHECK(same);
  // 跨呼叫連續：下一段從 -100 開始內插
  int16_t in2[1] = {100};
  CHECK(u.process(in2, 1, out) == 2 && out[0] == 0 && out[1] == 100);
  // 4 倍、極值不溢位
  u.reset(4);
  int16_t ex[2] = {-32768, 32767};
  int16_t o4[8];
  CHECK(u.process(ex, 2, o4) == 8 && o4[3] == -32768 && o4[7] == 32767 && o4[5] == -1);  // -32768 + 65535*2/4
  u.reset(0);
  CHECK(u.factor() == 1);
}

static void test_record_buffer() {
  std::vector<int16_t> mem(10);
  RecordBuffer rb;
  CHECK(rb.push(nullptr, 0) == 0);
  rb.attach(mem.data(), mem.size());
  int16_t a[6] = {1, 2, 3, 4, 5, 6};
  CHECK(rb.push(a, 6) == 6);
  CHECK(!rb.full());
  CHECK(rb.push(a, 6) == 4);  // 只剩 4 格
  CHECK(rb.full());
  CHECK(rb.length() == 10);
  CHECK(mem[9] == 4);
  CHECK(rb.millis(16000) == 0);  // 10 樣本 < 1 ms
  rb.clear();
  CHECK(rb.length() == 0 && !rb.full());
  std::vector<int16_t> big(32000);
  rb.attach(big.data(), big.size());
  std::vector<int16_t> chunk(16000, 0);
  rb.push(chunk.data(), chunk.size());
  CHECK(rb.millis(16000) == 1000);
}

// ---------------- WAV ----------------
struct Collect {
  std::vector<int16_t> pcm;
  size_t stopAfter = static_cast<size_t>(-1);
};
static bool collectCb(const int16_t* s, size_t n, void* ctx) {
  Collect* c = static_cast<Collect*>(ctx);
  for (size_t i = 0; i < n; ++i) c->pcm.push_back(s[i]);
  return c->pcm.size() < c->stopAfter;
}

static std::vector<uint8_t> makeWav(uint32_t rate, const std::vector<int16_t>& pcm, bool withList, uint32_t dataField) {
  std::vector<uint8_t> v(44);
  wavHeaderPcm16Mono(v.data(), rate, static_cast<uint32_t>(pcm.size() * 2));
  if (withList) {
    // 在 fmt 與 data 之間插一個奇數長度的 LIST chunk（要補 1 B）
    std::vector<uint8_t> head(v.begin(), v.begin() + 36);
    const char list[] = {'L', 'I', 'S', 'T', 5, 0, 0, 0, 'a', 'b', 'c', 'd', 'e', 0};
    head.insert(head.end(), list, list + sizeof list);
    head.insert(head.end(), v.begin() + 36, v.end());
    v = head;
  }
  put32le(v.data() + v.size() - 4, dataField);
  for (int16_t s : pcm) { v.push_back(static_cast<uint8_t>(s & 0xFF)); v.push_back(static_cast<uint8_t>((s >> 8) & 0xFF)); }
  return v;
}

static void test_wav_header() {
  uint8_t h[44];
  wavHeaderPcm16Mono(h, 16000, 32000);
  CHECK(std::memcmp(h, "RIFF", 4) == 0);
  CHECK(get32le(h + 4) == 36 + 32000);
  CHECK(std::memcmp(h + 8, "WAVEfmt ", 8) == 0);
  CHECK(get16le(h + 20) == 1 && get16le(h + 22) == 1);
  CHECK(get32le(h + 24) == 16000 && get32le(h + 28) == 32000);
  CHECK(get16le(h + 32) == 2 && get16le(h + 34) == 16);
  CHECK(std::memcmp(h + 36, "data", 4) == 0 && get32le(h + 40) == 32000);
}

static void test_wav_stream_any_split() {
  std::vector<int16_t> pcm;
  for (int i = 0; i < 1001; ++i) pcm.push_back(static_cast<int16_t>(i * 37 - 18000));
  for (int variant = 0; variant < 3; ++variant) {
    uint32_t dataField = variant == 0 ? static_cast<uint32_t>(pcm.size() * 2) : (variant == 1 ? 0u : 0xFFFFFFFFu);
    std::vector<uint8_t> w = makeWav(24000, pcm, variant == 0, dataField);
    // 用 1..17 B 的各種切法餵進去，結果都要一樣
    for (size_t step = 1; step <= 17; ++step) {
      WavStreamParser p;
      Collect c;
      bool ok = true;
      for (size_t i = 0; i < w.size(); i += step) {
        size_t k = std::min(step, w.size() - i);
        ok = p.feed(w.data() + i, k, collectCb, &c) && ok;
      }
      CHECK(ok);
      CHECK(p.error() == WavError::None);
      CHECK(p.sampleRate() == 24000);
      CHECK(c.pcm == pcm);
      CHECK(p.pcmBytes() == pcm.size() * 2);
      if (variant == 0) CHECK(p.done()); else CHECK(!p.done() && p.inData());
    }
  }
}

static void test_wav_trailing_and_stop() {
  std::vector<int16_t> pcm(100, 7);
  std::vector<uint8_t> w = makeWav(16000, pcm, false, 200);
  const char tail[] = "LIST\x04\0\0\0junk";
  w.insert(w.end(), tail, tail + sizeof tail - 1);
  WavStreamParser p;
  Collect c;
  CHECK(p.feed(w.data(), w.size(), collectCb, &c));
  CHECK(c.pcm.size() == 100 && p.done());
  // 回呼要求停止
  WavStreamParser q;
  Collect d;
  d.stopAfter = 50;
  CHECK(!q.feed(w.data(), w.size(), collectCb, &d));
  CHECK(q.stopped() && q.error() == WavError::None);
  CHECK(!q.feed(w.data(), 1, collectCb, &d));  // 停了就不再吃
}

static void test_wav_errors() {
  std::vector<int16_t> pcm(10, 1);
  auto feedAll = [](std::vector<uint8_t> w) {
    WavStreamParser p;
    Collect c;
    p.feed(w.data(), w.size(), collectCb, &c);
    return p.error();
  };
  std::vector<uint8_t> w = makeWav(16000, pcm, false, 20);
  auto bad = w; bad[0] = 'X';              CHECK(feedAll(bad) == WavError::NotRiff);
  bad = w; bad[8] = 'X';                   CHECK(feedAll(bad) == WavError::NotWave);
  bad = w; put16le(bad.data() + 22, 2);    CHECK(feedAll(bad) == WavError::NotPcm16Mono);   // 立體聲
  bad = w; put16le(bad.data() + 34, 8);    CHECK(feedAll(bad) == WavError::NotPcm16Mono);   // 8 bit
  bad = w; put16le(bad.data() + 20, 3);    CHECK(feedAll(bad) == WavError::NotPcm16Mono);   // float
  bad = w; put32le(bad.data() + 24, 4000); CHECK(feedAll(bad) == WavError::BadRate);
  bad = w; put32le(bad.data() + 24, 96000); CHECK(feedAll(bad) == WavError::BadRate);
  bad = w; put32le(bad.data() + 16, 8);    CHECK(feedAll(bad) == WavError::BadFmt);
  bad = w; put32le(bad.data() + 16, 200);  CHECK(feedAll(bad) == WavError::HeaderTooBig);
  // fmt 長度是奇數（17）：後面要補 1 B 才是下一個 chunk
  {
    std::vector<uint8_t> o(w.begin(), w.begin() + 36);
    put32le(o.data() + 16, 17);
    o.push_back(0);  // fmt 第 17 個位元組
    o.push_back(0);  // 補位
    o.insert(o.end(), w.begin() + 36, w.end());
    WavStreamParser p;
    Collect c;
    CHECK(p.feed(o.data(), o.size(), collectCb, &c));
    CHECK(p.error() == WavError::None && c.pcm.size() == 10);
  }
  // data 在 fmt 之前
  std::vector<uint8_t> d = {'R', 'I', 'F', 'F', 0, 0, 0, 0, 'W', 'A', 'V', 'E', 'd', 'a', 't', 'a', 2, 0, 0, 0, 1, 0};
  CHECK(feedAll(d) == WavError::DataBeforeFmt);
  // 超大的其他 chunk
  std::vector<uint8_t> big(w.begin(), w.begin() + 36);
  const uint8_t junk[] = {'j', 'u', 'n', 'k', 0, 0, 0x20, 0};
  big.insert(big.end(), junk, junk + 8);
  CHECK(feedAll(big) == WavError::HeaderTooBig);
}

// ---------------- chunked ----------------
struct Bytes { std::string s; size_t stopAfter = static_cast<size_t>(-1); };
static bool bytesCb(const uint8_t* p, size_t n, void* ctx) {
  Bytes* b = static_cast<Bytes*>(ctx);
  b->s.append(reinterpret_cast<const char*>(p), n);
  return b->s.size() < b->stopAfter;
}

static void test_chunked() {
  const std::string body = "4\r\nWiki\r\n5;ext=1\r\npedia\r\nE\r\n in\r\n\r\nchunks.\r\n0\r\nX-Trailer: 1\r\n\r\nGARBAGE";
  for (size_t step = 1; step <= 9; ++step) {
    ChunkedDecoder d;
    Bytes b;
    bool ok = true;
    for (size_t i = 0; i < body.size(); i += step) {
      size_t k = std::min(step, body.size() - i);
      ok = d.feed(reinterpret_cast<const uint8_t*>(body.data()) + i, k, bytesCb, &b) && ok;
    }
    CHECK(ok);
    CHECK(d.done());
    CHECK(b.s == "Wikipedia in\r\n\r\nchunks.");
  }
  auto run = [](const std::string& s) {
    ChunkedDecoder d;
    Bytes b;
    bool ok = d.feed(reinterpret_cast<const uint8_t*>(s.data()), s.size(), bytesCb, &b);
    return std::make_pair(ok, d.error());
  };
  CHECK(run("zz\r\n").second);              // 非十六進位
  CHECK(run("\r\n").second);                // 沒有長度
  CHECK(run("3\r\nabcX\r\n").second);       // 少了 CRLF
  CHECK(run("123456789\r\n").second);       // 太長
  CHECK(run("3\rX").second);                // CR 後不是 LF
  CHECK(run("3\r\nabcX\n0\r\n\r\n").second); // 資料後的 CR 被換成別的字元
  // 回呼要求停止
  ChunkedDecoder d;
  Bytes b;
  b.stopAfter = 2;
  std::string s = "4\r\nWiki\r\n0\r\n\r\n";
  CHECK(!d.feed(reinterpret_cast<const uint8_t*>(s.data()), s.size(), bytesCb, &b));
  CHECK(!d.error());
}

static void test_chunked_wav_pipeline() {
  // chunked → WAV → PCM 串在一起（裝置實際的路徑）
  std::vector<int16_t> pcm;
  for (int i = 0; i < 777; ++i) pcm.push_back(static_cast<int16_t>((i * 97) % 30000 - 15000));
  std::vector<uint8_t> w = makeWav(16000, pcm, true, 0xFFFFFFFFu);
  std::string body;
  size_t pos = 0, sz = 1;
  while (pos < w.size()) {
    size_t k = std::min(sz, w.size() - pos);
    char hex[16];
    std::snprintf(hex, sizeof hex, "%zx\r\n", k);
    body += hex;
    body.append(reinterpret_cast<const char*>(w.data() + pos), k);
    body += "\r\n";
    pos += k;
    sz = sz * 3 + 1;  // 各種大小（含奇數）
  }
  body += "0\r\n\r\n";
  struct Ctx { WavStreamParser wav; Collect c; } ctx;
  auto onBody = [](const uint8_t* p, size_t n, void* v) -> bool {
    Ctx* c = static_cast<Ctx*>(v);
    return c->wav.feed(p, n, collectCb, &c->c);
  };
  ChunkedDecoder d;
  for (size_t i = 0; i < body.size(); i += 5)
    d.feed(reinterpret_cast<const uint8_t*>(body.data()) + i, std::min<size_t>(5, body.size() - i), onBody, &ctx);
  CHECK(d.done());
  CHECK(ctx.c.pcm == pcm);
}

static void test_error_code_json() {
  char c[32];
  CHECK(extractErrorCode("{\"error\":{\"code\":\"too_long\",\"message\":\"x\"}}", c, sizeof c) && std::strcmp(c, "too_long") == 0);
  CHECK(extractErrorCode("{ \"error\" : { \"code\" :  \"rate_limited\" } }", c, sizeof c) && std::strcmp(c, "rate_limited") == 0);
  CHECK(!extractErrorCode("{\"error\":{}}", c, sizeof c) && c[0] == '\0');
  CHECK(!extractErrorCode("{\"code\":5}", c, sizeof c));
  CHECK(!extractErrorCode("{\"code\":\"a b\"}", c, sizeof c));  // 不合法字元
  char tiny[4];
  CHECK(!extractErrorCode("{\"code\":\"toolong\"}", tiny, sizeof tiny));
  CHECK(!extractErrorCode(nullptr, c, sizeof c));
}

// ---------------- 協議小工具 ----------------
static void test_http_errors() {
  CHECK(errorFromHttp(200) == AskError::None);
  CHECK(errorFromHttp(-1) == AskError::Connect);
  CHECK(errorFromHttp(kHttpcReadTimeout) == AskError::Timeout);
  CHECK(errorFromHttp(400) == AskError::BadAudio);
  CHECK(errorFromHttp(400, "too_short") == AskError::TooShort);
  CHECK(errorFromHttp(400, "bad_audio") == AskError::BadAudio);
  CHECK(errorFromHttp(401) == AskError::Unauthorized);
  CHECK(errorFromHttp(404) == AskError::NotFound);
  CHECK(errorFromHttp(413) == AskError::TooLong);
  CHECK(errorFromHttp(415) == AskError::BadAudio);
  CHECK(errorFromHttp(422) == AskError::NoSpeech);
  CHECK(errorFromHttp(429) == AskError::RateLimited);
  CHECK(errorFromHttp(500) == AskError::Server);
  CHECK(errorFromHttp(502) == AskError::Server);
  CHECK(errorFromHttp(504) == AskError::Timeout);
  CHECK(errorFromHttp(302) == AskError::BadResponse);
  // 重試只在連線層失敗
  CHECK(shouldRetry(-1, 0, 1));
  CHECK(!shouldRetry(-1, 1, 1));
  CHECK(!shouldRetry(kHttpcReadTimeout, 0, 1));
  CHECK(!shouldRetry(500, 0, 1));
  CHECK(!shouldRetry(429, 0, 1));
  for (int i = 0; i <= static_cast<int>(AskError::BadResponse); ++i)
    CHECK(std::strcmp(errorShort(static_cast<AskError>(i)), "?") != 0);
}

static void test_join_url() {
  char out[64];
  CHECK(joinUrl("https://ai.example.com/ask-api", "/v1/ask", out, sizeof out) && std::strcmp(out, "https://ai.example.com/ask-api/v1/ask") == 0);
  CHECK(joinUrl("https://ai.example.com/ask-api///", "v1/health", out, sizeof out) && std::strcmp(out, "https://ai.example.com/ask-api/v1/health") == 0);
  CHECK(joinUrl("http://127.0.0.1:8787", "/v1/ask", out, sizeof out) && std::strcmp(out, "http://127.0.0.1:8787/v1/ask") == 0);
  CHECK(!joinUrl("", "/v1/ask", out, sizeof out) && out[0] == '\0');   // 預設空字串＝未設定
  CHECK(!joinUrl("ftp://x", "/v1/ask", out, sizeof out));
  CHECK(!joinUrl("https://", "/v1/ask", out, sizeof out));
  CHECK(!joinUrl("https:///", "/v1/ask", out, sizeof out));
  CHECK(!joinUrl("https://a b", "/v1/ask", out, sizeof out));
  CHECK(!joinUrl("https://ai.example.com/a-very-long-path-that-does-not-fit", "/v1/ask", out, 32));
  CHECK(isHttpsUrl("https://x") && !isHttpsUrl("http://x") && isHttpUrl("http://x"));
}

static void test_percent_and_ascii() {
  char out[64];
  CHECK(percentDecode("Hello%20World%21", out, sizeof out) == 12 && std::strcmp(out, "Hello World!") == 0);
  percentDecode("%E4%BD%A0%E5%A5%BD", out, sizeof out);
  CHECK(std::strcmp(out, "\xE4\xBD\xA0\xE5\xA5\xBD") == 0);  // 你好（UTF-8）
  CHECK(!isPrintableAscii(out));
  CHECK(percentDecode("100%", out, sizeof out) == 4 && std::strcmp(out, "100%") == 0);
  CHECK(percentDecode("%zz", out, sizeof out) == 3);
  char tiny[4];
  CHECK(percentDecode("abcdef", tiny, sizeof tiny) == 3 && std::strcmp(tiny, "abc") == 0);
  CHECK(isPrintableAscii("Hi there"));
  CHECK(!isPrintableAscii(""));
  CHECK(!isPrintableAscii("tab\t"));
}

static void test_base64_bitmap() {
  uint8_t out[16];
  CHECK(base64Decode("TWFu", out, sizeof out) == 3 && std::memcmp(out, "Man", 3) == 0);
  CHECK(base64Decode("TWE=", out, sizeof out) == 2 && std::memcmp(out, "Ma", 2) == 0);
  CHECK(base64Decode("TQ==", out, sizeof out) == 1 && out[0] == 'M');
  CHECK(base64Decode("TQ=", out, sizeof out) == 0);     // 長度不對
  CHECK(base64Decode("T=Q=", out, sizeof out) == 0);    // = 位置不對
  CHECK(base64Decode("TWF*", out, sizeof out) == 0);    // 非法字元
  CHECK(base64Decode("=AAA", out, sizeof out) == 0);
  CHECK(base64Decode("TWFuTWFu", out, 5) == 0);         // 放不下
  // 512 B 點陣：第 0 列最左點亮、第 31 列最右點亮
  std::vector<uint8_t> bm(kBitmapBytes, 0);
  bm[0] = 0x80;
  bm[kBitmapBytes - 1] = 0x01;
  static const char* tbl = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  std::string enc;
  for (size_t i = 0; i < bm.size(); i += 3) {
    uint32_t v = static_cast<uint32_t>(bm[i]) << 16;
    if (i + 1 < bm.size()) v |= static_cast<uint32_t>(bm[i + 1]) << 8;
    if (i + 2 < bm.size()) v |= bm[i + 2];
    enc += tbl[(v >> 18) & 63];
    enc += tbl[(v >> 12) & 63];
    enc += i + 1 < bm.size() ? tbl[(v >> 6) & 63] : '=';
    enc += i + 2 < bm.size() ? tbl[v & 63] : '=';
  }
  CHECK(enc.size() == 684);
  std::vector<uint8_t> dec(kBitmapBytes);
  CHECK(base64Decode(enc.c_str(), dec.data(), dec.size()) == kBitmapBytes);
  CHECK(bitmapPixel(dec.data(), 0, 0));
  CHECK(!bitmapPixel(dec.data(), 1, 0));
  CHECK(bitmapPixel(dec.data(), 127, 31));
  CHECK(!bitmapPixel(dec.data(), 126, 31));
  CHECK(!bitmapPixel(dec.data(), 128, 0) && !bitmapPixel(dec.data(), -1, 0));
}

static void test_device_id() {
  char id[17];
  deviceIdHex(0x0123456789abcdefULL, id);
  CHECK(std::strcmp(id, "0123456789abcdef") == 0);
  deviceIdHex(1, id);
  CHECK(std::strcmp(id, "0000000000000001") == 0 && std::strlen(id) == 16);
}

static void test_pins() {
  const int used[] = {4, 5, 6, 7, 15, 16, 41, 42, 47};
  for (int p : used) CHECK(!pinForbidden(p));
  const int bad[] = {0, 3, 19, 20, 26, 32, 33, 35, 36, 37, 38, 43, 44, 45, 46, 48, 22, 49, -1};
  for (int p : bad) CHECK(pinForbidden(p));
}

int main() {
  const TestCase tests[] = {
      {"state_happy_path", test_state_happy_path},
      {"state_edges", test_state_edges},
      {"debounce", test_debounce},
      {"dsp", test_dsp},
      {"upsample", test_upsample},
      {"record_buffer", test_record_buffer},
      {"wav_header", test_wav_header},
      {"wav_stream_any_split", test_wav_stream_any_split},
      {"wav_trailing_and_stop", test_wav_trailing_and_stop},
      {"wav_errors", test_wav_errors},
      {"chunked", test_chunked},
      {"chunked_wav_pipeline", test_chunked_wav_pipeline},
      {"error_code_json", test_error_code_json},
      {"http_errors", test_http_errors},
      {"join_url", test_join_url},
      {"percent_and_ascii", test_percent_and_ascii},
      {"base64_bitmap", test_base64_bitmap},
      {"device_id", test_device_id},
      {"pins", test_pins},
  };
  int failedTests = 0;
  for (const TestCase& t : tests) {
    int before = g_fail;
    t.fn();
    bool ok = g_fail == before;
    if (!ok) ++failedTests;
    std::printf("%s %s\n", ok ? "PASS" : "FAIL", t.name);
  }
  std::printf("\n%zu tests, %d checks, %d failed checks, %d failed tests\n", sizeof(tests) / sizeof(tests[0]), g_checks,
              g_fail, failedTests);
  return g_fail == 0 ? 0 : 1;
}
