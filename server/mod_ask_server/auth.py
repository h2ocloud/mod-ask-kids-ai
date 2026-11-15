# SPDX-License-Identifier: MIT
"""選用的 Bearer token 檢查：設定檔只存 token 的 SHA-256 雜湊，不存明文。

清單為空 → 不檢查。有清單 → 沒帶、格式不對或雜湊不在清單內都算失敗（401）。
比對用 hmac.compare_digest，且每次都走完整份清單，避免從回應時間猜雜湊。
"""
from __future__ import annotations

import hashlib
import hmac
from typing import Iterable


def hash_token(token: str) -> str:
    """token（UTF-8）→ 小寫十六進位 SHA-256。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class TokenAuth:
    def __init__(self, hashes: Iterable[str] = ()) -> None:
        self._hashes = tuple(h.lower() for h in hashes)

    @property
    def enabled(self) -> bool:
        return bool(self._hashes)

    def verify(self, authorization: str | None) -> bool:
        """authorization 是整個 Authorization 標頭值（例如 'Bearer xxxx'）。"""
        if not self.enabled:
            return True
        if not authorization:
            return False
        scheme, _, token = authorization.strip().partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            return False
        digest = hash_token(token.strip())
        ok = False
        for h in self._hashes:  # 不要提早 break
            ok |= hmac.compare_digest(digest, h)
        return ok
