#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""畫 MOD-ASK 接線圖（自繪 SVG，不使用任何第三方元件圖）。

板子腳位取自 Espressif 官方 ESP32-S3-DevKitC-1 v1.1 user guide 的 J1／J3 表
（第 1 腳在天線端）。每條線的端點由腳位座標計算，保證落在真的腳位上。
輸出：wiring_mod_ask.svg（圖本身以 CC0-1.0 釋出）。PNG 用 render_png.py 另外轉。
用法：python3 draw_wiring.py <輸出.svg>
"""
import sys
from xml.sax.saxutils import escape

# ---------- 官方腳位表（v1.1；v1.0 差別：RGB LED 在 GPIO48 而不是 38） ----------
J1 = ["3V3", "3V3", "RST", "4", "5", "6", "7", "15", "16", "17", "18", "8", "3", "46",
      "9", "10", "11", "12", "13", "14", "5V", "GND"]
J3 = ["GND", "TX/43", "RX/44", "1", "2", "42", "41", "40", "39", "38", "37", "36", "35",
      "0", "45", "48", "47", "21", "20", "19", "GND", "GND"]
assert len(J1) == 22 and len(J3) == 22

AVOID = {  # 腳位 → 原因（畫成灰色斜線）
    "3": "strapping", "46": "strapping", "0": "strapping", "45": "strapping",
    "TX/43": "UART0", "RX/44": "UART0", "20": "USB D+", "19": "USB D−",
    "35": "PSRAM", "36": "PSRAM", "37": "PSRAM", "38": "LED v1.1", "48": "LED v1.0",
}

W, H = 2000, 1580
BX0, BX1 = 840, 1160          # 板子左右邊
BY0, BY1 = 300, 1270          # 板子上下邊（天線在上，USB 在下）
PIN_Y0, PITCH = 470, 36       # 第 1 腳 y、腳距（畫面用，不是實際 2.54 mm 比例）
J1X, J3X = BX0 + 22, BX1 - 22

COLORS = {
    "3v3": "#d62728", "5v": "#ff7f0e", "gnd": "#222222",
    "ws": "#1f77b4", "sck": "#17becf", "sd": "#2c5fa8",
    "din": "#2ca02c", "bclk": "#7fbf3f", "lrc": "#1b7a3a",
    "sda": "#9467bd", "scl": "#e377c2", "btn": "#8c564b",
}


def pin_y(n):
    return PIN_Y0 + (n - 1) * PITCH


def jpos(header, n):
    return (J1X if header == "J1" else J3X, pin_y(n))


out = []
labels = []  # 線的標籤最後才畫，永遠在線的上面


def add(s):
    out.append(s)


def text(x, y, s, size=20, anchor="start", weight="normal", fill="var(--ink)", cls=""):
    add(f'<text x="{x}" y="{y}" font-size="{size}" text-anchor="{anchor}" font-weight="{weight}" '
        f'fill="{fill}" class="{cls}">{escape(s)}</text>')


def rect(x, y, w, h, fill, stroke="var(--ink)", rx=10, sw=2, extra=""):
    add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{stroke}" '
        f'stroke-width="{sw}" {extra}/>')


def wire(points, color, label=None, label_at=None):
    d = "M " + " L ".join(f"{x} {y}" for x, y in points)
    # 先畫背景色粗線（交叉處會出現缺口＝沒有相連），再畫彩色線
    add(f'<path d="{d}" fill="none" stroke="var(--bg)" stroke-width="11" stroke-linejoin="round"/>')
    add(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="5" stroke-linejoin="round" stroke-linecap="round"/>')
    for x, y in (points[0], points[-1]):
        add(f'<circle cx="{x}" cy="{y}" r="7" fill="{color}" stroke="var(--bg)" stroke-width="2"/>')
    if label and label_at:
        labels.append((label_at, label, color))


def label_width(s):
    return sum(16 if ord(c) > 0x2E80 else 9 for c in s)


def flush_labels():
    for (lx, ly), label, color in labels:
        add(f'<rect x="{lx - 4}" y="{ly - 17}" width="{label_width(label) + 8}" height="22" rx="4" fill="var(--bg)" opacity="0.95"/>')
        text(lx, ly, label, 16, fill=color, weight="bold")


def module(x, y, w, h, title, sub, pins, side, fill):
    """pins: [(名稱, y 偏移)]；side='right' 或 'left' 或 'bottom'；回傳 {名稱: (x, y)}"""
    rect(x, y, w, h, fill)
    text(x + 14, y + 32, title, 24, weight="bold")
    if sub:
        text(x + 14, y + 58, sub, 16, fill="var(--muted)")
    pos = {}
    for name, off in pins:
        if side == "right":
            px, py = x + w, y + off
            text(px - 12, py + 6, name, 18, anchor="end", weight="bold")
        elif side == "left":
            px, py = x, y + off
            text(px + 12, py + 6, name, 18, weight="bold")
        else:  # bottom：off 是 x 偏移
            px, py = x + off, y + h
            text(px, py - 12, name, 16, anchor="middle", weight="bold")
        add(f'<rect x="{px - 7}" y="{py - 7}" width="14" height="14" fill="#c9a227" stroke="var(--ink)" stroke-width="1.5"/>')
        pos[name] = (px, py)
    return pos


def main():
    dst = sys.argv[1]
    add(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
        f'font-family="\'Noto Sans TC\',\'PingFang TC\',\'Microsoft JhengHei\',sans-serif">')
    add('<title>MOD-ASK 接線圖：ESP32-S3-DevKitC-1 N16R8＋INMP441＋MAX98357A＋OLED＋按鈕</title>')
    add('<metadata>SPDX-License-Identifier: CC0-1.0；自繪，不含第三方元件圖。腳位來源見 wiring/PINMAP.md</metadata>')
    add('<style>svg{--bg:#ffffff;--ink:#1d1d1f;--muted:#5b5b66;--board:#1f4e79;--boardink:#ffffff}</style>')
    rect(0, 0, W, H, "var(--bg)", stroke="none", rx=0)

    text(40, 56, "MOD-ASK 兒童 AI 問答機：接線圖", 38, weight="bold")
    text(40, 92, "ESP32-S3-DevKitC-1 N16R8（44 腳）正面朝上、天線朝上；J1／J3 腳號從天線端算起（官方 v1.1 腳位表）", 20, fill="var(--muted)")

    # ---------- 開發板 ----------
    rect(BX0, BY0, BX1 - BX0, BY1 - BY0, "var(--board)", stroke="#0d2c47", rx=16, sw=3)
    rect(BX0 + 70, BY0 - 64, BX1 - BX0 - 140, 74, "#c0c0c8", stroke="#555", rx=6)
    text((BX0 + BX1) // 2, BY0 - 20, "天線（模組端）", 20, anchor="middle", weight="bold", fill="#1d1d1f")
    rect(BX0 + 30, BY0 + 18, BX1 - BX0 - 60, 92, "#9aa3ad", stroke="#444", rx=6)
    text((BX0 + BX1) // 2, BY0 + 56, "ESP32-S3-WROOM-1", 18, anchor="middle", weight="bold", fill="#111")
    text((BX0 + BX1) // 2, BY0 + 84, "N16R8（16 MB＋8 MB PSRAM）", 15, anchor="middle", fill="#111")
    # USB 口
    for i, lab in enumerate(["UART 口（燒錄／序列埠）", "USB 口（GPIO19/20）"]):
        ux = BX0 + 40 + i * 150
        rect(ux, BY1 - 18, 90, 46, "#b8b8be", stroke="#444", rx=4)
        text(ux + 45, BY1 + 58 + i * 24, lab, 16, anchor="middle", fill="var(--muted)")
    text(BX0 + 14, BY0 + 140, "J1", 22, weight="bold", fill="var(--boardink)")
    text(BX1 - 14, BY0 + 140, "J3", 22, anchor="end", weight="bold", fill="var(--boardink)")

    for i, name in enumerate(J1, start=1):
        x, y = jpos("J1", i)
        avoid = name in AVOID
        fill = "#6b6b6b" if avoid else "#e8c547"
        add(f'<circle cx="{x}" cy="{y}" r="9" fill="{fill}" stroke="#111" stroke-width="1.5"/>')
        lab = f"{i} {name if name in ('3V3', '5V', 'GND', 'RST') else 'IO' + name}"
        text(x + 18, y + 6, lab, 17, fill="#9fb3c8" if avoid else "var(--boardink)")
    for i, name in enumerate(J3, start=1):
        x, y = jpos("J3", i)
        avoid = name in AVOID
        fill = "#6b6b6b" if avoid else "#e8c547"
        add(f'<circle cx="{x}" cy="{y}" r="9" fill="{fill}" stroke="#111" stroke-width="1.5"/>')
        nm = name if name in ("GND",) or "/" in name else "IO" + name
        text(x - 18, y + 6, f"{nm} {i}", 17, anchor="end", fill="#9fb3c8" if avoid else "var(--boardink)")

    # ---------- 元件 ----------
    mic = module(250, 330, 300, 300, "INMP441 麥克風", "I2S 輸入，3.3 V",
                 [("VDD", 70), ("WS", 120), ("SCK", 165), ("SD", 210)], "right", "#eaf2fb")
    mic_b = module(250, 330, 300, 300, "", "", [("L/R", 90), ("GND", 210)], "bottom", "none")
    amp = module(250, 820, 300, 330, "MAX98357A 功放", "I2S 輸出，Vin 5 V",
                 [("DIN", 70), ("BCLK", 115), ("LRC", 160), ("Vin", 230), ("GND", 280)], "right", "#edf7ec")
    amp_l = module(250, 820, 300, 330, "", "", [("GAIN 浮接＝9 dB", 200), ("SD 浮接＝(L+R)/2", 255)], "left", "none")
    oled = module(1500, 300, 330, 260, "0.96\" OLED", "SSD1315（I2C 0x3C）",
                  [("VCC", 90), ("GND", 135), ("SCL", 180), ("SDA", 225)], "left", "#f4eefb")
    btn = module(1500, 920, 330, 240, "12×12 按鈕", "按住說話（對角兩腳）",
                 [("A", 100), ("B", 175)], "left", "#f7efe9")

    # 麥克風板上 L/R 與 GND 短接（左聲道）
    (lx, ly), (gx, gy) = mic_b["L/R"], mic_b["GND"]
    wire([(lx, ly), (lx, ly + 34), (gx, gy + 34), (gx, gy)], COLORS["gnd"])
    text(lx - 10, ly + 64, "L/R 接 GND＝左聲道", 16, fill="var(--ink)")

    # 喇叭
    rect(300, 1230, 200, 110, "#f2f2f2", rx=55)
    text(400, 1280, "喇叭 4 Ω 3 W", 18, anchor="middle", weight="bold")
    text(400, 1305, "Ø50 mm", 16, anchor="middle", fill="var(--muted)")
    wire([(360, 1150), (360, 1230)], "#555")
    wire([(440, 1150), (440, 1230)], "#555")
    text(452, 1196, "端子 +／−", 16, fill="var(--muted)")

    # ---------- 連線（左側通道 x 由外往內遞增，右側由內往外） ----------
    def left_wire(src, header_pin, chan, color, label):
        sx, sy = src
        tx, ty = jpos("J1", header_pin)
        wire([(sx, sy), (chan, sy), (chan, ty), (BX0 - 2, ty), (tx, ty)], color, label, (sx + 18, sy - 10))

    # 往下走的線：越上面的用越靠板子的通道；往上走的線相反 → 彼此不交叉
    left_wire(mic["VDD"], 1, 790, COLORS["3v3"], "3V3 → J1-1")
    left_wire(mic["WS"], 4, 760, COLORS["ws"], "WS → IO4")
    left_wire(mic["SCK"], 5, 730, COLORS["sck"], "SCK → IO5")
    left_wire(mic["SD"], 6, 700, COLORS["sd"], "SD → IO6")
    left_wire(amp["DIN"], 7, 700, COLORS["din"], "DIN → IO7")
    left_wire(amp["BCLK"], 8, 730, COLORS["bclk"], "BCLK → IO15")
    left_wire(amp["LRC"], 9, 760, COLORS["lrc"], "LRC → IO16")
    left_wire(amp["Vin"], 21, 820, COLORS["5v"], "Vin → 5V J1-21")
    left_wire(amp["GND"], 22, 790, COLORS["gnd"], "GND → J1-22")

    # 麥克風 GND：從板子底下繞到 J3-22
    gx, gy = mic_b["GND"]
    tx, ty = jpos("J3", 22)
    wire([(gx, gy), (gx, gy + 34), (190, gy + 34), (190, 1420), (1390, 1420), (1390, ty), (BX1 + 2, ty), (tx, ty)],
         COLORS["gnd"], "麥克風 GND → J3-22", (210, 1410))

    # OLED VCC 從 J1-2 繞過板子上方
    sx, sy = jpos("J1", 2)
    vx, vy = oled["VCC"]
    wire([(sx, sy), (BX0 - 2, sy), (812, sy), (812, 180), (1350, 180), (1350, vy), (vx, vy)],
         COLORS["3v3"], "OLED VCC ← 3V3 J1-2", (960, 172))

    def right_wire(dst, header_pin, chan, color, label):
        dx, dy = dst
        sx, sy = jpos("J3", header_pin)
        lx = dx - label_width(label) - 16
        wire([(sx, sy), (BX1 + 2, sy), (chan, sy), (chan, dy), (dx, dy)], color, label, (lx, dy - 10))

    right_wire(oled["GND"], 1, 1220, COLORS["gnd"], "GND ← J3-1")
    right_wire(oled["SCL"], 6, 1260, COLORS["scl"], "SCL ← IO42")
    right_wire(oled["SDA"], 7, 1300, COLORS["sda"], "SDA ← IO41")
    right_wire(btn["A"], 17, 1260, COLORS["btn"], "按鈕 ← IO47")
    right_wire(btn["B"], 21, 1300, COLORS["gnd"], "按鈕 ← GND J3-21")

    # ---------- 圖例與注意事項 ----------
    nx, ny = 1440, 1236
    notes = [
        "• 麥克風、OLED 只接 3V3；功放 Vin 接 5V（I2S 訊號仍是 3.3 V）",
        "• 功放 Vin–GND 建議就近並一顆 470–1000 µF 電解＋0.1 µF",
        "• 無聲時：SD 改接 3V3（固定左聲道，韌體左右送同一份）",
        "• I2C 上拉：OLED 模組板上已有（到貨後用電表確認）",
        "• 按鈕接「對角」兩腳；不確定就用電表量按下才導通的那對",
        "• 避開（灰色）：IO0/3/45/46 strapping、IO19/20 USB、",
        "  IO35/36/37 PSRAM、IO38/48 RGB LED、TX/RX UART0",
    ]
    flush_labels()
    rect(nx - 20, ny - 36, 560, 30 + len(notes) * 28, "var(--bg)", stroke="var(--muted)", rx=10, sw=1.5)
    for i, n in enumerate(notes):
        text(nx, ny + i * 28, n, 17)
    text(40, H - 24, "自繪示意圖（CC0-1.0）；腳距與元件大小不按比例。腳位來源：Espressif ESP32-S3-DevKitC-1 v1.1 user guide、INMP441／MAX98357A datasheet。",
         15, fill="var(--muted)")
    add("</svg>")
    with open(dst, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print("wrote", dst)


if __name__ == "__main__":
    main()
