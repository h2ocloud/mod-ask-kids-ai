# 選配：改用 xiaozhi-esp32 韌體（同一套接線）

> 這是**選配**，不是本專案的主線，也沒有實際編譯或實機驗證過。主線韌體在 `firmware/`。
> xiaozhi-esp32 是 MIT 授權的第三方專案：https://github.com/78/xiaozhi-esp32 。本 repo 不包含它的程式碼。

## 什麼時候考慮
- 想要串流 Opus（上傳流量小、延遲可能更低）、本地喚醒詞、表情動畫、MCP 工具。
- 願意自架 xiaozhi-esp32-server（https://github.com/xinnan-tech/xiaozhi-esp32-server ，MIT）或在自己的伺服器實作它的協議。

## 接線
不用改。本專案腳位和 `bread-compact-wifi` 一致（見 `wiring/PINMAP.md`）。INMP441 的 L/R 一樣要接 GND（它讀左聲道）。

## 建置重點（依官方文件整理，未實測）
1. 安裝 **ESP-IDF 6.0.1 以上**（官方建議 `release/v6.1` 分支），依 xiaozhi README 設定環境。
2. 板型選 **`bread-compact-wifi-128x64`**（不是預設的 128×32）。
3. **把 OTA 網址改成你自己的伺服器**（menuconfig 的 `OTA_URL`，或板型 `config.json` 的 `sdkconfig_append` 加 `CONFIG_OTA_URL="https://ai.example.com/xiaozhi/ota/"`）。不改的話預設會連官方雲端。
4. 兒童機只用按鈕時，建置加 `--wake-word disabled`（zh-TW 預設會自動開「你好小智」喚醒詞）。
5. 考慮關掉配網頁的「進階：OTA 網址」欄（`show_ota_config`），避免被改到別的伺服器。這點官方沒有文件，需要讀碼確認。

## 伺服器最少要做的事（依 `docs/websocket.md` 整理）
1. `POST <OTA 網址>`：回 `{"websocket":{"url":"wss://…","token":"…"},"server_time":{…}}`，**不要**帶 `mqtt`、`activation`。
2. WebSocket：收裝置 `hello` → 回 `{"type":"hello","transport":"websocket","session_id":"…","audio_params":{"format":"opus","sample_rate":24000,"channels":1,"frame_duration":60}}`。
3. 收 `listen start`（mode `manual`）後的 16 kHz Opus 框，`listen stop` 後做 STT → LLM → TTS。
4. 回 `tts start`、24 kHz Opus 框、`tts stop`；要在螢幕顯示文字就另送 `stt`、`tts sentence_start`。
5. 處理 `abort`。

兒童內容規則、提問紀錄一樣要在伺服器端做；xiaozhi 韌體和官方 server 都沒有內容過濾。

## 已知差異與風險（讀碼推論，未實機驗證）
- 開機一定先打 OTA；第一次開機沒有可用的 OTA 端點就無法取得 WebSocket 位址。
- Wi‑Fi 連不上 60 秒會自動開配網熱點。
- 在「連線中」階段就放開按鈕，停止事件可能被丟掉（`application.cc` 的 `StopListening` 只在 Listening 狀態處理）。
- `esp-sr`、`esp_audio_codec` 的授權限用於 Espressif 晶片；字型元件與提示音的授權要自行確認後再散布編譯好的韌體。
