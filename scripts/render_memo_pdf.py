#!/usr/bin/env python3
"""Render docs/Product-Memo.md -> 提交文件/Product-Memo.pdf via Playwright chromium."""
import asyncio
import pathlib
import re
import sys

import markdown
from playwright.async_api import async_playwright

ROOT = pathlib.Path("/root/AIIC-Project")
SRC = ROOT / "docs" / "Product-Memo.md"
OUT = ROOT / "提交文件" / "Product-Memo.pdf"

CSS = """
@page { size: A4; margin: 13mm 16mm; }
* { box-sizing: border-box; }
body {
  font-family: "Noto Sans CJK SC", "WenQuanYi Zen Hei", "WenQuanYi Micro Hei",
    "PingFang SC", "Microsoft YaHei", sans-serif;
  font-size: 9.9pt; line-height: 1.48; color: #1a1a1a; margin: 0;
}
h1 { font-size: 18pt; line-height: 1.28; margin: 0 0 4pt; border-bottom: 2px solid #312e81; padding-bottom: 5pt; }
h2 { font-size: 12.8pt; margin: 12pt 0 5pt; color: #312e81; border-left: 4px solid #6366f1; padding-left: 8pt; }
h3 { font-size: 10.8pt; margin: 9pt 0 3pt; color: #3730a3; }
p { margin: 4pt 0; }
ul, ol { margin: 4pt 0; padding-left: 18pt; }
li { margin: 1.5pt 0; }
strong { color: #111827; }
a { color: #4338ca; text-decoration: none; word-break: break-all; }
blockquote {
  margin: 5pt 0; padding: 5pt 10pt; background: #eef2ff; border-left: 3px solid #6366f1;
  color: #3730a3; border-radius: 4pt;
}
blockquote p { margin: 2pt 0; }
code { background: #f3f4f6; padding: 1pt 4pt; border-radius: 3pt; font-family: monospace; font-size: 9.2pt; }
pre { background: #f3f4f6; padding: 7pt 9pt; border-radius: 6pt; overflow-x: auto; }
pre code { background: none; padding: 0; }
hr { border: none; border-top: 1px solid #ddd; margin: 11pt 0; }
table { border-collapse: collapse; width: 100%; margin: 7pt 0; font-size: 9.6pt; }
th, td { border: 1px solid #d1d5db; padding: 4pt 7pt; text-align: left; vertical-align: top; }
th { background: #eef2ff; color: #3730a3; font-weight: 600; }
"""


def build_html() -> str:
    md = SRC.read_text(encoding="utf-8")
    body = markdown.markdown(md, extensions=["tables", "fenced_code", "sane_lists"])
    return f"<!doctype html><html lang='zh'><head><meta charset='utf-8'><style>{CSS}</style></head><body>{body}</body></html>"


async def main() -> None:
    html = build_html()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path="/root/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome")
        page = await browser.new_page()
        await page.set_content(html, wait_until="load")
        await page.pdf(path=str(OUT), format="A4", print_background=True,
                       margin={"top": "13mm", "bottom": "13mm", "left": "16mm", "right": "16mm"})
        await browser.close()
    print("OK ->", OUT)


if __name__ == "__main__":
    asyncio.run(main())
