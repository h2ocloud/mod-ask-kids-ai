// secrets.example.h — 範本。複製成 secrets.h 再填；secrets.h 已列入 .gitignore，不要 commit。
// SPDX-License-Identifier: MIT
//
// 沒有 secrets.h 時，韌體會用這份範本編譯：全部是空字串 → 開機顯示「尚未設定」，不連任何網路。
#pragma once

// Wi-Fi：最多 3 組，只支援 2.4 GHz。不用的留空字串。
#define WIFI_SSID_1 ""
#define WIFI_PASS_1 ""
#define WIFI_SSID_2 ""
#define WIFI_PASS_2 ""
#define WIFI_SSID_3 ""
#define WIFI_PASS_3 ""

// 你自己的伺服器根網址（協議見 docs/SERVER_API.md），結尾不要斜線。
// 例：https://ai.example.com/ask-api   ← 這是佔位網址，不是真的服務
#define ASK_SERVER_URL ""

// 選填：伺服器有開裝置 token 檢查時填（每台一組，伺服器只存雜湊）
#define ASK_DEVICE_TOKEN ""

// 選填：伺服器用自簽憑證時，貼上根憑證 PEM（含 BEGIN/END 行）。
// 留空 = 用韌體內建的 Mozilla 根憑證清單驗證（一般公開憑證用這個就好）。
#define ASK_SERVER_ROOT_CA ""

// 1 = HTTPS 不驗證憑證。只限區網測試，正式使用請保持 0。
#define ASK_TLS_INSECURE 0
