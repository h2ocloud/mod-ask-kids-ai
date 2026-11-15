# SPDX-License-Identifier: MIT
"""額度（每分鐘、每日）與允許使用時段。"""
import unittest
from datetime import datetime, timedelta, timezone

import _helpers  # noqa: F401
from mod_ask_server.config import QuotaCfg
from mod_ask_server.errors import ApiError
from mod_ask_server.quota import Quota

TZ8 = timezone(timedelta(hours=8))
DEV = "0123456789abcdef"


def local(h: int, m: int = 0, s: int = 0, day: int = 15) -> float:
    return datetime(2026, 11, day, h, m, s, tzinfo=TZ8).timestamp()


class QuotaTests(unittest.TestCase):
    def rejected(self, q: Quota, now: float, dev: str = DEV, commit: bool = True) -> ApiError:
        with self.assertRaises(ApiError) as cm:
            (q.acquire if commit else q.check)(dev, now)
        e = cm.exception
        self.assertEqual((e.status, e.code), (429, "rate_limited"))
        self.assertIsInstance(e.retry_after, int)
        self.assertGreaterEqual(e.retry_after, 1)
        return e

    def test_per_minute_limit_and_retry_after(self):
        q = Quota(QuotaCfg(per_minute=2, per_day=0))
        t = local(12)
        q.acquire(DEV, t)
        q.acquire(DEV, t + 10)
        e = self.rejected(q, t + 20)
        self.assertEqual(e.retry_after, 40)          # 最舊那筆 60 s 後過期：t+60−(t+20)
        self.rejected(q, t + 59)
        q.acquire(DEV, t + 61)                         # 第一筆已滑出視窗

    def test_check_does_not_consume(self):
        q = Quota(QuotaCfg(per_minute=1, per_day=0))
        t = local(12)
        for _ in range(5):
            q.check(DEV, t)                            # 只檢查，不計數
        q.acquire(DEV, t)                              # 還是第一次
        self.rejected(q, t + 1, commit=False)         # 預檢也會擋
        self.rejected(q, t + 1)

    def test_devices_are_counted_separately(self):
        q = Quota(QuotaCfg(per_minute=1, per_day=0))
        t = local(12)
        q.acquire("a" * 16, t)
        q.acquire("b" * 16, t)
        self.rejected(q, t, "a" * 16)

    def test_per_day_limit_resets_at_local_midnight(self):
        q = Quota(QuotaCfg(per_minute=0, per_day=3, utc_offset_minutes=480))
        for i in range(3):
            q.acquire(DEV, local(8 + i))
        e = self.rejected(q, local(23, 30))
        self.assertEqual(e.retry_after, 30 * 60)       # 到當地午夜還有 30 分鐘
        q.acquire(DEV, local(0, 5, day=16))            # 隔天重新計（當地日期，不是 UTC 日期）
        q.acquire(DEV, local(0, 10, day=16))
        q.acquire(DEV, local(0, 20, day=16))
        self.rejected(q, local(0, 30, day=16))         # 新的一天也是 3 次

    def test_daily_uses_configured_utc_offset(self):
        q = Quota(QuotaCfg(per_minute=0, per_day=1, utc_offset_minutes=0))
        t = datetime(2026, 11, 15, 23, 0, tzinfo=timezone.utc).timestamp()
        q.acquire(DEV, t)
        e = self.rejected(q, t + 600)
        self.assertEqual(e.retry_after, 3600 - 600)

    def test_zero_means_unlimited(self):
        q = Quota(QuotaCfg(per_minute=0, per_day=0))
        for i in range(500):
            q.acquire(DEV, local(12) + i * 0.01)
        self.assertEqual(len(q._devs), 0)              # 不限額度就不必記錄

    def test_allowed_hours(self):
        q = Quota(QuotaCfg(per_minute=0, per_day=0, hours_enabled=True,
                           hours_start=7 * 60, hours_end=20 * 60 + 30))
        q.check(DEV, local(7, 0))                      # 起點含
        q.check(DEV, local(12))
        q.check(DEV, local(20, 29, 59))
        e = self.rejected(q, local(20, 30), commit=False)   # 終點不含
        self.assertEqual(e.retry_after, (10 * 60 + 30) * 60)  # 到隔天 07:00
        e = self.rejected(q, local(23, 0))
        self.assertEqual(e.retry_after, 8 * 3600)
        e = self.rejected(q, local(3, 0))
        self.assertEqual(e.retry_after, 4 * 3600)
        e = self.rejected(q, local(6, 59, 59))
        self.assertEqual(e.retry_after, 1)

    def test_allowed_hours_wrapping_midnight(self):
        q = Quota(QuotaCfg(per_minute=0, per_day=0, hours_enabled=True,
                           hours_start=20 * 60, hours_end=6 * 60))
        q.check(DEV, local(21))
        q.check(DEV, local(2))
        e = self.rejected(q, local(12), commit=False)
        self.assertEqual(e.retry_after, 8 * 3600)

    def test_hours_disabled_by_default(self):
        Quota(QuotaCfg()).check(DEV, local(3))

    def test_outside_hours_does_not_consume_quota(self):
        q = Quota(QuotaCfg(per_minute=1, per_day=0, hours_enabled=True,
                           hours_start=7 * 60, hours_end=20 * 60))
        self.rejected(q, local(23))
        q.acquire(DEV, local(8))                       # 時段外的嘗試沒有佔掉額度

    def test_memory_is_bounded(self):
        q = Quota(QuotaCfg(per_minute=5, per_day=0), max_devices=50)
        t = local(12)
        for i in range(500):
            q.acquire("%016x" % i, t)
        self.assertLessEqual(len(q._devs), 50)


if __name__ == "__main__":
    unittest.main()
