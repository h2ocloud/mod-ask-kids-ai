# 架構

```
 按住按鈕 ──► ESP32-S3（本 repo 韌體）──HTTPS POST WAV──► 你自己的伺服器 ──► STT → 兒童規則 → LLM → 兒童規則 → TTS
   │            │  INMP441 錄音（I2S0）                     （server/ 是最小參考實作）
   │            │  OLED 狀態（I2C）                                  │
   └ 放開 ──────┘  MAX98357A 播放（I2S1）◄──── WAV 串流回答 ─────────┘
```

- 裝置只做「錄、傳、播、顯示」。辨識、回答、兒童內容規則、提問紀錄、額度全在伺服器端。
- 協議見 `SERVER_API.md`（v1：`GET /v1/health`、`POST /v1/ask`）。
- 預期延遲 2–4 秒（上傳＋STT＋LLM＋第一段 TTS；依伺服器與網路而定，**未實測**）。

## 韌體檔案

| 檔案 | 內容 | 能不能在電腦上測 |
|---|---|---|
| `mod_ask.ino` | `setup()`／`loop()`、狀態轉換時的動作、播放回呼 | 否（硬體） |
| `config.h` | 腳位、錄音秒數、音量上限、逾時；`static_assert` 擋危險腳位 | 編譯期檢查 |
| `secrets.example.h` | Wi‑Fi 三組、伺服器網址、裝置 token、根憑證（全空） | — |
| `audio_io.*` | I2S 錄音工作（core 0）＋預錄 200 ms 環形緩衝＋PSRAM 錄音緩衝；I2S 播放與音量；提示音 | 否 |
| `display.*` | OLED 繪圖工作（約 8 fps），臉＋中文狀態字＋音量條＋伺服器點陣 | 否 |
| `net_ask.*` | Wi‑Fi 多組、裝置 ID（NVS 亂數）、HTTPS、health、ask 串流播放 | 否 |
| `labels_zh.h` | 中文狀態字點陣（自動產生，OFL-1.1） | — |
| `src/core/ask_state.h` | 狀態機 | ✅ |
| `src/core/button.h` | 去彈跳 | ✅ |
| `src/core/audio_dsp.h` | 32→16 bit、直流阻隔、音量、音量條、錄音緩衝、升頻 | ✅ |
| `src/core/wav.h` | WAV 標頭、串流 WAV 解析（任意切段、略過 LIST、長度 0／0xFFFFFFFF） | ✅ |
| `src/core/chunked.h` | HTTP chunked 解碼、錯誤 JSON 取 code | ✅ |
| `src/core/proto.h` | 錯誤分類、重試規則、網址組合、百分比解碼、base64、點陣 | ✅ |
| `src/core/pins_guard.h` | 不能用的腳位清單 | ✅ |

`src/core/` 不依賴 Arduino，`firmware/test/test_core.cpp` 用 clang＋ASan／UBSan 在電腦上跑。

## 狀態機

| 狀態 | OLED | 進入時做什麼 | 離開條件 |
|---|---|---|---|
| 尚未設定 | 「尚未設定／請大人設定 secrets.h」 | 不連網 | 重新燒錄 |
| 連線中 | 「連線中」＋跑動的點 | 連 Wi‑Fi（最多 20 s） | 連上 → 待機；失敗 → 沒有網路 |
| 沒有網路 | 難過臉「沒有網路」 | 每 30 s 重試；按按鈕播兩聲低音 | 連上 → 待機 |
| 待機 | 微笑「按住說話」 | — | 按下 → 聆聽中 |
| 聆聽中 | 「聆聽中」＋音量條＋剩餘秒數 | 開始錄音（含按下前 200 ms） | 放開或錄滿 → 思考中；太短（< 0.3 s）→ 待機 |
| 思考中 | 「思考中」＋跑動的點 | 上傳 WAV，等伺服器 | 收到 200 → 回答中；失敗 → 出錯了 |
| 回答中 | 嘴巴開合「回答中」＋伺服器點陣或英文字 | 串流播放 | 播完 → 待機；按一下 → 聆聽中（插話） |
| 出錯了 | X 眼＋錯誤原因（中文＋英文代碼） | 一聲低音 | 3 s 後 → 待機；按下 → 聆聽中 |

## 記憶體

- 錄音緩衝在 PSRAM：44 B＋12 s × 16 kHz × 2 B ≈ 384 KB（8 MB PSRAM 的 4.6%）。
- 播放不整段存：網路收到多少就解析多少、寫進 I2S DMA；I2S 寫入會阻塞，自然節流。
- 編譯結果（Arduino-ESP32 3.3.12）：程式 1,202,667 B（app 槽 3 MB 的 38%），全域變數 60,468 B（內部 RAM 的 18%）。

## 安全與隱私（裝置端）

- `secrets.h` 不進版控；`WiFi.persistent(false)`，帳密不寫進 NVS。
- 伺服器網址預設空字串；沒填就停在「尚未設定」，**不會連任何網址**。
- HTTPS 預設用內建 Mozilla 根憑證驗證；`ASK_TLS_INSECURE` 預設 0。
- 裝置 ID 是亂數（不是 MAC）；不傳 SSID、位置或任何個資。
- 錄音只存在 RAM，每次新錄音覆蓋；裝置不保存歷史。
