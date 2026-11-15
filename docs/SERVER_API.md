# MOD-ASK 伺服器 API（協議 v1）

裝置（ESP32-S3 韌體）和「你自己的伺服器」之間只用一般 HTTP(S)，沒有 WebSocket、沒有專用雲端。
任何能收 HTTP POST、回 WAV 的伺服器都能接；`server/` 有一份 Python 最小參考實作。

> 文件裡的網址一律是佔位：`https://ai.example.com/ask-api`。韌體預設**沒有**任何網址，要自己在 `secrets.h` 填。

## 0. 名詞

| 名詞 | 意思 |
|---|---|
| `BASE` | 裝置設定的伺服器根網址，例如 `https://ai.example.com/ask-api`（結尾不要斜線；裝置會自己去掉多餘的 `/`） |
| PCM16 | 16-bit 有號整數、little-endian、單聲道 |
| 裝置 ID | 第一次開機用硬體亂數產生的 16 位十六進位字串，存在 NVS。**不是 MAC**，清除 NVS 就會換一個 |

## 1. 端點一覽

| 方法 | 路徑 | 用途 | 裝置何時呼叫 |
|---|---|---|---|
| `GET` | `BASE/v1/health` | 確認伺服器活著、版本相容 | 開機連上 Wi‑Fi 後一次；之後每次錯誤恢復時 |
| `POST` | `BASE/v1/ask` | 上傳一段錄音，取回語音回答 | 放開按鈕（或錄到上限）後 |

只有這兩個。兒童模式規則、提問紀錄、額度、STT／LLM／TTS 引擎都在伺服器端，裝置不知道也不需要知道。

## 2. `GET /v1/health`

請求標頭：`Authorization: Bearer <token>`（有設定才帶）、`X-Device-Id`、`X-Fw-Version`。

回應 `200 application/json`：

```json
{"ok": true, "api": "mod-ask/1", "max_seconds": 15, "sample_rate": 16000}
```

| 欄位 | 型別 | 說明 |
|---|---|---|
| `ok` | bool | 一定是 `true`；不健康就回 503 |
| `api` | string | 協議版本，v1 固定 `mod-ask/1`。裝置只接受前綴 `mod-ask/1` |
| `max_seconds` | number | 伺服器接受的最長錄音秒數（裝置取自己設定和這個值的較小者） |
| `sample_rate` | number | 伺服器希望收到的取樣率，v1 固定 16000 |

## 3. `POST /v1/ask`

### 3.1 請求

| 標頭 | 必填 | 值 |
|---|---|---|
| `Content-Type` | 是 | `audio/wav` |
| `Content-Length` | 是 | 位元組數（裝置不用 chunked 上傳） |
| `Authorization` | 選 | `Bearer <ASK_DEVICE_TOKEN>`；伺服器有開 token 檢查時必填 |
| `X-Device-Id` | 是 | 16 位十六進位（見 §0） |
| `X-Fw-Version` | 是 | 例如 `0.1.0` |
| `Accept` | 是 | `audio/wav` |

本文：標準 RIFF/WAVE，`fmt ` 為 PCM（format 1）、單聲道、16000 Hz、16 bit，後接 `data`。
- 長度：0.3 s 以上（裝置端短於 0.3 s 會當成誤觸直接丟掉，不會送出）；上限見 `health.max_seconds`，參考伺服器預設 15 s（480,044 B）。
- 裝置已做：去直流（一階高通）、32→16 bit 轉換；沒有做降噪、AGC、VAD。

### 3.2 成功回應 `200`

| 標頭 | 必填 | 值 |
|---|---|---|
| `Content-Type` | 是 | `audio/wav` |
| `Content-Length` 或 `Transfer-Encoding: chunked` | 擇一 | 兩種裝置都會處理；要「邊產生邊播」就用 chunked |
| `X-Answer-Text` | 選 | 回答文字，UTF-8 再做百分比編碼（RFC 3986），解碼後 ≤ 200 B。裝置只印到序列埠；若全是可列印 ASCII 也會顯示在 OLED |
| `X-Display-Bitmap` | 選 | OLED 下半部圖片：128×32、1 bpp、逐列、每列 16 B、每個位元組最高位元在最左邊、1＝亮；共 512 B，標準 base64（含 `=` 補位，684 字元）。伺服器用任何字型把中文算成點陣，裝置不用內建中文字型 |
| `X-Request-Id` | 選 | 除錯用，裝置印到序列埠 |

本文：RIFF/WAVE，PCM16 單聲道。**取樣率建議 16000 Hz。**
- 功放 MAX98357A 只吃 8000／16000／32000／44100／48000 Hz（datasheet：11.025／12／22.05／24 kHz 不支援）。
- 裝置對 24000、22050（×2）與 12000、11025（×4）會做線性內插升頻後再播，所以常見 TTS 的 24 kHz 輸出也能直接回；其他取樣率裝置會當成「回答格式錯誤」。
- 串流時 `RIFF` 與 `data` 的長度欄位可以填 `0` 或 `0xFFFFFFFF`，裝置會一直播到連線結束。
- 裝置會略過 `data` 前的其他 chunk（`LIST` 等）；`fmt ` 必須在 `data` 之前。
- 裝置端播放上限 60 s，超過就停止並關閉連線。

### 3.3 錯誤回應

一律 `application/json`：

```json
{"error": {"code": "too_long", "message": "audio longer than 15 s"}}
```

| HTTP | `code` | 什麼時候 | 裝置怎麼做 |
|---|---|---|---|
| 400 | `bad_audio` | 不是 WAV、格式不是 16 kHz／16 bit／單聲道 | OLED「格式錯誤」，不重試 |
| 400 | `too_short` | 有效音訊太短 | OLED「沒聽到」，不重試 |
| 401 | `unauthorized` | token 錯或缺 | OLED「未授權」，不重試 |
| 404 | `not_found` | 路徑錯（多半是 `BASE` 設錯） | OLED「網址錯誤」 |
| 413 | `too_long` | 超過 `max_seconds` | OLED「說太久了」 |
| 415 | `unsupported_media_type` | `Content-Type` 不對 | OLED「格式錯誤」 |
| 422 | `no_speech` | STT 沒辨識出文字（**建議改回 200＋一段「我沒聽清楚，再說一次好嗎？」語音**，422 只是備用） | OLED「沒聽清楚」 |
| 429 | `rate_limited` | 超過每分鐘／每日額度（兒童模式時間限制也用這個），帶 `Retry-After` 秒數 | OLED「休息一下」，不重試 |
| 500 | `internal` | 伺服器自己出錯 | OLED「伺服器錯誤」，不重試 |
| 502 | `upstream_failed` | STT／LLM／TTS 引擎失敗 | 同上 |
| 503 | `unavailable` | 維護中，帶 `Retry-After` | 同上 |
| 504 | `upstream_timeout` | 引擎逾時 | 同上 |

**兒童內容規則不用錯誤碼表達**：被過濾的問題照樣回 200，內容是伺服器準備好的安全回覆語音（例如「這個問題我們去問爸爸媽媽好不好？」）。這樣小孩聽到的是一句話，不是錯誤畫面。

## 4. 逾時與重試（裝置端預設，可在 `config.h` 改）

| 項目 | 預設 | 說明 |
|---|---|---|
| TCP／TLS 連線逾時 | 5 s | `ASK_CONNECT_TIMEOUT_MS` |
| 等第一個回應位元組 | 20 s | `ASK_RESPONSE_TIMEOUT_MS`；涵蓋上傳＋STT＋LLM＋第一段 TTS |
| 播放中兩段資料的間隔 | 5 s | `ASK_STREAM_IDLE_TIMEOUT_MS`；超過就停播 |
| 自動重試 | 1 次 | **只有**連線層失敗（DNS、TCP、TLS、請求沒送完）才重送一次。等回應逾時不重送（伺服器可能已在處理，重送會讓小孩多等 20 秒）；收到任何 HTTP 狀態碼也不重送 |
| health 逾時 | 5 s | 開機檢查用 |

伺服器端建議：收到請求到送出第一個音訊位元組 ≤ 4 s（目標 2–4 s）；內部硬上限 15 s，超過就回 504。

## 5. 安全與隱私

- **一定用 HTTPS**（裝置預設用韌體內建的 Mozilla 根憑證驗證；自簽憑證要在 `secrets.h` 填 `ASK_SERVER_ROOT_CA`）。`ASK_TLS_INSECURE 1` 只給區網測試用。
- `ASK_DEVICE_TOKEN` 是每台裝置的共享密鑰，只放在 `secrets.h`（已 gitignore）。伺服器存雜湊即可。
- 伺服器**不要保存錄音檔**。參考伺服器只記「時間、裝置 ID、辨識文字、回答文字、是否被過濾」，保留天數可設（預設 30 天），可以整個關掉。
- 裝置不傳 MAC、不傳 SSID、不傳位置；裝置 ID 是亂數，家長清除 NVS 就換新。
- 兒童模式（系統提示、輸入／輸出過濾、額度、使用時段）全部在伺服器端，見 `server/README.md`。

## 6. 範例

```sh
# 健康檢查
curl -s https://ai.example.com/ask-api/v1/health

# 用一段 16 kHz/16 bit/單聲道 WAV 測試，回答存成 answer.wav
curl -s -X POST https://ai.example.com/ask-api/v1/ask \
  -H 'Content-Type: audio/wav' -H 'Accept: audio/wav' \
  -H 'X-Device-Id: 0123456789abcdef' -H 'X-Fw-Version: 0.1.0' \
  --data-binary @question.wav -D headers.txt -o answer.wav
```

本機參考伺服器（假引擎）跑法見 `server/README.md`；它只綁 `127.0.0.1`，要給裝置連要自己改綁定位址並加 HTTPS 反向代理。

## 7. 版本

- v1（`mod-ask/1`）：本文件。
- 之後可能：Opus 上傳（省頻寬）、伺服器推送 WebSocket。會用新路徑 `/v2/...`，不改 v1。
