#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""把 SVG 轉成 PNG（headless Chromium，獨立暫存 profile，不碰使用者的瀏覽器）。
用法：python3 render_png.py <in.svg> <out.png> [寬度 px，預設 2000]
需要：pip install playwright && python3 -m playwright install chromium
"""
import pathlib
import sys

from playwright.sync_api import sync_playwright


def main():
    src = pathlib.Path(sys.argv[1]).resolve()
    dst = pathlib.Path(sys.argv[2]).resolve()
    width = int(sys.argv[3]) if len(sys.argv) > 3 else 2000
    svg = src.read_text(encoding="utf-8")
    # 從 viewBox 算高度
    import re

    vb = re.search(r'viewBox="0 0 (\d+) (\d+)"', svg)
    w, h = int(vb.group(1)), int(vb.group(2))
    height = round(width * h / w)
    html = f"<!doctype html><meta charset='utf-8'><style>html,body{{margin:0;background:#fff}}svg{{display:block;width:{width}px;height:{height}px}}</style>{svg}"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
        page.set_content(html)
        page.wait_for_timeout(300)
        page.screenshot(path=str(dst), full_page=False)
        page.close()
        browser.close()
    print("wrote", dst)


if __name__ == "__main__":
    main()
