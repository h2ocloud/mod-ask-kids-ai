# SPDX-License-Identifier: MIT
"""產生 token 的 SHA-256 雜湊，貼進 config.json 的 auth.token_sha256。

用法（token 從 stdin 讀，不會印出明文）：

    printf '%s' "$TOKEN" | python3 -m mod_ask_server.hash_token

在終端機直接執行（stdin 是 TTY）時會用不回顯的方式詢問。
只會處理「去掉結尾換行」後的內容；內容為空會失敗。
"""
from __future__ import annotations

import getpass
import sys

from .auth import hash_token


def main(argv: list[str] | None = None) -> int:
    if sys.stdin.isatty():
        token = getpass.getpass("token（輸入時不會顯示）: ")
    else:
        token = sys.stdin.read()
    token = token.rstrip("\r\n")
    if not token:
        print("error: empty token", file=sys.stderr)
        return 1
    print(hash_token(token))
    return 0


if __name__ == "__main__":
    sys.exit(main())
