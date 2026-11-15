# SPDX-License-Identifier: MIT
"""測試用的自訂引擎工廠（設定檔 "custom": {"factory": "_custom_engines:make_stt"}）。"""


class _Stt:
    def __init__(self, text: str) -> None:
        self.text = text

    def transcribe(self, wav, *, timeout=None):
        return self.text


def make_stt(params):
    return _Stt(params.get("text", ""))


def make_wrong(params):
    return object()  # 沒有實作介面：應該被拒絕
