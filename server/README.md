# MOD-ASK 最小參考伺服器

兒童 AI 問答機（ESP32 按住說話）的伺服器端參考實作：收一段 WAV，做 **STT → LLM → TTS**，回一段 WAV。
協議規格見 [`../docs/SERVER_API.md`](../docs/SERVER_API.md)，本實作完全照它做。

> **English summary.** A minimal reference server for the MOD-ASK push-to-talk kids' Q&A device (protocol `mod-ask/1`).
> Python 3.10+ standard library only (Pillow is optional, used only to draw the 128×32 `X-Display-Bitmap`).
> STT / LLM / TTS are swappable interfaces; defaults are offline fakes, and an explicit OpenAI-compatible HTTP configuration is provided (API keys are read **only** from environment variables).
> Child-mode rules (system prompt, keyword filters, PII detection, per-device quotas, allowed hours) and an optional JSONL question log (no audio kept, retention configurable) live on the server.
> It binds to `127.0.0.1` by default; for real use put it behind an HTTPS reverse proxy. License: MIT.

## 重點與限制

- **只用 Python 3.10+ 標準函式庫**（`http.server`、`wave`、`json`、`urllib`、`unittest`…）。在 Python 3.14 上測試。
- Pillow 是**選用**：只有要產生 `X-Display-Bitmap`（把中文回答畫成 128×32 點陣）時才需要；沒裝或沒設定字型就不送這個標頭。
- 預設使用**假引擎**，不連網、不需要任何金鑰，用來測裝置與協議。
- 這是**參考實作**：單一程序、記憶體計數額度、同步回應（先產生完整 WAV 再回，不做 chunked 串流）。
  第一個音訊位元組要等到 STT＋LLM＋TTS 都完成，用外部引擎時延遲約 2–4 秒是目標、不是保證。
- 兒童模式的關鍵字過濾是**粗篩**，會誤擋也會漏掉；它不能取代系統提示詞、LLM 供應商自己的安全機制，以及大人的陪伴。
- **正式使用請放在 HTTPS 反向代理後面，不要直接對外開放 HTTP。**裝置預設要求 HTTPS（SERVER_API §5）。

## 快速開始

```sh
cd server

# 1. 直接跑（全部用預設值：假引擎、只綁 127.0.0.1:8787、紀錄寫到 ./data/）
python3 -m mod_ask_server

# 2. 或用自己的設定（config.json、child_rules.json 都已被 .gitignore 排除）
cp config.example.json config.json
cp child_rules.example.json child_rules.json
python3 -m mod_ask_server --config config.json
```

另開一個終端機測試（本機路徑對應 SERVER_API §6 的範例）：

```sh
# 產生測試錄音（16 kHz／16 bit／單聲道，2 秒）
python3 tools/make_test_wav.py question.wav

curl -s http://127.0.0.1:8787/v1/health
# {"ok": true, "api": "mod-ask/1", "max_seconds": 15, "sample_rate": 16000}

curl -s -X POST http://127.0.0.1:8787/v1/ask \
  -H 'Content-Type: audio/wav' -H 'Accept: audio/wav' \
  -H 'X-Device-Id: 0123456789abcdef' -H 'X-Fw-Version: 0.1.0' \
  --data-binary @question.wav -D headers.txt -o answer.wav
cat headers.txt        # 看 X-Answer-Text（百分比編碼）、X-Request-Id
```

`Ctrl-C` 或 `SIGTERM` 會乾淨地關閉。命令列選項：`--config`、`--host`、`--port`、`-v`、`--version`。

## 檔案結構

```
server/
├── README.md
├── config.example.json         設定範例（複製成 config.json）
├── child_rules.example.json    兒童模式規則範例（複製成 child_rules.json）
├── .gitignore                  data/、config.json、child_rules.json、__pycache__/、*.pyc
├── mod_ask_server/
│   ├── __main__.py             命令列入口
│   ├── app.py                  HTTP 層：路由、標頭、驗證、錯誤 JSON
│   ├── service.py              問答流程：STT → 過濾 → LLM → 過濾 → TTS → 紀錄
│   ├── wavio.py                WAV 解析／驗證／產生
│   ├── child_mode.py           系統提示詞、關鍵字過濾、個資偵測與遮蔽
│   ├── quota.py                每台裝置的每分鐘／每日額度、允許使用時段
│   ├── qa_log.py               提問紀錄（JSONL）與保留期清除
│   ├── auth.py、hash_token.py  token 雜湊檢查與產生雜湊的小工具
│   ├── display.py              X-Display-Bitmap（打包為純 Python；畫字才需要 Pillow）
│   ├── answer_text.py          X-Answer-Text 編碼與截斷
│   ├── config.py、errors.py
│   └── engines/
│       ├── base.py             STT／LLM／TTS 介面（typing.Protocol）
│       ├── fake.py             假引擎（預設）
│       └── openai_compat.py    OpenAI 相容 HTTP 引擎（urllib）
├── tools/make_test_wav.py      產生測試用 WAV
└── tests/                      unittest（見最後一節）
```

## 設定檔

JSON；以底線開頭的鍵（例如 `"_說明"`）會被忽略，可當註解；**打錯鍵名會直接報錯**，不會靜默用預設值。
相對路徑以**設定檔所在資料夾**為準（沒給設定檔時以目前工作目錄為準）。完整範例見 `config.example.json`。

| 區塊 | 重點欄位（預設值） |
|---|---|
| `server` | `host`（`127.0.0.1`）、`port`（`8787`）、`base_path`（空；反向代理沒去掉前綴時填 `/ask-api`）、`hard_timeout_s`（`15`，整個問答的硬上限，超過回 504）、`max_concurrent`（`4`，同時處理數，超過回 503） |
| `limits` | `max_seconds`（`15`）、`max_body_bytes`（`null`＝依秒數推算，15 秒＝480,044 B） |
| `auth` | `token_sha256`（`[]`＝不檢查）、`health_requires_token`（`true`） |
| `stt`／`llm`／`tts` | `type`：`fake`（預設）、`openai_compat`、`custom`；各自的設定在同名子區塊，只有被選中的那塊生效 |
| `child_mode` | `rules_file`（`null`）、`empty_stt`（`speak`）、`max_answer_chars`（`150`） |
| `quota` | `per_minute`（`6`）、`per_day`（`200`）（`0`＝不限）、`utc_offset_minutes`（`480`）、`allowed_hours`（`enabled:false`、`07:00`–`20:30`） |
| `qa_log` | `enabled`（`true`）、`path`（`./data/qa_log.jsonl`）、`retention_days`（`30`） |
| `display` | `font_path`（空＝不送 `X-Display-Bitmap`）、`font_index`、`font_size`（`16`） |

## 換引擎

三個介面定義在 `mod_ask_server/engines/base.py`（`typing.Protocol`，不必繼承，有對應方法就行）：

```python
class STTEngine:  def transcribe(self, wav: bytes, *, timeout=None) -> str            # 沒聽到語音回 ""
class LLMEngine:  def complete(self, system_prompt, user_text, *, timeout=None) -> str  # 單輪、不帶歷史
class TTSEngine:  def synthesize(self, text, *, timeout=None) -> bytes                  # 回完整 WAV
```

失敗請丟 `EngineError`（→ 502 `upstream_failed`），逾時丟 `EngineTimeout`（→ 504 `upstream_timeout`）；
`timeout` 是整個問答剩餘的秒數。訊息裡不要放使用者的話或金鑰。

**TTS 輸出的取樣率**（SERVER_API §3.2）：PCM16 單聲道；功放只吃 8000／16000／32000／44100／48000 Hz，
裝置會把 24000、22050（×2）與 12000、11025（×4）升頻後播放。**伺服器不重取樣**：回傳的 WAV 取樣率只要在
`{8000, 16000, 32000, 44100, 48000, 24000, 22050, 12000, 11025}` 內就原樣送出，否則回 **502 `upstream_failed`**，
不會把裝置播不了的音訊送過去。建議 16000 Hz。

### 假引擎（預設）

| 引擎 | 行為 |
|---|---|
| `FakeSTT` | 回傳設定檔 `fixed_text`；沒設定時依錄音長度回「（測試）你好」之類，**靜音錄音回空字串**。`fixed_text` 設成 `""` 可模擬辨識不到語音 |
| `FakeLLM` | 回「你問的是：…。這是測試伺服器的假回答。」 |
| `FakeTTS` | 固定 16000 Hz；一個字一個柔和的五聲音階音，長度約 0.12 秒／字（0.8–6 秒），音量很小 |

### OpenAI 相容 HTTP API（明示的外部引擎設定）

把 `type` 改成 `openai_compat`，在子區塊填 `base_url` 與 `model`。**金鑰只從環境變數讀**（`api_key_env` 填的是變數**名稱**，
貼成金鑰本身會被拒絕）；環境變數沒設就不帶 `Authorization` 標頭（給不需要金鑰的本機服務用）。

```json
"llm": {
  "type": "openai_compat",
  "openai_compat": {
    "base_url": "https://ai.example.com/v1",
    "model": "your-llm-model",
    "api_key_env": "ASK_LLM_API_KEY",
    "max_tokens": 200, "temperature": 0.7, "timeout_s": 10
  }
}
```

```sh
export ASK_STT_API_KEY=...   # 值由你自己提供；不要寫進設定檔、程式或版控
export ASK_LLM_API_KEY=...
export ASK_TTS_API_KEY=...
python3 -m mod_ask_server --config config.json
```

| 引擎 | 請求 | 備註 |
|---|---|---|
| STT | `POST {base_url}/audio/transcriptions`，`multipart/form-data`：`file`（`audio.wav`）、`model`、`response_format=json`、`language`（有設才送）、`extra_fields` | 回應取 `text` |
| LLM | `POST {base_url}/chat/completions`，JSON：`model`、`messages`（system＋user）、`max_tokens`、`temperature`、`stream:false`、`extra_body` | 取 `choices[0].message.content`，並去掉 `<think>…</think>` |
| TTS | `POST {base_url}/audio/speech`，JSON：`model`、`input`、`voice`、`response_format`（`wav` 或 `pcm`）、`extra_body` | `pcm` 會包成 WAV，標上設定的 `sample_rate`（預設 24000，不重取樣） |

安全：只接受 `http`／`https`、網址不可內嵌帳密、**不跟隨重新導向**（避免金鑰被帶到別處）、回應有大小上限、
錯誤訊息不含上游回應內容。`use_env_proxy:false` 可忽略系統的代理設定。範例網址只用 `https://ai.example.com`。

### 自訂引擎

```json
"stt": { "type": "custom", "custom": { "factory": "my_engines:make_stt", "any_param": 1 } }
```

`factory` 是 `模組:函式`，會收到該區塊的 dict 並回傳實作介面的物件（模組要在 `PYTHONPATH` 上；設定檔由你控制，視同可信程式碼）。

## 兒童模式（伺服器端負責）

流程（SERVER_API §3.3：**被過濾的問題照樣回 200＋安全回覆的語音**，不用錯誤碼）：

```
錄音 → STT → 空？→ 200＋「我沒聽清楚，再說一次好嗎？」
            → 偵測到個資？→ 200＋提醒不要說出個資（不呼叫 LLM）
            → 命中輸入規則？→ 200＋安全回覆（不呼叫 LLM）
            → LLM（帶系統提示詞）→ 命中輸出規則？→ 丟掉回答，200＋安全回覆
            → 整理回答（最多 3 句、150 字、去掉 Markdown 與 emoji）→ TTS
```

- **系統提示詞**（`child_mode.py` 的 `DEFAULT_SYSTEM_PROMPT`，繁體中文／臺灣用語；可在規則檔用 `system_prompt` 覆寫）：
  對象 4–10 歲、最多 3 句、簡單用語、不教危險操作、不詢問也不記住姓名／學校／地址／電話、不適合的話題溫和轉向「問爸爸媽媽或老師」。
  每個問題**獨立處理**，伺服器不保存對話歷史。
- **關鍵字規則**放在 JSON 規則檔（`child_rules.example.json`，複製成 `child_rules.json` 再改）：
  `input_rules` 套用在 STT 文字、`output_rules` 套用在 LLM 回答；每條規則有 `id`、`keywords`、選用的 `reply`。
  比對前先做全形轉半形、轉小寫、去掉空白與標點；中文關鍵字是子字串，純英數關鍵字要整個單字吻合。
  由上往下比對、第一個命中的生效，所以「傷害自己」「求助」這類需要關心的主題排在前面，並有自訂回覆。
  範例檔裡的 113 是臺灣的保護專線，其他地區請改成當地的求助管道。
  沒設定 `rules_file` 時依序找 `child_rules.json`、`child_rules.example.json`；指定了卻找不到會直接報錯。
- **個資偵測**（樣式比對，會有誤判與漏判）：電話（8 位以上數字、口述的「零九一二…」）、email、地址（路街巷弄號、縣市區…）。
  命中時回覆提醒小朋友不要說出個資，**不呼叫 LLM**（個資不會送到外部引擎），紀錄中以 `[電話]`／`[email]`／`[地址]` 遮蔽。
  （錄音本身仍會先送給 STT；若 STT 是外部服務，請自行評估。）
- **額度**：每台裝置每分鐘／每日次數上限，超過回 **429 `rate_limited`＋`Retry-After`**。**允許使用時段**（例如 `07:00`–`20:30`，
  `[起, 迄)`，可跨午夜）以 `utc_offset_minutes` 算當地時間，時段外同樣回 429。計數存在記憶體，重啟歸零。
  裝置 ID 缺少或格式不對的請求共用一個 `unknown` 額度。
- **STT 為空**：預設回 200＋「我沒聽清楚，再說一次好嗎？」的語音；`child_mode.empty_stt` 設成 `error` 則回 422 `no_speech`。

## 隱私與提問紀錄

- **不存錄音**：錄音只在記憶體中處理，回應後即丟棄。
- 提問紀錄（`qa_log`，JSON Lines，預設 `./data/qa_log.jsonl`，`data/` 已列入 `.gitignore`）**只記**：
  時間（UTC ISO 8601）、裝置 ID、辨識文字（個資已遮蔽）、回答文字、是否被過濾、延遲毫秒。
  單行範例：`{"ts":"2026-11-15T04:21:13Z","device_id":"0123456789abcdef","question":"…","answer":"…","filtered":false,"latency_ms":412}`
- 保留天數 `retention_days`（預設 30）：**啟動時與之後每天**清掉過期的行；`qa_log.enabled:false` 可整個關掉（不寫、不建檔）。
- 檔案權限 `0600`、資料夾 `0700`；單一程序使用，不要讓多個伺服器程序共用同一個紀錄檔。
- 外部 STT／LLM／TTS 服務各有自己的資料政策，請自行確認。伺服器日誌（stderr）只記方法、路徑、狀態碼、耗時與請求 ID，不記內容。

## 授權（選用的 token 檢查）

設定檔放 token 的 **SHA-256 雜湊**（不放明文）。清單為空＝不檢查；有清單時，沒帶或錯的 `Authorization: Bearer …` 回 **401**
（`/v1/health` 預設也要帶，`auth.health_requires_token:false` 可放行；這樣裝置開機時就能發現 token 設錯）。

```sh
# 產生 token（顯示一次，貼進韌體的 secrets.h），並把它的雜湊貼進 config.json 的 auth.token_sha256
TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
echo "裝置 token（只顯示這一次）: $TOKEN"
printf '%s' "$TOKEN" | python3 -m mod_ask_server.hash_token     # 從 stdin 讀，只印雜湊、不印明文
```

直接在終端機執行 `python3 -m mod_ask_server.hash_token`（stdin 是 TTY）會改用不回顯的方式詢問。
雜湊比對用 `hmac.compare_digest`。

## 請求驗證與錯誤碼

驗證順序（先便宜的、先不讀本文）：路由（404／405）→ 授權（401）→ 429 預檢（時段、額度）→ `Content-Type`（415）→
`Content-Length`（411／400／413）→ 讀本文 → WAV 格式與長度（400／413／400）→ 429 正式計數 → 503（太忙）→ 問答（502／504）。

| HTTP | `code` | 時機 |
|---|---|---|
| 400 | `bad_audio` | 不是 WAV、不是 PCM16／單聲道／16000 Hz、本文比 `Content-Length` 短 |
| 400 | `too_short` | 短於 0.3 秒（4800 個樣本） |
| 401 | `unauthorized` | token 缺少或錯誤（帶 `WWW-Authenticate: Bearer`） |
| 404 | `not_found` | 路徑錯 |
| 413 | `too_long` | 超過 `max_seconds`（15 秒＝480,044 B）；`Content-Length` 過大時不讀本文就回 |
| 415 | `unsupported_media_type` | `Content-Type` 不是 `audio/wav`（大小寫與參數不拘） |
| 422 | `no_speech` | 只有 `child_mode.empty_stt:"error"` 時 |
| 429 | `rate_limited` | 超過每分鐘／每日額度，或不在允許使用時段；帶 `Retry-After` 秒數 |
| 502 | `upstream_failed` | STT／LLM／TTS 失敗，或 TTS 回了裝置播不了的格式／取樣率 |
| 503 | `unavailable` | 同時處理數已滿（`max_concurrent`），帶 `Retry-After` |
| 504 | `upstream_timeout` | 引擎逾時或整個問答超過 `hard_timeout_s` |
| 500 | `internal` | 伺服器自己出錯 |

**請求一定要有 `Content-Length`**（SERVER_API §3.1：裝置不用 chunked 上傳）：沒帶或用 `Transfer-Encoding: chunked`
上傳會回 **411 `length_required`**。`Content-Length` 不是數字回 400 `bad_request`。
所有錯誤都是 `{"error": {"code": …, "message": …}}`，`Content-Type: application/json`，並帶 `X-Request-Id`。
`Accept` 標頭不檢查。每個回應都是 `Connection: close`。

## 回應

200 時：`Content-Type: audio/wav`、`Content-Length`（不用 chunked）、`X-Request-Id`、
`X-Answer-Text`（回答文字，UTF-8 再百分比編碼，**解碼後 ≤ 200 B**，超過在 UTF-8 字元邊界截斷；語音仍是完整回答）、
以及選用的 `X-Display-Bitmap`。回應的 WAV 一律重新包成標準 44 B 標頭（長度欄位正確、沒有多餘 chunk）。

### X-Display-Bitmap（選用，需要 Pillow）

128×32、1 bpp、逐列、每列 16 B、每個位元組最高位元在最左邊、1＝亮；共 512 B，標準 base64（684 字元）。
打包函式 `display.pack_bitmap()` 是純 Python；**只有「畫字」需要 Pillow 與一個含中文的字型檔**（TTF／OTF／TTC，請確認字型授權）：

```sh
python3 -m pip install Pillow                      # 在自己的虛擬環境裡裝；不裝也能跑
# config.json："display": {"font_path": "/path/to/your-cjk-font.ttc", "font_size": 16}
python3 -m mod_ask_server.display --font /path/to/your-cjk-font.ttc "你好，我是小問"   # 用 ASCII 預覽
```

16 px 字型約能放 2 列、每列 8 個全形字，放不下的部分以「…」結尾；`font_size` 調小可多放幾個字。
沒裝 Pillow、沒設 `font_path` 或字型載入失敗，都只是不送這個標頭（啟動時會記一行警告），不影響問答。

## 部署：放在 HTTPS 反向代理後面

伺服器預設只綁 `127.0.0.1`。要給裝置連，請讓反向代理負責 HTTPS，伺服器維持綁本機；
若自行改 `server.host` 為非本機位址，啟動時會警告，且**務必同時設定 token**。nginx 範例（`ai.example.com` 是佔位網域）：

```nginx
server {
    listen 443 ssl;
    server_name ai.example.com;
    # ssl_certificate / ssl_certificate_key：自行設定

    location /ask-api/ {
        client_max_body_size 1m;            # 錄音最大約 480 KB
        proxy_read_timeout 20s;
        proxy_pass http://127.0.0.1:8787/;  # 結尾的 / 會去掉 /ask-api 前綴
    }
}
```

裝置的 `BASE` 就是 `https://ai.example.com/ask-api`，對應 SERVER_API §6：

```sh
curl -s https://ai.example.com/ask-api/v1/health

curl -s -X POST https://ai.example.com/ask-api/v1/ask \
  -H 'Content-Type: audio/wav' -H 'Accept: audio/wav' \
  -H 'X-Device-Id: 0123456789abcdef' -H 'X-Fw-Version: 0.1.0' \
  --data-binary @question.wav -D headers.txt -o answer.wav
```

有設 token 時再加 `-H "Authorization: Bearer $TOKEN"`。若代理沒有去掉前綴，把 `server.base_path` 設成 `/ask-api`。

## 與 SERVER_API.md 的對照與補充

完全依規格：端點、標頭、錯誤碼、JSON 格式、`X-Display-Bitmap`、`X-Answer-Text`、health 內容。規格沒定義、本實作另外決定的部分：

- `405 method_not_allowed`（帶 `Allow`）、`411 length_required`、`400 bad_request`（`Content-Length` 格式錯）、
  以及 `http.server` 自己產生的協議層錯誤（414／431／505…），一樣用 JSON 錯誤格式。
- `503 unavailable` 另外用在「同時處理數已滿」（規格只寫「維護中」）。
- `/v1/health` 在有設 token 時預設也要帶 token（規格只說「有設定才帶」）；可用 `auth.health_requires_token` 關掉。
- `X-Device-Id` 缺少或格式不對不拒絕，歸到共用的 `unknown` 額度。`Accept` 不檢查。
- 不做 chunked 回應；規格建議的「收到請求到第一個音訊位元組 ≤ 4 s」在假引擎下遠低於此，用外部引擎時取決於上游。

## 測試

```sh
cd server
python3 -m unittest discover -s tests -v
```

只需要標準函式庫。涵蓋：WAV 解析與驗證、HTTP 端到端（在 `127.0.0.1` 隨機埠起伺服器，測完關閉）、錯誤碼、兒童過濾與個資遮蔽、
`X-Answer-Text` 編碼與截斷、點陣打包、紀錄保留期、額度與時段、TTS 取樣率、OpenAI 相容引擎的請求格式
（本機假上游＋`unittest.mock`，完全不連外網）。沒有 Pillow 時，畫字相關的案例會被略過（skip）而不是失敗。

## 授權

MIT。
