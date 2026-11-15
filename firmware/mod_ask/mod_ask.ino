// mod_ask.ino — 兒童 AI 問答機（按住說話 → 伺服器 STT/LLM/TTS → 播放）
// SPDX-License-Identifier: MIT
//
// 硬體：ESP32-S3-DevKitC-1 N16R8＋INMP441＋MAX98357A＋0.96" I2C OLED＋12×12 按鈕
// 協議：docs/SERVER_API.md（v1）；架構：docs/ARCHITECTURE.md
// 狀態：只做過編譯與主機端單元測試，尚未實機驗證。
#include <Arduino.h>

#include "audio_io.h"
#include "config.h"
#include "display.h"
#include "net_ask.h"
#include "src/core/ask_state.h"
#include "src/core/audio_dsp.h"
#include "src/core/button.h"

using askcore::AskError;
using askcore::Event;
using askcore::State;

static State state = State::ConnectingWifi;
static AskError lastError = AskError::None;
static uint32_t errorAt = 0;
static bool askPending = false;
static askcore::Debouncer button(BUTTON_DEBOUNCE_MS);
static bool bargeIn = false;
static bool audioOk = false;

static bool buttonRaw() { return digitalRead(PIN_BUTTON) == LOW; }  // 內部上拉：按下＝低

static void enterState(State s);

static void dispatch(Event e) {
  State n = askcore::next(state, e, netConnected());
  Serial.printf("[STATE] %s --%s--> %s\n", askcore::stateName(state), askcore::eventName(e), askcore::stateName(n));
  if (n != state) enterState(n);
}

static void fail(AskError e) {
  lastError = e;
  uiSetError(e);
  dispatch(Event::RequestFailed);
}

static void enterState(State s) {
  State prev = state;
  state = s;
  uiSetState(s);
  switch (s) {
    case State::Listening:
      audioStartRecording();
      break;
    case State::Thinking:
      audioStopRecording();
      askPending = true;
      break;
    case State::Error:
      errorAt = millis();
      audioBeep(330, 120);  // 低音一聲
      break;
    case State::Offline:
      if (prev == State::Listening) audioStopRecording();
      break;
    case State::Idle:
      if (prev == State::Listening) audioStopRecording();
      break;
    default:
      break;
  }
}

// ---- 播放回呼（在 netAsk 裡被呼叫）----
static uint32_t playedSamples = 0;
static uint32_t playLimitSamples = 0;
static uint32_t playRate = 0;            // 伺服器 WAV 的取樣率
static askcore::Upsampler upsampler;     // 24 k／22.05 k 等功放不支援的取樣率要升頻
static bool unsupportedRate = false;

static void onResponseStart(void*) {
  playedSamples = 0;
  playLimitSamples = 0;
  playRate = 0;
  unsupportedRate = false;
  const uint8_t* bm = netLastBitmap();
  if (bm) uiSetAnswerBitmap(bm);
  const char* t = netLastAnswerText();
  if (t && askcore::isPrintableAscii(t)) uiSetAnswerAscii(t);
  dispatch(Event::ResponseStart);
}

static bool onPcm(int16_t* s, size_t n, uint32_t rate, void*) {
  if (rate != playRate) {
    playRate = rate;
    uint8_t f = askcore::upsampleFactor(rate);
    if (f == 0) {
      Serial.printf("[PLAY] unsupported sample rate %u Hz\n", static_cast<unsigned>(rate));
      unsupportedRate = true;
      return false;
    }
    upsampler.reset(f);
    playLimitSamples = rate * PLAY_MAX_SECONDS;
    if (!audioSpeakerBegin(rate * f)) return false;
  }
  if (upsampler.factor() == 1) {
    audioSpeakerWrite(s, n);
  } else {
    int16_t up[64 * 4];  // net_ask 每次最多給 64 個樣本；最多 4 倍
    while (n > 0) {
      size_t k = n < 64 ? n : 64;
      size_t m = upsampler.process(s, k, up);
      audioSpeakerWrite(up, m);
      s += k;
      n -= k;
      playedSamples += k;
    }
    return playedSamples < playLimitSamples;
  }
  playedSamples += n;
  return playedSamples < playLimitSamples;
}

static bool pollDuringPlay(void*) {
  // 播放中按一下＝插話：停播、直接開始錄下一題
  if (button.update(buttonRaw(), millis()) == askcore::Edge::Down) {
    bargeIn = true;
    return false;
  }
  return true;
}

static void runAsk() {
  size_t len = 0;
  const uint8_t* wav = audioWavBuffer(&len);
  Serial.printf("[ASK] uploading %u ms of audio (%u B)\n", static_cast<unsigned>(audioRecordedMs()),
                static_cast<unsigned>(len));
  bargeIn = false;
  AskHooks hooks{onResponseStart, onPcm, pollDuringPlay, nullptr};
  AskOutcome r = netAsk(wav, len, hooks);
  audioSpeakerEnd();
  if (bargeIn) {
    dispatch(Event::ButtonDown);
    return;
  }
  if (unsupportedRate) {
    fail(AskError::BadResponse);
    return;
  }
  if (r.err != AskError::None) {
    fail(r.err);
    return;
  }
  dispatch(Event::PlayDone);
}

void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.printf("\n[BOOT] mod-ask %s  PSRAM=%u B  heap=%u B\n", MOD_ASK_FW_VERSION,
                static_cast<unsigned>(ESP.getPsramSize()), static_cast<unsigned>(ESP.getFreeHeap()));
  pinMode(PIN_BUTTON, INPUT_PULLUP);
  uiBegin();
  audioSetVolume(SPEAKER_VOLUME);

  audioOk = audioBegin();
  if (!audioOk) {
    // 沒有 PSRAM 或 I2S 起不來：停在錯誤畫面（重新上電或修正設定才會離開）
    lastError = AskError::BadAudio;
    uiSetError(lastError);
    state = State::Error;
    uiSetState(state);
    return;
  }

  if (!netConfigured()) {
    Serial.printf("[BOOT] not configured (%s). Copy secrets.example.h to secrets.h and fill it in.\n",
                  netHasSecretsFile() ? "secrets.h incomplete" : "no secrets.h");
    state = State::NoConfig;
    uiSetState(state);
    return;
  }

  netBegin();
  Serial.printf("[BOOT] device id %s\n", netDeviceId());
  state = State::ConnectingWifi;
  uiSetState(state);
  bool up = netConnect(WIFI_CONNECT_TIMEOUT_MS);
  dispatch(up ? Event::WifiUp : Event::WifiDown);
  if (up) {
    AskError h = netHealth();
    if (h != AskError::None) fail(h);
    else audioBeep(880, 80);  // 準備好了：高音短嗶
  }
}

void loop() {
  const uint32_t now = millis();
  if (state == State::NoConfig || !audioOk) {
    delay(50);
    return;
  }

  // Wi-Fi 狀態變化
  static bool wasUp = netConnected();
  bool up = netConnected();
  if (up != wasUp) {
    wasUp = up;
    dispatch(up ? Event::WifiUp : Event::WifiDown);
  }
  if (!up) netMaintain(now);

  // 按鈕
  askcore::Edge edge = button.update(buttonRaw(), now);
  if (edge == askcore::Edge::Down) {
    if (state == State::Offline) {
      audioBeep(440, 150);  // 離線提示：兩聲低音
      delay(80);
      audioBeep(330, 200);
    }
    dispatch(Event::ButtonDown);
  } else if (edge == askcore::Edge::Up && state == State::Listening) {
    if (audioRecordedMs() < REC_MIN_MS + REC_PREROLL_MS) {
      audioStopRecording();
      dispatch(Event::RecordTooShort);
    } else {
      dispatch(Event::ButtonUp);
    }
  }

  if (state == State::Listening) {
    uiSetLevel(audioLevelBars());
    uint32_t ms = audioRecordedMs();
    uint32_t maxMs = REC_MAX_SECONDS * 1000;
    uiSetRecordLeft(static_cast<uint8_t>(ms >= maxMs ? 0 : (maxMs - ms + 999) / 1000));
    if (audioRecordFull()) dispatch(Event::RecordLimit);
  }

  if (state == State::Thinking && askPending) {
    askPending = false;
    runAsk();
  }

  if (state == State::Error && now - errorAt > ERROR_SHOW_MS) dispatch(Event::ErrorTimeout);

  delay(5);
}
