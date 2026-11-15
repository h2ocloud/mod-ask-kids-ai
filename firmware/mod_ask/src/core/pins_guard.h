// pins_guard.h — 編譯期擋掉 ESP32-S3-DevKitC-1 N16R8 上不能用的腳位
// SPDX-License-Identifier: MIT
//
// 依據（詳見 wiring/PINMAP.md 的來源）：
//   GPIO0/3/45/46   strapping（開機模式、JTAG 來源、VDD_SPI 電壓、ROM log）
//   GPIO19/20       原生 USB D-/D+
//   GPIO26–32       模組內部 SPI flash／PSRAM（DevKitC-1 沒有拉出）
//   GPIO33–37       Octal PSRAM（N16R8 = 8 MB Octal PSRAM：35/36/37 被佔用；33/34 板上未拉出）
//   GPIO38          DevKitC-1 v1.1 板載 RGB LED
//   GPIO48          DevKitC-1 v1.0 板載 RGB LED
//   GPIO43/44       UART0 TX/RX（USB 轉 UART 晶片，燒錄與序列埠 log 用）
#pragma once
#include <stdint.h>

namespace askcore {

constexpr bool pinForbidden(int gpio) {
  return gpio == 0 || gpio == 3 || gpio == 45 || gpio == 46 ||  // strapping
         gpio == 19 || gpio == 20 ||                               // USB
         (gpio >= 26 && gpio <= 37) ||                             // flash / octal PSRAM
         gpio == 38 || gpio == 48 ||                               // RGB LED（v1.1 / v1.0）
         gpio == 43 || gpio == 44 ||                               // UART0
         gpio < 0 || gpio > 48 || (gpio >= 22 && gpio <= 25);      // 晶片沒有 GPIO22–25
}

}  // namespace askcore
