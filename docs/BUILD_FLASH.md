# 建置與燒錄

> 狀態：**只做過編譯**（arduino-cli 1.5.1、esp32 core 3.3.12、U8g2 2.36.19，macOS arm64）。燒錄與實機行為尚未驗證。

## 1. 準備（不需要 sudo）

```sh
brew install arduino-cli          # 或從 https://arduino.github.io/arduino-cli/ 下載
sh firmware/build.sh --setup      # 加 Espressif 官方 board manager、裝 esp32 core 3.3.12 與 U8g2 2.36.19
```

## 2. 設定

```sh
cp firmware/mod_ask/secrets.example.h firmware/mod_ask/secrets.h
# 用編輯器填：WIFI_SSID_1／WIFI_PASS_1（2.4 GHz）、ASK_SERVER_URL（你自己的伺服器，例如 https://ai.example.com/ask-api）
```

- `secrets.h` 已在 `.gitignore`，**不要 commit**。
- 沒有 `secrets.h` 也能編譯：裝置開機會顯示「尚未設定」且不連網。
- 伺服器協議見 `docs/SERVER_API.md`；可以先在電腦上跑 `server/` 的參考伺服器（假引擎）測流程。

## 3. 編譯

```sh
sh firmware/build.sh
```

| 項目 | 值 |
|---|---|
| FQBN | `esp32:esp32:esp32s3:FlashSize=16M,PSRAM=opi,PartitionScheme=app3M_fat9M_16MB` |
| PSRAM | **OPI**（N16R8 是 Octal PSRAM；選錯會開不起來或錄音緩衝配置失敗） |
| Flash | 16 MB，QIO 80 MHz（預設） |
| 分割表 | 16M Flash（3 MB APP×2／9.9 MB FATFS） |

編譯產物放在暫存資料夾（`$TMPDIR/mod_ask_build`），不要放進 repo；**有 `secrets.h` 時 binary 內含 Wi‑Fi 帳密**，不要外傳。

## 4. 燒錄

1. USB 線（要能傳資料）插開發板的 **「UART」口**（官方板是 Micro-USB；USB-C 的多半是相容板）。
2. 找序列埠：拔掉 USB 跑一次 `ls /dev/cu.*`，插上再跑一次，多出來的就是。macOS 內建 CP210x／CH34x 驅動，不要裝 kext。
3. 燒錄：
   ```sh
   PORT=/dev/cu.usbserial-XXXX sh firmware/build.sh --upload
   ```
4. 停在 `Connecting...`：按住 **BOOT**、看到 `Writing at 0x…` 再放開；燒完沒自動重開就按一下 **RST**。
5. 看序列埠：
   ```sh
   arduino-cli monitor -p /dev/cu.usbserial-XXXX -c baudrate=115200
   ```
   應該看到 `[BOOT] mod-ask 0.1.0  PSRAM=…`（約 8 MB）、裝置 ID、`[NET] health -> 200 (OK)`，按按鈕時有 `[STATE] Idle --ButtonDown--> Listening`。

## 5. 主機端測試（不需要硬體）

```sh
sh firmware/test/run_tests.sh               # 韌體純邏輯：clang + ASan/UBSan
cd server && python3 -m unittest discover -s tests -v   # 參考伺服器
```

## 6. 到貨後第一次上電檢查清單（尚未做）

| # | 檢查 | 預期 | 不對時 |
|---|---|---|---|
| 1 | 序列埠 PSRAM 大小 | 約 8,388,608 B | FQBN 的 PSRAM 不是 OPI，或板子不是 R8 |
| 2 | OLED | 顯示「尚未設定」或「連線中」，字是正的 | 上下顛倒：`config.h` 改 `OLED_ROTATE_180`；全黑：查 SDA/SCL、位址 0x3D |
| 3 | 按住說話時音量條 | 說話時跳動、安靜時 0–2 格 | 一直 0：查 INMP441 接線、L/R 是否接 GND；一直滿：`MIC_SHIFT` 加 1 |
| 4 | 開機嗶聲 | 高音短嗶 | 無聲：查功放 Vin 5V、SD 腳（見 PINMAP §3） |
| 5 | 問一題 | 2–4 s 內開始播答案 | 看序列埠 `[NET]` 那幾行的狀態碼與毫秒數 |
| 6 | 大聲播放時 | 不重開機、Wi‑Fi 不斷 | 加大功放旁的電解電容、換 1 A 以上的 USB 電源、降音量上限 |
