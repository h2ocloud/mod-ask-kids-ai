# SPDX-License-Identifier: MIT
"""X-Answer-Text：UTF-8 百分比編碼與 ≤200 B 截斷。"""
import re
import unittest
from urllib.parse import unquote_to_bytes

import _helpers  # noqa: F401  （設定 sys.path）
from mod_ask_server.answer_text import MAX_ANSWER_BYTES, encode_answer_text, truncate_utf8


def decode(value: str) -> str:
    return unquote_to_bytes(value).decode("utf-8")  # 嚴格解碼：壞掉的 UTF-8 會直接丟例外


class AnswerTextTests(unittest.TestCase):
    def test_short_text_roundtrips(self):
        for s in ("你好", "Hello, world!", "你問的是：（測試）你好。這是測試伺服器的假回答。", "", "a b"):
            v = encode_answer_text(s)
            self.assertEqual(decode(v), s)
            self.assertTrue(v.isascii())

    def test_encoding_is_rfc3986_percent_encoding(self):
        self.assertEqual(encode_answer_text("你"), "%E4%BD%A0")
        self.assertEqual(encode_answer_text("a b"), "a%20b")          # 空格是 %20，不是 +
        self.assertEqual(encode_answer_text("AZaz09-._~"), "AZaz09-._~")  # unreserved 不編碼
        self.assertEqual(encode_answer_text("a\r\nb"), "a%0D%0Ab")      # 控制字元一定被編碼
        self.assertRegex(encode_answer_text("你好!?,"), r"^[A-Za-z0-9%._~-]+$")

    def test_exactly_200_bytes_is_kept(self):
        s = "a" * 200
        self.assertEqual(truncate_utf8(s), s)
        s = "你" * 66 + "ab"  # 66*3 + 2 = 200 B
        self.assertEqual(len(s.encode("utf-8")), 200)
        self.assertEqual(truncate_utf8(s), s)

    def test_truncates_on_character_boundary_cjk(self):
        s = "你" * 100  # 300 B
        t = truncate_utf8(s)
        self.assertEqual(t, "你" * 66)  # 198 B：不能切在字中間
        self.assertLessEqual(len(t.encode("utf-8")), MAX_ANSWER_BYTES)

    def test_truncates_on_character_boundary_every_offset(self):
        # 不管 200 B 邊界剛好落在 1/2/3/4 位元組字元的哪一個位置，解碼後都必須是合法 UTF-8
        for prefix in range(0, 8):
            s = "a" * prefix + "你好😀é" * 40
            t = truncate_utf8(s)
            raw = t.encode("utf-8")
            self.assertLessEqual(len(raw), MAX_ANSWER_BYTES, prefix)
            self.assertGreater(len(raw), MAX_ANSWER_BYTES - 4, prefix)  # 只丟掉不完整的那一個字元
            self.assertTrue(s.startswith(t), prefix)
            self.assertEqual(decode(encode_answer_text(s)), t)

    def test_emoji_not_split(self):
        s = "a" * 198 + "😀"  # 4 B 字元跨過 200 B
        self.assertEqual(truncate_utf8(s), "a" * 198)

    def test_decoded_header_is_at_most_200_bytes(self):
        for s in ("你好嗎" * 200, "a" * 1000, "😀" * 100):
            self.assertLessEqual(len(unquote_to_bytes(encode_answer_text(s))), 200)

    def test_custom_limit(self):
        self.assertEqual(truncate_utf8("你好嗎", 7), "你好")

    def test_lone_surrogate_does_not_crash(self):
        v = encode_answer_text("壞\ud800字")
        self.assertEqual(decode(v), "壞?字")

    def test_header_value_has_no_forbidden_characters(self):
        v = encode_answer_text("你好\n世界\r\n" * 30)
        self.assertIsNone(re.search(r"[\r\n\s]", v))


if __name__ == "__main__":
    unittest.main()
