# SPDX-License-Identifier: MIT
"""共用錯誤型別。

- ApiError：要原樣回給裝置的 HTTP 錯誤（SERVER_API §3.3 的 JSON 格式）。
- EngineError／EngineTimeout：STT／LLM／TTS 引擎失敗，會被轉成 502／504。
- ConfigError：設定檔有誤，啟動時就失敗（不要帶著壞設定跑）。
"""
from __future__ import annotations

import json


class ApiError(Exception):
    """對應 SERVER_API §3.3：{"error": {"code": ..., "message": ...}}。"""

    def __init__(self, status: int, code: str, message: str,
                 retry_after: int | None = None,
                 headers: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.retry_after = retry_after       # 429／503 要帶 Retry-After（秒）
        self.headers = dict(headers or {})   # 其他要附上的回應標頭（WWW-Authenticate、Allow）

    def to_json_bytes(self) -> bytes:
        body = {"error": {"code": self.code, "message": self.message}}
        # ensure_ascii：錯誤訊息一律英文，輸出純 ASCII 最保險
        return json.dumps(body, ensure_ascii=True).encode("ascii")


class EngineError(Exception):
    """引擎回報失敗（對應 502 upstream_failed）。訊息不得包含使用者內容或金鑰。"""


class EngineTimeout(EngineError):
    """引擎逾時（對應 504 upstream_timeout）。"""


class ConfigError(Exception):
    """設定檔或規則檔格式錯誤。訊息只寫鍵名與原因，不回顯值（避免洩漏金鑰）。"""
