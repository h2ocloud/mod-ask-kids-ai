# 韌體選擇：精簡自製（主線）＋ xiaozhi-esp32（選配，不改線）

**結論：主線用精簡自製韌體（Arduino-ESP32 3.x，MIT）。** xiaozhi-esp32 列為選配：本專案接線和它的 `bread-compact-wifi-128x64` 板型完全一致，想換就照 `docs/XIAOZHI_OPTION.md` 建置，不用重新接線、不用寫自訂板型。本 repo 不包含 xiaozhi 的任何程式碼。

評估日期 2026-11-15；xiaozhi-esp32 看的是 v2.6.0（2026-11-13 發佈）與當天的 main 分支，後端 xiaozhi-esp32-server v0.9.8。只讀原始碼與官方文件，**沒有實際編譯 xiaozhi**。

## 1. 選擇標準與結果

| 標準（brief） | 精簡自製 | xiaozhi-esp32 |
|---|---|---|
| POC 要快出結果 | ✅ 已編譯通過（arduino-cli，冷編譯約 45 s）、主機端測試 19 項／573 個檢查全過 | ⚠️ 需要 ESP-IDF ≥ 6.0.1（建議 `release/v6.1` 分支）＋大量 managed components；官方沒有編譯時間數據 |
| 可讀可改 | ✅ 約 1,000 行，四個檔案（音訊、顯示、網路、主程式）＋可在電腦上測的純邏輯標頭 | ⚠️ 大型專案（音訊服務、Opus、AFE、LVGL、MCP、OTA、多種協議），改行為要讀很多層 |
| 授權乾淨 | ✅ 自己的程式碼 MIT；相依只有 Arduino-ESP32 core（LGPL-2.1，見 §4）與 U8g2（BSD-2-Clause）；OLED 中文字點陣來自 Cubic 11（OFL-1.1） | ⚠️ 本體 MIT；但 `esp-sr`、`esp_audio_codec` 是「Espressif 修改版 MIT」（限 Espressif 晶片），字型元件 `78/xiaozhi-fonts` 的授權檔查不到，提示音 ogg 沒有授權說明 |
| 不依賴第三方雲 | ✅ 伺服器網址預設空字串，沒填就不連網；只打你設定的那一個網址 | ⚠️ **預設 OTA 網址是官方雲**（`CONFIG_OTA_URL` = `https://api.tenclass.net/xiaozhi/ota/`）。開機一定先打 OTA 端點取得 WebSocket 位址；改成自架才不連官方雲 |
| 兒童安全 | 伺服器端負責（參考伺服器已有規則、過濾、額度、紀錄保留期） | 同樣全靠伺服器；韌體與官方 server 都沒有內容過濾。`bread-compact-wifi` 還會把「燈」的 MCP 工具暴露給 LLM |
| 協議適配自家伺服器 | ✅ 一般 HTTP POST＋WAV，伺服器端約 100 行就能接（`docs/SERVER_API.md`） | ⚠️ 要實作 OTA 端點＋WebSocket＋hello＋Opus 編解碼＋listen/tts 訊息 |
| 延遲 | 預期 2–4 s（PCM 上傳 10 s 錄音約 320 KB；未實測） | 串流 Opus，理論上較低（未實測） |
| 離線 | OLED「沒有網路」＋本機提示音；不會自己開熱點 | 沒網路 60 s 後進配網熱點模式（小孩手上可能被誤用）；有預錄提示音 |
| 喚醒詞 | 不需要（按住說話） | ESP-SR 本地喚醒詞；用 `build.py` 不加參數時 zh-TW 會自動選「你好小智」，要明確 `--wake-word disabled` |

## 2. 為什麼這樣選

1. **POC 要能馬上驗證整條路**：按鈕 → 錄音 → HTTPS → 伺服器 → 語音回答。自製版每一步都可以單獨測：錄音緩衝、WAV 串流解析、chunked 解碼、錯誤碼、狀態機、升頻都在電腦上跑過單元測試與變異測試。
2. **自家伺服器端比較省事**：HTTP＋WAV 不用 Opus、不用常駐 WebSocket；STT／LLM／TTS 換引擎不影響裝置。
3. **小孩用的裝置，越少「意外連外」越好**：自製版只有一個可設定的網址，空白就不連；xiaozhi 要改 OTA 網址並注意配網頁可被改（`show_ota_config`）。
4. **授權清楚**：公開 repo 要能說清楚每個檔的授權。

代價（誠實列出）：
- 沒有 Opus 壓縮，上傳較大（16 kHz PCM＝32 KB/s）。家用 Wi‑Fi 足夠，行動熱點會慢。
- 沒有 AEC（回音消除）與喚醒詞；按住說話不需要，但不能「邊播邊聽」。
- 沒有 OTA（分割表已預留兩個 3 MB app 槽，之後可加）。
- 沒有 Wi‑Fi 設定網頁；Wi‑Fi 與伺服器網址寫在 `secrets.h` 重新燒錄。

## 3. xiaozhi 選配：可行，而且不用改線

- 本專案腳位（麥克風 4/5/6、功放 7/15/16、OLED 41/42、按鈕 47）和 `main/boards/bread-compact-wifi/config.h` 一致；GPIO47 按下 `StartListening()`、放開 `StopListening()`，就是按住說話。
- 用 `bread-compact-wifi-128x64` 變體（預設的 `bread-compact-wifi` 是 128×32，選錯畫面只剩一半）。
- 它另外用到 GPIO0（板上 BOOT 鍵）、GPIO39／40（音量鍵，沒接會被內部上拉，不會誤觸）、GPIO48（單顆 LED，v1.1 板上沒有東西）、GPIO18（燈，設為輸出低）。這些腳本專案都沒接，不衝突。
- 自訂板型官方文件 `docs/custom-board.md`：新增 3 個檔（約 260 行可從 `bread-compact-wifi` 複製改名）＋改 `Kconfig.projbuild`、`CMakeLists.txt` 各約 4 行。**本專案不需要**，直接用現成板型即可，所以不提供「半套」的板型檔。
- 步驟與注意事項見 `docs/XIAOZHI_OPTION.md`。

## 4. 授權處理

| 元件 | 授權 | 怎麼處理 |
|---|---|---|
| 本專案韌體（`firmware/`） | MIT | `LICENSE`、檔頭 SPDX |
| Arduino-ESP32 core 3.3.12 | LGPL-2.1（core）＋各 IDF 元件授權 | 不隨 repo 散布；使用者自行安裝。若散布編譯好的韌體，依 LGPL 提供相同版本 core 的取得方式（本 repo 不附編譯韌體） |
| U8g2 2.36.19 | BSD-2-Clause（程式）；字型各自授權 | 只用 `u8g2_font_6x10_tf`（X11 misc-fixed，公眾領域）。U8g2 由使用者自行安裝 |
| OLED 中文字點陣 `labels_zh.h` | OFL-1.1（由 Cubic 11 算繪） | `LICENSES/OFL-1.1-Cubic-11.txt`；`firmware/tools/gen_labels.py` 可重算 |
| xiaozhi-esp32 | MIT | 本 repo **不包含**其程式碼；選配文件只有連結與步驟 |

沒有任何相依強制 GPL，所以韌體維持 MIT。

## 5. 證據（xiaozhi，路徑皆在 xiaozhi-esp32 repo 內）

| 事實 | 位置 |
|---|---|
| 板型腳位 | `main/boards/bread-compact-wifi/config.h`（WS4/SCK5/DIN6、DOUT7/BCLK15/LRCK16、SDA41/SCL42、TOUCH_BUTTON 47） |
| 按住說話 | `main/boards/bread-compact-wifi/compact_wifi_board.cc`（PressDown→StartListening、PressUp→StopListening） |
| OLED 型號選項 | `main/Kconfig.projbuild`（SSD1306 128x32／128x64、SH1106 128x64）；`config.json` 有 `bread-compact-wifi-128x64` |
| 預設 OTA 網址 | `main/Kconfig.projbuild` `config OTA_URL` |
| 開機先打 OTA 取得 WebSocket 設定 | `main/application.cc` ActivationTask；`main/ota.cc` |
| 啟用碼只在 OTA 回應帶 `activation` 時出現 | `main/ota.cc`、`docs/ota.md` |
| 協議 | `docs/websocket.md`、`docs/mqtt-udp.md` |
| 自架 server 的 OTA 端點 | xiaozhi-esp32-server `core/http_server.py`、`core/api/ota_handler.py` |
| ESP-IDF 版本需求 | `README.md`、`main/idf_component.yml`（≥ 6.0.1） |
| release 大小 | v2.6.0 `bread-compact-wifi-128x64.zip` 1,912,531 B，內含 8,949,709 B 的 merged binary（GitHub release assets） |
| 授權 | `LICENSE`（MIT）；components.espressif.com 上 esp-sr、esp_audio_codec 的 license.txt |
