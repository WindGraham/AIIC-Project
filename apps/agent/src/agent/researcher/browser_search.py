"""Browser-backed search for cookie-gated platforms (小红书 / 知乎).

These platforms generate runtime anti-bot request signatures (``x-s``/``x-t`` on
XHS, ``x-zse-96`` on 知乎) that a plain HTTP client cannot reproduce. The robust
approach: drive a real headless Chromium with the user's logged-in cookies, let
the page's own JS sign the requests, then extract results from the rendered DOM.

Thread-safety: Playwright's sync API uses greenlets bound to the thread that
created the browser/context. To use it from a thread pool (``run_queries``), we
run ALL browser work on ONE dedicated worker thread that owns Playwright for the
process lifetime. ``search_xhs`` / ``search_zhihu`` submit a job and block on the
result; the worker is daemonized so it never blocks shutdown.

Graceful degradation: any failure inside the worker returns ``[]`` (or a marker),
never raises, so the keyless engine route still covers the search. ``playwright``
is an optional runtime dependency (imported lazily), so the agent boots without it.
"""

from __future__ import annotations

import logging
import queue
import threading
from typing import Any, Optional

from agent.config import get_settings
from agent.contracts import Source

logger = logging.getLogger(__name__)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")

_JOBS: "queue.Queue[tuple[str, str, int, float, queue.Queue]]" = queue.Queue()
_WORKER = None
_WORKER_LOCK = threading.Lock()


def _parse_cookies(cookie_str: str, domain: str) -> list[dict[str, Any]]:
    out = []
    for part in (cookie_str or "").split(";"):
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        name = name.strip()
        if not name:
            continue
        out.append({"name": name, "value": value.strip(), "domain": domain, "path": "/"})
    return out


def _worker_loop():
    """Owns Playwright + browser for the process. Processes jobs sequentially."""
    sync_pw = None
    browser = None
    context = None
    try:
        from playwright.sync_api import sync_playwright  # lazy, optional
    except Exception as exc:  # noqa: BLE001
        logger.warning("browser_search: playwright not available: %s", exc)
        _drain(_JOBS, None)
        return

    def _ensure():
        nonlocal sync_pw, browser, context
        if browser is not None:
            return context
        s = get_settings()
        sync_pw = sync_playwright().start()
        browser = sync_pw.chromium.launch(headless=True)
        context = browser.new_context(user_agent=UA, locale="zh-CN", viewport={"width": 1280, "height": 900})
        if s.xhs_cookie:
            try:
                context.add_cookies(_parse_cookies(s.xhs_cookie, ".xiaohongshu.com"))
            except Exception as exc:  # noqa: BLE001
                logger.warning("browser_search: xhs cookie inject failed: %s", exc)
        if s.zhihu_d_cookie:
            try:
                context.add_cookies(_parse_cookies(s.zhihu_d_cookie, ".zhihu.com"))
            except Exception as exc:  # noqa: BLE001
                logger.warning("browser_search: zhihu cookie inject failed: %s", exc)
        return context

    while True:
        job = _JOBS.get()
        if job is None:
            break
        kind, query, max_results, sleep_s, resp = job
        try:
            ctx = _ensure()
            page = ctx.new_page()
            page.set_default_timeout(25000)
            try:
                if kind == "xhs":
                    result = _xhs(page, query, max_results, sleep_s)
                else:
                    result = _zhihu(page, query, max_results, sleep_s)
                resp.put(result)
            finally:
                try:
                    page.close()
                except Exception:  # noqa: BLE001
                    pass
        except Exception as exc:  # noqa: BLE001
            logger.warning("browser_search: %s job failed for %r: %s", kind, query, exc)
            resp.put([])

    # shutdown
    try:
        if context is not None:
            context.close()
        if browser is not None:
            browser.close()
        if sync_pw is not None:
            sync_pw.stop()
    except Exception:  # noqa: BLE001
        pass


def _drain(jobs, value):
    while True:
        try:
            job = jobs.get_nowait()
        except queue.Empty:
            break
        _, _, _, _, resp = job
        resp.put(value or [])


def _ensure_worker() -> None:
    global _WORKER
    with _WORKER_LOCK:
        # Force a fresh worker if the current one died, so a single failed launch
        # doesn't permanently disable browser search for the process lifetime.
        if _WORKER is not None and _WORKER.is_alive():
            return
        _WORKER = threading.Thread(target=_worker_loop, name="browser-search", daemon=True)
        _WORKER.start()


def _submit(kind: str, query: str, *, max_results: int, sleep_s: float) -> list[Source]:
    """Submit a browser search job and block for the result. Never raises."""
    _ensure_worker()
    resp: "queue.Queue" = queue.Queue()
    _JOBS.put((kind, query, max_results, sleep_s, resp))
    timeout = 45.0
    try:
        result = resp.get(timeout=timeout)
    except queue.Empty:
        logger.warning("browser_search: %s job timed out for %r", kind, query)
        return []
    return result or []


def close() -> None:
    """Signal the worker to shut down (best effort)."""
    try:
        _JOBS.put(None)
    except Exception:  # noqa: BLE001
        pass


# --- platform extractors (run on the worker thread) --------------------------
def _xhs(page: Any, query: str, max_results: int, sleep_s: float) -> list[Source]:
    from urllib.parse import quote
    url = "https://www.xiaohongshu.com/search_result?keyword=" + quote(query) + "&source=web_search_result_notes"
    page.goto(url, timeout=30000)
    page.wait_for_timeout(sleep_s * 1000)
    cards = page.query_selector_all("[class*='note-item']")
    seen: set[str] = set()
    out: list[Source] = []
    for c in cards:
        try:
            nid = c.get_attribute("data-note-id")
            if not nid or nid in seen:
                continue
            title = c.evaluate(
                """el => {
                    const cs = el.querySelectorAll("[class*='title'], [class*='Title'], span, p");
                    for (const x of cs) { const t=(x.textContent||'').trim(); if (t.length>6 && t.length<100) return t; }
                    return (el.textContent||'').trim().slice(0,80);
                }"""
            )
            title = (title or "").strip()
            seen.add(nid)
            out.append(Source(title=(title or "小红书笔记")[:120],
                              url="https://www.xiaohongshu.com/explore/" + nid,
                              snippet="", provider="xiaohongshu"))
            if len(out) >= max_results:
                break
        except Exception as exc:  # noqa: BLE001
            logger.debug("browser_search: xhs card skipped: %s", exc)
    logger.info("browser_search: xhs %d results for %r", len(out), query)
    return out


def _zhihu(page: Any, query: str, max_results: int, sleep_s: float) -> list[Source]:
    from urllib.parse import quote
    url = "https://www.zhihu.com/search?type=content&q=" + quote(query)
    page.goto(url, timeout=30000)
    page.wait_for_timeout(sleep_s * 1000)
    cards = page.query_selector_all(".SearchResult-Card, .List-item")
    seen: set[str] = set()
    out: list[Source] = []
    for card in cards:
        try:
            a = card.query_selector("a[href*='/question/']")
            if not a:
                continue
            href = a.get_attribute("href") or ""
            full = href if href.startswith("http") else "https://www.zhihu.com" + href
            if full in seen:
                continue
            title = (a.text_content() or "").strip()
            if not title:
                title = (a.get_attribute("title") or "").strip()
            if not title:
                continue
            seen.add(full)
            snippet = (card.text_content() or "").strip()[:200]
            out.append(Source(title=title[:120], url=full, snippet=snippet, provider="zhihu"))
            if len(out) >= max_results:
                break
        except Exception as exc:  # noqa: BLE001
            logger.debug("browser_search: zhihu card skipped: %s", exc)
    logger.info("browser_search: zhihu %d results for %r", len(out), query)
    return out


def search_xhs(query: str, *, max_results: int = 8, sleep_s: float = 4.0) -> list[Source]:
    return _submit("xhs", query, max_results=max_results, sleep_s=sleep_s)


def search_zhihu(query: str, *, max_results: int = 8, sleep_s: float = 3.0) -> list[Source]:
    return _submit("zhihu", query, max_results=max_results, sleep_s=sleep_s)
