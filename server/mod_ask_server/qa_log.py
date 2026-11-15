# SPDX-License-Identifier: MIT
"""提問紀錄（JSON Lines）。

只記：時間（UTC ISO 8601）、裝置 ID、辨識文字（已遮蔽個資）、回答文字、是否被過濾、延遲毫秒。
**不存錄音。** 保留天數可設，啟動時與每天清掉過期紀錄；可整個關掉（enabled=false）。
檔案權限 0600、資料夾 0700。單一程序使用（同一個檔案不要給多個伺服器程序同時寫）。
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Callable

log = logging.getLogger("mod_ask.qalog")

_TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_MAX_TEXT = 500  # 單一欄位的字數上限，避免異常資料灌爆紀錄檔


def format_ts(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime(_TS_FORMAT)


def parse_ts(ts: str) -> float:
    """解析 format_ts 產生的時間字串（不用 fromisoformat：3.10 不認得結尾的 Z）。"""
    return datetime.strptime(ts, _TS_FORMAT).replace(tzinfo=timezone.utc).timestamp()


class QALog:
    def __init__(self, path: str | os.PathLike[str], retention_days: int = 30,
                 enabled: bool = True, clock: Callable[[], float] = time.time) -> None:
        self.path = os.fspath(path)
        self.retention_days = retention_days
        self.enabled = enabled
        self._clock = clock
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # --- 寫入 ---
    def append(self, *, device_id: str, question: str, answer: str, filtered: bool,
               latency_ms: int) -> None:
        """寫一筆。呼叫端必須先遮蔽個資。寫入失敗只記警告，不影響回應。"""
        if not self.enabled:
            return
        entry = {
            "ts": format_ts(self._clock()),
            "device_id": device_id,
            "question": question[:_MAX_TEXT],
            "answer": answer[:_MAX_TEXT],
            "filtered": bool(filtered),
            "latency_ms": int(latency_ms),
        }
        line = (json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n"
                ).encode("utf-8", "replace")
        try:
            with self._lock:
                directory = os.path.dirname(os.path.abspath(self.path))
                os.makedirs(directory, mode=0o700, exist_ok=True)
                fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
                try:
                    os.write(fd, line)
                finally:
                    os.close(fd)
        except OSError as e:
            log.warning("cannot write QA log: %s", e.strerror)

    # --- 保留期 ---
    def purge_expired(self, now: float | None = None) -> int:
        """刪掉超過保留天數的紀錄（以及無法判斷時間的壞行）。回傳刪掉的行數。"""
        if not self.enabled:
            return 0
        cutoff = (self._clock() if now is None else now) - self.retention_days * 86400
        tmp = self.path + ".tmp"
        removed = 0
        try:
            with self._lock:
                if not os.path.exists(self.path):
                    return 0
                fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with open(self.path, "rb") as src, os.fdopen(fd, "wb") as dst:
                    for raw in src:
                        if self._line_time(raw) >= cutoff:
                            dst.write(raw)
                        else:
                            removed += 1
                if removed:
                    os.replace(tmp, self.path)
                else:
                    os.unlink(tmp)
        except OSError as e:
            log.warning("cannot purge QA log: %s", e.strerror)
            return 0
        if removed:
            log.info("QA log: purged %d expired line(s)", removed)
        return removed

    @staticmethod
    def _line_time(raw: bytes) -> float:
        """一行的時間；壞行（不是 JSON、沒有時間、沒有結尾換行）回 -inf，會被清掉。"""
        try:
            if not raw.endswith(b"\n"):
                return float("-inf")
            return parse_ts(json.loads(raw)["ts"])
        except (ValueError, KeyError, TypeError):
            return float("-inf")

    def start_purge_thread(self, interval_s: float = 86400.0) -> None:
        """啟動時先清一次，之後每 interval_s 秒清一次（背景執行緒，stop() 結束它）。"""
        if not self.enabled or self._thread is not None:
            return
        self.purge_expired()
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, args=(interval_s,),
                                        name="qa-log-purge", daemon=True)
        self._thread.start()

    def _loop(self, interval_s: float) -> None:
        while not self._stop.wait(interval_s):
            self.purge_expired()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
