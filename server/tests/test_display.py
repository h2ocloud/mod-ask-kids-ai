# SPDX-License-Identifier: MIT
"""X-Display-Bitmap：打包函式（純 Python，不需要 Pillow）與選用的畫字（沒有 Pillow 就略過）。"""
import base64
import unittest
from unittest import mock

import _helpers  # noqa: F401
from mod_ask_server import display
from mod_ask_server.config import DisplayCfg
from mod_ask_server.display import (BITMAP_BYTES, HEIGHT, WIDTH, bitmap_header_value,
                                    pack_bitmap)


def blank():
    return [[0] * WIDTH for _ in range(HEIGHT)]


class PackBitmapTests(unittest.TestCase):
    def test_size_is_512_bytes(self):
        self.assertEqual(BITMAP_BYTES, 512)
        self.assertEqual(len(pack_bitmap(blank())), 512)
        self.assertEqual(pack_bitmap(blank()), bytes(512))

    def test_all_on(self):
        rows = [[1] * WIDTH for _ in range(HEIGHT)]
        self.assertEqual(pack_bitmap(rows), b"\xff" * 512)

    def test_msb_is_leftmost_pixel(self):
        for x, expected_byte, expected_val in ((0, 0, 0x80), (1, 0, 0x40), (7, 0, 0x01),
                                               (8, 1, 0x80), (15, 1, 0x01), (127, 15, 0x01)):
            rows = blank()
            rows[0][x] = 1
            packed = pack_bitmap(rows)
            self.assertEqual(packed[expected_byte], expected_val, "x=%d" % x)
            self.assertEqual(sum(packed), expected_val, "x=%d：只該有一個位元亮" % x)

    def test_rows_are_row_major_16_bytes_each(self):
        for y in (0, 1, 15, 31):
            rows = blank()
            rows[y][0] = 1
            packed = pack_bitmap(rows)
            self.assertEqual(packed[y * 16], 0x80, "y=%d" % y)
            self.assertEqual(sum(packed), 0x80)
        rows = blank()
        rows[31][127] = 1
        self.assertEqual(pack_bitmap(rows)[511], 0x01)  # 右下角＝最後一個位元組的最低位元

    def test_alternating_pattern_and_truthy_values(self):
        rows = blank()
        rows[3] = [1, 0] * 64
        self.assertEqual(pack_bitmap(rows)[3 * 16:4 * 16], b"\xaa" * 16)
        rows[3] = [True, False, "x", None, 5, 0, 0.5, ""] * 16  # 真值＝亮
        self.assertEqual(pack_bitmap(rows)[3 * 16], 0b10101010)

    def test_accepts_tuples(self):
        rows = tuple(tuple([0] * WIDTH) for _ in range(HEIGHT))
        self.assertEqual(len(pack_bitmap(rows)), 512)

    def test_rejects_wrong_dimensions(self):
        with self.assertRaises(ValueError):
            pack_bitmap([[0] * WIDTH] * (HEIGHT - 1))
        with self.assertRaises(ValueError):
            pack_bitmap([[0] * WIDTH] * (HEIGHT + 1))
        bad = blank()
        bad[5] = [0] * (WIDTH - 1)
        with self.assertRaises(ValueError):
            pack_bitmap(bad)

    def test_header_value_is_standard_base64_684_chars(self):
        rows = blank()
        rows[0][0] = 1
        v = bitmap_header_value(rows)
        self.assertEqual(len(v), 684)
        self.assertTrue(v.endswith("="))        # 512 = 3*170 + 2 → 一個 = 補位
        self.assertFalse(v.endswith("=="))
        self.assertRegex(v, r"^[A-Za-z0-9+/]+=$")
        raw = base64.b64decode(v, validate=True)
        self.assertEqual(raw, pack_bitmap(rows))
        self.assertEqual(raw[0], 0x80)


class RendererSetupTests(unittest.TestCase):
    """不需要 Pillow：沒設字型、沒裝 Pillow、字型壞掉時都不送標頭，也不丟例外。"""

    def test_no_font_path_means_no_renderer(self):
        self.assertIsNone(display.make_renderer(DisplayCfg()))

    def test_font_set_but_pillow_missing(self):
        with mock.patch.object(display, "pillow_available", return_value=False):
            self.assertIsNone(display.make_renderer(DisplayCfg(font_path="some-font.ttf")))

    @unittest.skipUnless(display.pillow_available(), "需要 Pillow")
    def test_missing_font_file_is_not_fatal(self):
        self.assertIsNone(display.make_renderer(DisplayCfg(font_path="no-such-font-file.ttf")))

    def test_render_failure_returns_none(self):
        class Boom:
            def getlength(self, s):
                raise RuntimeError("boom")
        r = display.DisplayRenderer(Boom(), 16)
        with self.assertLogs("mod_ask.display", level="ERROR"):
            self.assertIsNone(r.render("你好"))


def _default_font(size):
    from PIL import ImageFont
    try:
        return ImageFont.load_default(size=size)  # Pillow ≥ 10.1：內建 FreeType 字型（只含拉丁字母）
    except TypeError:
        return None


@unittest.skipUnless(display.pillow_available(), "需要 Pillow（選用相依）")
class PillowRenderTests(unittest.TestCase):
    def setUp(self):
        self.font = _default_font(14)
        if self.font is None:
            self.skipTest("Pillow 太舊，沒有可縮放的內建字型")

    def test_render_shape_and_pixels(self):
        rows = display.render_text_bitmap("Hello", self.font, 14)
        self.assertEqual(len(rows), HEIGHT)
        self.assertTrue(all(len(r) == WIDTH for r in rows))
        self.assertTrue(all(v in (0, 1) for r in rows for v in r))
        lit = sum(map(sum, rows))
        self.assertGreater(lit, 20)
        self.assertLess(lit, WIDTH * HEIGHT // 2)

    def test_text_is_centered_horizontally(self):
        rows = display.render_text_bitmap("HI", self.font, 14)
        cols = [x for x in range(WIDTH) if any(r[x] for r in rows)]
        self.assertLess(abs((min(cols) + max(cols)) / 2 - WIDTH / 2), 6)

    def test_long_text_wraps_and_is_truncated_with_ellipsis(self):
        long = "The quick brown fox jumps over the lazy dog. " * 10
        rows = display.render_text_bitmap(long, self.font, 14)
        self.assertEqual(len(pack_bitmap(rows)), 512)
        # 14 px 行高在 32 px 只放得下 2 行；最後一行有東西，且不會畫出邊界
        self.assertTrue(any(rows[HEIGHT - 3]) or any(rows[HEIGHT - 4]) or any(rows[HEIGHT - 5]))

    def test_empty_text_is_blank(self):
        rows = display.render_text_bitmap("", self.font, 14)
        self.assertEqual(sum(map(sum, rows)), 0)

    def test_renderer_header_is_valid(self):
        v = display.DisplayRenderer(self.font, 14).render("Hello")
        self.assertEqual(len(v), 684)
        self.assertEqual(len(base64.b64decode(v, validate=True)), 512)


if __name__ == "__main__":
    unittest.main()
