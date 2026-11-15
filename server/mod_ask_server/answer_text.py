# SPDX-License-Identifier: MIT
"""X-Answer-Text 標頭：UTF-8 → 百分比編碼（RFC 3986），解碼後 ≤ 200 B（SERVER_API §3.2）。"""
from __future__ import annotations

from urllib.parse import quote

MAX_ANSWER_BYTES = 200


def truncate_utf8(text: str, max_bytes: int = MAX_ANSWER_BYTES) -> str:
    """在 UTF-8 字元邊界截斷，使編碼後不超過 max_bytes。

    不會切到多位元組字元的中間（中文 3 B、emoji 4 B）。
    孤立的代理碼位（例如 LLM 回傳壞掉的 \\ud800）無法編碼成 UTF-8，會被換成 "?"。
    """
    raw = text.encode("utf-8", "replace")
    if len(raw) <= max_bytes:
        return raw.decode("utf-8")
    cut = max_bytes
    # 往回退到不是 continuation byte（10xxxxxx）的位置，就是字元的開頭
    while cut > 0 and (raw[cut] & 0xC0) == 0x80:
        cut -= 1
    return raw[:cut].decode("utf-8")


def encode_answer_text(text: str, max_bytes: int = MAX_ANSWER_BYTES) -> str:
    """回傳可直接放進 HTTP 標頭的值（純 ASCII；換行等控制字元也會被編碼）。"""
    return quote(truncate_utf8(text, max_bytes).encode("utf-8"), safe="")
