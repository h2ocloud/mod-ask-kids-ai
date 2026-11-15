# SPDX-License-Identifier: MIT
"""X-Display-Bitmap：把回答文字畫成 128×32、1 bpp 的點陣（SERVER_API §3.2）。

格式：逐列、每列 16 B、每個位元組最高位元在最左邊、1＝亮；共 512 B，標準 base64（684 字元）。
打包函式 pack_bitmap 是純 Python，不需要 Pillow。**只有「畫字」需要 Pillow 與字型檔**；
沒裝 Pillow 或沒設定字型就不送這個標頭（伺服器照常運作）。

預覽：python3 -m mod_ask_server.display --font 字型檔 "你好，我是小問"
"""
from __future__ import annotations

import argparse
import base64
import logging
import sys
from typing import Any, Sequence

from .config import DisplayCfg

log = logging.getLogger("mod_ask.display")

WIDTH = 128
HEIGHT = 32
BITMAP_BYTES = WIDTH // 8 * HEIGHT  # 512

Bitmap = Sequence[Sequence[int]]  # HEIGHT 列 × WIDTH 欄，真值＝亮


def pack_bitmap(rows: Bitmap) -> bytes:
    """32 列 × 128 欄的 0/1 點陣 → 512 B（逐列、每個位元組 MSB 在左）。"""
    if len(rows) != HEIGHT:
        raise ValueError("bitmap must have %d rows, got %d" % (HEIGHT, len(rows)))
    out = bytearray()
    for y, row in enumerate(rows):
        if len(row) != WIDTH:
            raise ValueError("row %d must have %d columns, got %d" % (y, WIDTH, len(row)))
        for x in range(0, WIDTH, 8):
            byte = 0
            for i in range(8):
                byte = (byte << 1) | (1 if row[x + i] else 0)
            out.append(byte)
    return bytes(out)


def bitmap_header_value(rows: Bitmap) -> str:
    """打包後轉標準 base64（含 = 補位）；512 B → 684 字元。"""
    return base64.b64encode(pack_bitmap(rows)).decode("ascii")


def pillow_available() -> bool:
    try:
        import PIL  # noqa: F401
        return True
    except ImportError:
        return False


def load_font(path: str, size: int, index: int = 0) -> Any:
    """載入 TrueType／OpenType（含 .ttc）字型。需要 Pillow。"""
    from PIL import ImageFont
    return ImageFont.truetype(path, size, index=index)


def render_text_bitmap(text: str, font: Any, line_height: int,
                       threshold: int = 110) -> list[list[int]]:
    """把文字排成 128×32 點陣（自動換行、置中、放不下就在最後一行加「…」）。需要 Pillow。

    font 是 PIL 的字型物件；line_height 是行高（像素），通常等於字型大小。
    """
    from PIL import Image, ImageDraw

    line_height = max(1, line_height)
    max_lines = max(1, HEIGHT // line_height)
    text = " ".join(text.split())

    def width_of(s: str) -> float:
        return font.getlength(s)

    # 逐字依像素寬度換行；行首的空白略過
    lines: list[str] = []
    cur = ""
    idx = 0
    while idx < len(text):
        ch = text[idx]
        if cur and width_of(cur + ch) > WIDTH:
            lines.append(cur)
            cur = ""
            if len(lines) == max_lines:
                break
        if ch == " " and not cur:
            idx += 1
            continue
        cur += ch
        idx += 1
    if cur:
        lines.append(cur)
    if idx < len(text) and lines:  # 還有字放不下：最後一行結尾換成 …
        last = lines[-1]
        while last and width_of(last + "…") > WIDTH:
            last = last[:-1]
        lines[-1] = last + "…"

    img = Image.new("L", (WIDTH, HEIGHT), 0)
    draw = ImageDraw.Draw(img)
    top = (HEIGHT - len(lines) * line_height) // 2
    for i, ln in enumerate(lines):
        x = max(0, int((WIDTH - width_of(ln)) // 2))
        draw.text((x, top + i * line_height), ln, font=font, fill=255)
    raw = img.tobytes()
    return [[1 if raw[y * WIDTH + x] >= threshold else 0 for x in range(WIDTH)]
            for y in range(HEIGHT)]


class DisplayRenderer:
    """把回答文字轉成 X-Display-Bitmap 標頭值。"""

    def __init__(self, font: Any, font_size: int) -> None:
        self._font = font
        self._size = font_size

    def render(self, text: str) -> str | None:
        """失敗時回 None（畫不出來不應該讓整個問答失敗）。"""
        try:
            return bitmap_header_value(render_text_bitmap(text, self._font, self._size))
        except Exception:  # noqa: BLE001 - 任何繪圖問題都只是「這次不送標頭」
            log.exception("cannot render display bitmap")
            return None


def make_renderer(cfg: DisplayCfg, resolve=lambda p: p) -> DisplayRenderer | None:
    """依設定建立畫字器；沒設字型、沒裝 Pillow 或字型載入失敗都回 None（不送標頭）。"""
    if not cfg.font_path:
        return None
    if not pillow_available():
        log.warning("display.font_path is set but Pillow is not installed; "
                    "X-Display-Bitmap is disabled")
        return None
    try:
        font = load_font(str(resolve(cfg.font_path)), cfg.font_size, cfg.font_index)
    except Exception as e:  # noqa: BLE001
        log.warning("cannot load display font (%s); X-Display-Bitmap is disabled",
                    type(e).__name__)
        return None
    return DisplayRenderer(font, cfg.font_size)


def _preview(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="用 ASCII 預覽 X-Display-Bitmap（需要 Pillow）")
    ap.add_argument("text")
    ap.add_argument("--font", required=True, help="字型檔路徑（TTF／OTF／TTC）")
    ap.add_argument("--size", type=int, default=16)
    ap.add_argument("--index", type=int, default=0)
    args = ap.parse_args(argv)
    if not pillow_available():
        print("error: Pillow is not installed", file=sys.stderr)
        return 1
    rows = render_text_bitmap(args.text, load_font(args.font, args.size, args.index), args.size)
    for row in rows:
        print("".join("#" if v else "." for v in row))
    print("base64 length:", len(bitmap_header_value(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(_preview())
