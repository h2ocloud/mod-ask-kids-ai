#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""產生 OLED 用的中文狀態字點陣（XBM 格式，給 U8g2 drawXBM）。

為什麼不用 U8g2 內建中文字型：U8g2 的中文字集以簡體常用字為主，繁體字缺很多。
這裡改成「只把固定要顯示的幾十個詞」預先算成點陣，韌體不必帶整套字型。

字型：Cubic 11（俐方體11號，SIL OFL 1.1，https://github.com/ACh-K/Cubic-11）。
用法：python3 gen_labels.py <Cubic_11.ttf> <輸出 labels_zh.h>
需要 Pillow（只有重新產生時才需要；韌體編譯不需要）。
"""
import sys

from PIL import Image, ImageDraw, ImageFont

# (識別名, 文字, 倍率)。倍率 2 = 24 px 高的大標題，最多 4 個字（96 px 寬）。
LABELS = [
    ("T_BOOT", "開機中", 2),
    ("T_WIFI", "連線中", 2),
    ("T_IDLE", "按住說話", 2),
    ("T_LISTEN", "聆聽中", 2),
    ("T_THINK", "思考中", 2),
    ("T_SPEAK", "回答中", 2),
    ("T_OFFLINE", "沒有網路", 2),
    ("T_NOCONFIG", "尚未設定", 2),
    ("T_ERROR", "出錯了", 2),
    ("H_IDLE", "按住按鈕問問題", 1),
    ("H_LISTEN", "說完放開按鈕", 1),
    ("H_THINK", "請稍等一下", 1),
    ("H_SPEAK", "按一下可以插話", 1),
    ("H_OFFLINE", "請大人檢查 Wi-Fi", 1),
    ("H_NOCONFIG", "請大人設定 secrets.h", 1),
    ("H_WIFI", "正在找 Wi-Fi", 1),
    ("E_CONNECT", "連不上伺服器", 1),
    ("E_TIMEOUT", "伺服器太慢了", 1),
    ("E_BADAUDIO", "聲音格式錯誤", 1),
    ("E_TOOSHORT", "沒有聽到聲音", 1),
    ("E_AUTH", "裝置未授權", 1),
    ("E_NOTFOUND", "伺服器網址錯誤", 1),
    ("E_TOOLONG", "說太久了", 1),
    ("E_NOSPEECH", "沒聽清楚，再說一次", 1),
    ("E_RATELIMIT", "休息一下再問", 1),
    ("E_SERVER", "伺服器出錯", 1),
    ("E_BADREPLY", "回答格式錯誤", 1),
    ("E_NOWIFI", "沒有網路", 1),
]

FONT_SIZE = 11  # Pillow 在 size=11 時字寬剛好 12 px（Cubic 11 的 12 px 設計格）
FONT_PX = 13  # 畫布高：含下伸部


def render(font, text, scale):
    # 先在大畫布上畫，再裁到實際墨跡寬度；高度固定 FONT_PX，讓同倍率的字基線一致
    w = FONT_PX * (len(text) + 2)
    img = Image.new("1", (w, FONT_PX), 0)
    d = ImageDraw.Draw(img)
    d.fontmode = "1"  # 不要反鋸齒
    d.text((0, 0), text, font=font, fill=1)
    bbox = img.getbbox()
    right = bbox[2] if bbox else 1
    img = img.crop((0, 0, right, FONT_PX))
    if scale != 1:
        img = img.resize((img.width * scale, img.height * scale), Image.NEAREST)
    return img


def to_xbm_bytes(img):
    w, h = img.size
    stride = (w + 7) // 8
    out = []
    px = img.load()
    for y in range(h):
        for bx in range(stride):
            b = 0
            for bit in range(8):
                x = bx * 8 + bit
                if x < w and px[x, y]:
                    b |= 1 << bit  # XBM：最低位元是最左邊的點
            out.append(b)
    return out


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    font = ImageFont.truetype(sys.argv[1], FONT_SIZE)
    lines = [
        "// labels_zh.h — 自動產生，請勿手改（firmware/tools/gen_labels.py）",
        "// SPDX-License-Identifier: OFL-1.1",
        "// 點陣由 Cubic 11（俐方體11號，SIL Open Font License 1.1）算繪；授權全文見 LICENSES/OFL-1.1-Cubic-11.txt",
        "#pragma once",
        "#include <stdint.h>",
        "",
        "struct ZhLabel { uint8_t w; uint8_t h; const uint8_t* bits; const char* text; };",
        "",
    ]
    names = []
    for name, text, scale in LABELS:
        img = render(font, text, scale)
        if img.width > 128:
            raise SystemExit(f"{name} 太寬：{img.width} px")
        if scale == 2 and img.width > 96:
            raise SystemExit(f"{name} 標題超過 96 px：{img.width}")
        data = to_xbm_bytes(img)
        body = ",".join(f"0x{b:02x}" for b in data)
        lines.append(f"// {text}（{img.width}×{img.height}）")
        lines.append(f"static const uint8_t {name}_bits[] = {{{body}}};")
        lines.append(f"static const ZhLabel {name} = {{{img.width}, {img.height}, {name}_bits, \"{text}\"}};")
        names.append(name)
    lines.append("")
    with open(sys.argv[2], "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"wrote {len(names)} labels -> {sys.argv[2]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
