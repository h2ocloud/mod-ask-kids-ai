// ask_state.h — 問答機狀態機（純邏輯，不依賴 Arduino，主機端可測）
// SPDX-License-Identifier: MIT
//
// 狀態只描述「現在畫面該顯示什麼、按鈕按下去會發生什麼」。
// 真正的動作（開始錄音、上傳、播放）由 mod_ask.ino 在「進入某狀態」時執行。
#pragma once
#include <stdint.h>

namespace askcore {

enum class State : uint8_t {
  NoConfig,        // secrets.h 沒填 Wi-Fi 或伺服器網址：只顯示設定提示
  ConnectingWifi,  // 開機後連線中
  Offline,         // Wi-Fi 斷線／連不上：按按鈕只會播放離線提示音
  Idle,            // 待機：等按鈕
  Listening,       // 聆聽中：按住按鈕錄音
  Thinking,        // 思考中：上傳錄音、等伺服器第一個位元組
  Speaking,        // 回答中：串流播放伺服器回傳的語音
  Error,           // 錯誤畫面（顯示幾秒後自動回待機）
};

enum class Event : uint8_t {
  WifiUp,          // Wi-Fi 已連上
  WifiDown,        // Wi-Fi 斷線或連線逾時
  ButtonDown,      // 按鈕按下（已去彈跳）
  ButtonUp,        // 按鈕放開（已去彈跳）
  RecordLimit,     // 錄音到達上限秒數（還按著也一樣送出）
  RecordTooShort,  // 放開時錄音短於下限：當成誤觸
  ResponseStart,   // 伺服器回 200，開始收到語音
  RequestFailed,   // 連線失敗、逾時、或伺服器回錯誤碼
  PlayDone,        // 語音播完（或達播放上限）
  ErrorTimeout,    // 錯誤畫面顯示時間到
};

// 下一個狀態。不合法的事件一律保持原狀（例如思考中再按按鈕＝忽略）。
// wifiUp：目前 Wi-Fi 是否連線（錯誤畫面結束後要回待機或離線，看它）。
inline State next(State s, Event e, bool wifiUp) {
  switch (s) {
    case State::NoConfig:
      return State::NoConfig;  // 沒設定就不做任何網路動作，重新燒錄才會離開

    case State::ConnectingWifi:
      if (e == Event::WifiUp) return State::Idle;
      if (e == Event::WifiDown) return State::Offline;
      return s;

    case State::Offline:
      if (e == Event::WifiUp) return State::Idle;
      return s;  // 按鈕在離線時只觸發提示音（由主程式處理），狀態不變

    case State::Idle:
      if (e == Event::ButtonDown) return wifiUp ? State::Listening : State::Offline;
      if (e == Event::WifiDown) return State::Offline;
      if (e == Event::RequestFailed) return State::Error;  // 背景請求（開機 health 檢查）失敗
      return s;

    case State::Listening:
      if (e == Event::ButtonUp || e == Event::RecordLimit) return State::Thinking;
      if (e == Event::RecordTooShort) return wifiUp ? State::Idle : State::Offline;
      return s;  // 錄音中斷線：先錄完，送出時自然會失敗並顯示錯誤

    case State::Thinking:
      if (e == Event::ResponseStart) return State::Speaking;
      if (e == Event::RequestFailed) return State::Error;
      return s;  // 思考中按按鈕：忽略（避免重複送出）

    case State::Speaking:
      if (e == Event::PlayDone) return wifiUp ? State::Idle : State::Offline;
      if (e == Event::ButtonDown) return wifiUp ? State::Listening : State::Offline;  // 插話：停播、直接再問
      if (e == Event::RequestFailed) return State::Error;  // 播到一半斷線
      return s;

    case State::Error:
      if (e == Event::ErrorTimeout) return wifiUp ? State::Idle : State::Offline;
      if (e == Event::ButtonDown) return wifiUp ? State::Listening : State::Offline;
      return s;
  }
  return s;
}

inline const char* stateName(State s) {
  switch (s) {
    case State::NoConfig: return "NoConfig";
    case State::ConnectingWifi: return "ConnectingWifi";
    case State::Offline: return "Offline";
    case State::Idle: return "Idle";
    case State::Listening: return "Listening";
    case State::Thinking: return "Thinking";
    case State::Speaking: return "Speaking";
    case State::Error: return "Error";
  }
  return "?";
}

inline const char* eventName(Event e) {
  switch (e) {
    case Event::WifiUp: return "WifiUp";
    case Event::WifiDown: return "WifiDown";
    case Event::ButtonDown: return "ButtonDown";
    case Event::ButtonUp: return "ButtonUp";
    case Event::RecordLimit: return "RecordLimit";
    case Event::RecordTooShort: return "RecordTooShort";
    case Event::ResponseStart: return "ResponseStart";
    case Event::RequestFailed: return "RequestFailed";
    case Event::PlayDone: return "PlayDone";
    case Event::ErrorTimeout: return "ErrorTimeout";
  }
  return "?";
}

}  // namespace askcore
