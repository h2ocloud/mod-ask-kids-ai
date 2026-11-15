# SPDX-License-Identifier: MIT
"""每台裝置的額度（記憶體計數，重啟就歸零）與「允許使用時段」。

超過額度或在時段外：丟 ApiError(429, "rate_limited")，帶 Retry-After 秒數（SERVER_API §3.3）。
每日額度與使用時段都用設定的固定 UTC 偏移（預設 UTC+8）算當地時間；不處理日光節約時間。
"""
from __future__ import annotations

import math
import threading
from collections import deque
from datetime import datetime, timedelta, timezone

from .config import QuotaCfg
from .errors import ApiError

_DAY = 86400


class _Dev:
    __slots__ = ("minute", "day", "day_count")

    def __init__(self) -> None:
        self.minute: deque[float] = deque()  # 最近 60 秒內的請求時間
        self.day = ""                        # 當地日期（YYYY-MM-DD）
        self.day_count = 0


class Quota:
    def __init__(self, cfg: QuotaCfg, max_devices: int = 10000) -> None:
        self.cfg = cfg
        self.max_devices = max_devices
        self._tz = timezone(timedelta(minutes=cfg.utc_offset_minutes))
        self._lock = threading.Lock()
        self._devs: dict[str, _Dev] = {}

    # --- 對外 ---
    def check(self, device_id: str, now: float) -> None:
        """只檢查、不計數（在讀取上傳內容之前先擋掉，省頻寬）。"""
        with self._lock:
            self._consume(device_id, now, commit=False)

    def acquire(self, device_id: str, now: float) -> None:
        """檢查並計一次（原子操作）。通過驗證、真的要處理這次問答時才呼叫。"""
        with self._lock:
            self._consume(device_id, now, commit=True)

    # --- 內部 ---
    def _local(self, now: float) -> datetime:
        return datetime.fromtimestamp(now, tz=self._tz)

    def _check_hours(self, now: float) -> None:
        c = self.cfg
        if not c.hours_enabled:
            return
        loc = self._local(now)
        minute = loc.hour * 60 + loc.minute
        if c.hours_start < c.hours_end:
            ok = c.hours_start <= minute < c.hours_end
        else:  # 跨午夜，例如 20:00–06:00
            ok = minute >= c.hours_start or minute < c.hours_end
        if ok:
            return
        sod = minute * 60 + loc.second
        wait = (c.hours_start * 60 - sod) % _DAY
        raise ApiError(429, "rate_limited", "outside allowed hours", max(1, wait))

    def _consume(self, device_id: str, now: float, *, commit: bool) -> None:
        self._check_hours(now)
        c = self.cfg
        if not c.per_minute and not c.per_day:
            return  # 兩種額度都不限：不必計數
        dev = self._devs.get(device_id)
        loc = self._local(now)
        today = loc.strftime("%Y-%m-%d")
        if dev is not None:
            while dev.minute and dev.minute[0] <= now - 60:
                dev.minute.popleft()
            if dev.day != today:
                dev.day, dev.day_count = today, 0
            if c.per_minute and len(dev.minute) >= c.per_minute:
                wait = math.ceil(dev.minute[0] + 60 - now)
                raise ApiError(429, "rate_limited", "too many requests per minute", max(1, wait))
            if c.per_day and dev.day_count >= c.per_day:
                sod = loc.hour * 3600 + loc.minute * 60 + loc.second
                raise ApiError(429, "rate_limited", "daily limit reached",
                               max(1, _DAY - sod))
        if not commit:
            return
        if dev is None:
            self._evict_if_full(now, today)
            dev = self._devs[device_id] = _Dev()
            dev.day = today
        dev.minute.append(now)
        dev.day_count += 1

    def _evict_if_full(self, now: float, today: str) -> None:
        """限制記憶體：先清掉沒有近期活動的裝置，還是太多就丟最舊的。"""
        if len(self._devs) < self.max_devices:
            return
        for key in [k for k, d in self._devs.items()
                    if d.day != today and (not d.minute or d.minute[-1] <= now - 60)]:
            del self._devs[key]
        while len(self._devs) >= self.max_devices:
            del self._devs[next(iter(self._devs))]
