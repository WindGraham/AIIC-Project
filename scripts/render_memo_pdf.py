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
@page { size: A4; margin: 16mm 18mm; }
* { box-sizing: border-box; }
body {
  font-family: "Noto Sans CJK SC", "WenQuanYi Zen Hei", "WenQuanYi Micro Hei",
    "PingFang SC", "Microsoft YaHei", sans-serif;
  font-size: 10.8pt; line-height: 1.62; color: #1a1a1a; margin: 0;
}
h1 { font-size: 20pt; line-height: 1.3; margin: 0 0 4pt; border-bottom: 2px solid #312e81; padding-bottom: 6pt; }
h2 { font-size: 14pt; margin: 16pt 0 6pt; color: #312e81; border-left: 4px solid #6366f1; padding-left: 8pt; }
h3 { font-size: 11.5pt; margin: 12pt 0 4pt; color: #3730a3; }
p { margin: 5pt 0; }
ul, ol { margin: 5pt 0; padding-left: 20pt; }
li { margin: 2pt 0; }
strong { color: #111827; }
a { color: #4338ca; text-decoration: none; word-break: break-all; }
blockquote {
  margin: 6pt 0; padding: 6pt 12pt; background: #eef2ff; border-left: 3px solid #6366f1;
  color: #3730a3; border-radius: 4pt;
}
blockquote p { margin: 2pt 0; }
code { background: #f3f4f6; padding: 1pt 4pt; border-radius: 3pt; font-family: monospace; font-size: 10pt; }
pre { background: #f3f4f6; padding: 8pt 10pt; border-radius: 6pt; overflow-x: auto; }
pre code { background: none; padding: 0; }
hr { border: none; border-top: 1px solid #ddd; margin: 14pt 0; }
table { border-collapse: collapse; width: 100%; margin: 8pt 0; font-size: 10pt; }
th, td { border: 1px solid #d1d5db; padding: 5pt 8pt; text-align: left; vertical-align: top; }
th { background: #eef2ff; color: #3730a3; font-weight: 600; }
"""


def clean_autolinks(txt: str) -> str:
    # Wrap bare <https://...> / <github...> so markdown keeps them plain + styled
    return re.sub(r"<((?:https?://|github\.com|WindGraham).*?)>", r"<span>&lt;\1&gt;</span>", txt)


def build_html() -> str:
    md = SRC.read_text(encoding="utf-8")
    md = clean_autolinks(md)
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
                       margin={"top": "16mm", "bottom": "16mm", "left": "18mm", "right": "18mm"})
        await browser.close()
    print("OK ->", OUT)


if __name__ == "__main__":
    asyncio.run(main())
