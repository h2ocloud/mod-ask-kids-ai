# SPDX-License-Identifier: MIT
"""提問紀錄：欄位、遮蔽前提、保留期清除、關閉、壞行處理。"""
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path

import _helpers  # noqa: F401
from mod_ask_server.qa_log import QALog, format_ts, parse_ts

DAY = 86400
NOW = 1_800_000_000.0  # 固定時間（2027-01-15）


class QALogTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.path = self.dir / "sub" / "qa_log.jsonl"   # 子資料夾：測試自動建立

    def log_at(self, ts: float, **kw) -> QALog:
        return QALog(self.path, clock=lambda: ts, **kw)

    def add(self, ts: float, q: str = "問", **kw):
        self.log_at(ts, **kw).append(device_id="0123456789abcdef", question=q, answer="答",
                                     filtered=False, latency_ms=12)

    def lines(self) -> list[dict]:
        return [json.loads(x) for x in self.path.read_text(encoding="utf-8").splitlines()]


class AppendTests(QALogTestCase):
    def test_entry_has_exactly_the_documented_fields(self):
        self.log_at(NOW).append(device_id="0123456789abcdef", question="你好嗎", answer="很好。",
                                filtered=True, latency_ms=345)
        (entry,) = self.lines()
        self.assertEqual(set(entry), {"ts", "device_id", "question", "answer", "filtered",
                                      "latency_ms"})  # 沒有錄音、沒有 IP、沒有其他欄位
        self.assertEqual(entry["question"], "你好嗎")
        self.assertIs(entry["filtered"], True)
        self.assertEqual(entry["latency_ms"], 345)
        self.assertRegex(entry["ts"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")  # UTC ISO 8601
        self.assertEqual(parse_ts(entry["ts"]), NOW)

    def test_one_json_object_per_line_utf8_unescaped(self):
        self.add(NOW, q="第一行\n第二行")        # 換行會被 JSON 跳脫，不會破壞一行一筆
        self.add(NOW, q="中文")
        raw = self.path.read_text(encoding="utf-8")
        self.assertEqual(len(raw.splitlines()), 2)
        self.assertIn("中文", raw)                # 不是 \uXXXX
        self.assertEqual(self.lines()[0]["question"], "第一行\n第二行")

    def test_field_length_is_capped(self):
        self.add(NOW, q="甲" * 5000)
        self.assertEqual(len(self.lines()[0]["question"]), 500)

    def test_lone_surrogate_does_not_break_logging(self):
        self.add(NOW, q="壞\ud800字")
        self.assertEqual(len(self.lines()), 1)

    @unittest.skipUnless(os.name == "posix", "POSIX 權限")
    def test_permissions_are_private(self):
        self.add(NOW)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.path.parent.stat().st_mode & 0o777, 0o700)

    def test_disabled_writes_nothing(self):
        self.add(NOW, enabled=False)
        self.assertFalse(self.path.exists())
        self.assertFalse(self.path.parent.exists())
        self.assertEqual(self.log_at(NOW, enabled=False).purge_expired(), 0)

    def test_unwritable_location_does_not_raise(self):
        blocker = self.dir / "file"
        blocker.write_text("x")
        log = QALog(blocker / "qa.jsonl", clock=lambda: NOW)  # 父路徑是檔案，建不了資料夾
        with self.assertLogs("mod_ask.qalog", level="WARNING"):
            log.append(device_id="d", question="q", answer="a", filtered=False, latency_ms=1)

    def test_concurrent_appends_keep_lines_intact(self):
        log = self.log_at(NOW)

        def worker(i):
            for j in range(25):
                log.append(device_id="%016x" % i, question="問題" * 20, answer="答", filtered=False,
                           latency_ms=j)
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(len(self.lines()), 200)  # 每行都是完整 JSON


class RetentionTests(QALogTestCase):
    def test_purges_entries_older_than_retention_days(self):
        for age_days in (45, 31, 29, 1, 0):
            self.add(NOW - age_days * DAY - 5, q="age%d" % age_days)
        removed = self.log_at(NOW, retention_days=30).purge_expired()
        self.assertEqual(removed, 2)
        self.assertEqual([e["question"] for e in self.lines()], ["age29", "age1", "age0"])

    def test_boundary_exactly_at_retention_is_kept(self):
        self.add(NOW - 30 * DAY, q="edge")
        self.add(NOW - 30 * DAY - 1, q="over")
        self.log_at(NOW, retention_days=30).purge_expired()
        self.assertEqual([e["question"] for e in self.lines()], ["edge"])

    def test_retention_days_is_configurable(self):
        self.add(NOW - 8 * DAY, q="old")
        self.add(NOW - 2 * DAY, q="new")
        self.log_at(NOW, retention_days=7).purge_expired()
        self.assertEqual([e["question"] for e in self.lines()], ["new"])

    def test_purge_can_take_explicit_now(self):
        self.add(NOW, q="a")
        log = self.log_at(NOW, retention_days=30)
        self.assertEqual(log.purge_expired(now=NOW + 31 * DAY), 1)  # 31 天後
        self.assertEqual(self.path.read_text(encoding="utf-8"), "")

    def test_nothing_to_purge_leaves_file_untouched(self):
        self.add(NOW, q="a")
        before = self.path.read_bytes()
        self.assertEqual(self.log_at(NOW).purge_expired(), 0)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(Path(str(self.path) + ".tmp").exists())

    def test_missing_file_is_fine(self):
        self.assertEqual(self.log_at(NOW).purge_expired(), 0)

    def test_corrupt_and_unterminated_lines_are_dropped(self):
        self.add(NOW, q="good")
        with open(self.path, "ab") as f:
            f.write(b"not json\n")
            f.write(b'{"no_ts": 1}\n')
            f.write(b'{"ts":"yesterday"}\n')
            f.write(json.dumps({"ts": format_ts(NOW)}).encode() + b"")  # 沒有結尾換行（寫到一半）
        removed = self.log_at(NOW).purge_expired()
        self.assertEqual(removed, 4)
        self.assertEqual([e["question"] for e in self.lines()], ["good"])

    def test_purge_does_not_lose_concurrent_appends(self):
        for i in range(50):
            self.add(NOW - 40 * DAY, q="old%d" % i)
        log = self.log_at(NOW)
        stop = threading.Event()

        def writer():
            n = 0
            while not stop.is_set() and n < 200:
                log.append(device_id="d", question="new%d" % n, answer="a", filtered=False,
                           latency_ms=1)
                n += 1
        t = threading.Thread(target=writer)
        t.start()
        log.purge_expired()
        t.join()
        qs = [e["question"] for e in self.lines()]
        self.assertTrue(all(q.startswith("new") for q in qs))
        self.assertEqual(qs, ["new%d" % i for i in range(len(qs))])  # 順序完整、沒有缺漏
        self.assertEqual(len(qs), 200)

    def test_purge_thread_runs_at_start_and_stops(self):
        self.add(NOW - 40 * DAY, q="old")
        self.add(NOW, q="new")
        log = self.log_at(NOW, retention_days=30)
        log.start_purge_thread(interval_s=3600)
        try:
            self.assertEqual([e["question"] for e in self.lines()], ["new"])  # 啟動時就清了
            self.assertTrue(log._thread.is_alive())
        finally:
            thread = log._thread
            log.stop()
        self.assertFalse(thread.is_alive())
        self.assertIsNone(log._thread)

    def test_periodic_purge_fires(self):
        self.add(NOW - 40 * DAY, q="old")
        log = self.log_at(NOW, retention_days=30)
        log.start_purge_thread(interval_s=0.05)  # 啟動時已清掉 old
        try:
            self.add(NOW - 40 * DAY, q="old2")   # 之後新增的過期資料，下一輪週期應該清掉
            for _ in range(100):
                if "old2" not in self.path.read_text(encoding="utf-8"):
                    break
                threading.Event().wait(0.05)
            self.assertNotIn("old2", self.path.read_text(encoding="utf-8"))
        finally:
            log.stop()


class TimestampTests(unittest.TestCase):
    def test_format_and_parse(self):
        self.assertEqual(format_ts(0), "1970-01-01T00:00:00Z")
        self.assertEqual(parse_ts("1970-01-02T00:00:00Z"), 86400)
        self.assertEqual(parse_ts(format_ts(NOW)), NOW)


if __name__ == "__main__":
    unittest.main()
