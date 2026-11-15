# SPDX-License-Identifier: MIT
"""MOD-ASK 最小參考伺服器（協議 v1，見 docs/SERVER_API.md）。

只用 Python 標準函式庫；Pillow 為選用（產生 X-Display-Bitmap 才需要）。
"""

__version__ = "0.1.0"

# 協議版本字串（SERVER_API §2：裝置只接受前綴 "mod-ask/1"）
API_VERSION = "mod-ask/1"

# v1 固定取樣率（上傳錄音）
SAMPLE_RATE = 16000
