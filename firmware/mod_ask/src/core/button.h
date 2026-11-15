// button.h — 按鈕去彈跳（純邏輯）
// SPDX-License-Identifier: MIT
//
// 12×12 輕觸開關接 GPIO 與 GND，GPIO 開內部上拉：按下＝低電位。
// 這裡只處理「已轉成 pressed=true/false 的原始讀值」，輸出乾淨的按下／放開邊緣。
#pragma once
#include <stdint.h>

namespace askcore {

enum class Edge : uint8_t { None, Down, Up };

class Debouncer {
 public:
  explicit Debouncer(uint32_t stableMs = 30) : stableMs_(stableMs) {}

  // raw：這次讀到的原始狀態（true＝按下）；nowMs：毫秒時間（可回繞，用無號減法）
  Edge update(bool raw, uint32_t nowMs) {
    if (raw != candidate_) {
      candidate_ = raw;
      since_ = nowMs;
      return Edge::None;
    }
    if (candidate_ != stable_ && static_cast<uint32_t>(nowMs - since_) >= stableMs_) {
      stable_ = candidate_;
      if (stable_) {
        pressedAt_ = nowMs;
        return Edge::Down;
      }
      return Edge::Up;
    }
    return Edge::None;
  }

  bool pressed() const { return stable_; }
  // 目前按住多久（沒按住時回 0）
  uint32_t heldMs(uint32_t nowMs) const { return stable_ ? static_cast<uint32_t>(nowMs - pressedAt_) : 0; }

 private:
  uint32_t stableMs_;
  bool stable_ = false;
  bool candidate_ = false;
  uint32_t since_ = 0;
  uint32_t pressedAt_ = 0;
};

}  // namespace askcore
