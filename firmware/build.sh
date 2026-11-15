#!/bin/sh
# 編譯 MOD-ASK 韌體（arduino-cli，使用者層安裝，不需要 sudo）
#   sh firmware/build.sh            只編譯
#   sh firmware/build.sh --setup    先安裝 esp32 core 與 U8g2（版本見下方）
#   PORT=/dev/cu.usbserial-XXXX sh firmware/build.sh --upload   編譯並燒錄
# 編譯產物放在 $TMPDIR（不進 repo；有 secrets.h 時 binary 內含 Wi-Fi 帳密，不要外傳）。
set -eu
cd "$(dirname "$0")"

FQBN="esp32:esp32:esp32s3:FlashSize=16M,PSRAM=opi,PartitionScheme=app3M_fat9M_16MB"
CORE_VER="3.3.12"
U8G2_VER="2.36.19"
BUILD="${BUILD_PATH:-${TMPDIR:-/tmp}/mod_ask_build}"

if [ "${1:-}" = "--setup" ]; then
  arduino-cli config init --overwrite >/dev/null 2>&1 || true
  arduino-cli config add board_manager.additional_urls https://espressif.github.io/arduino-esp32/package_esp32_index.json
  arduino-cli core update-index
  arduino-cli core install "esp32:esp32@${CORE_VER}"
  arduino-cli lib install "U8g2@${U8G2_VER}"
  shift
fi

echo "arduino-cli: $(arduino-cli version)"
echo "core:        $(arduino-cli core list | awk '$1=="esp32:esp32"{print $1, $2}')"
echo "U8g2:        $(arduino-cli lib list | awk '$1=="U8g2"{print $2}')"
echo "FQBN:        ${FQBN}"
if [ -f mod_ask/secrets.h ]; then echo "secrets.h:   present (binary will contain credentials)"; else echo "secrets.h:   absent (builds with empty template -> device shows 'not configured')"; fi

if [ "${1:-}" = "--upload" ]; then
  : "${PORT:?set PORT=/dev/cu.xxx}"
  arduino-cli compile --fqbn "$FQBN" --warnings all --build-path "$BUILD" --upload -p "$PORT" mod_ask
else
  arduino-cli compile --fqbn "$FQBN" --warnings all --build-path "$BUILD" mod_ask
fi
