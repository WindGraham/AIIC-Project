"""Search providers for the Researcher module.

Design goals (mirroring MockMate's ``web_research.py`` and DeepInterview's
mock-first adapters):

* **Zero-key first**: :class:`SearchEngineProvider` (360 / bing / baidu HTML
  scraping) and :class:`NowcoderProvider` need no API keys.
* **Optional-key providers** (:class:`TavilyProvider`, :class:`XiaohongshuProvider`,
  :class:`ZhihuProvider`) are ``enabled=False`` unless their key/cookie is set —
  they degrade gracefully, never crash.
* **Every ``search()`` is best-effort**: any network error, captcha, or parse
  failure returns ``[]`` (or ``unavailable`` marker via logs) — never raises, so
  the main flow always survives a blocked network.

Parsing is done with stdlib ``re`` + ``html.unescape`` (no bs4 dependency).
"""

from __future__ import annotations

import base64
import html
import json
import logging
import random
import re
import time
import urllib.parse
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import httpx

from agent.config import get_settings
from agent.contracts import Source

logger = logging.getLogger(__name__)

HTTP_TIMEOUT = 8.0
MAX_RETRIES = 1

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
]

# --- engine config: regex-based result extraction (bs4-free) -----------------
SEARCH_ENGINES = [
    {
        "name": "360",
        "url": "https://www.so.com/s",
        "param": "q",
        "block": r'<li[^>]*class="res-list"[^>]*>(.*?)</li>',
        # prefer data-mdurl (real url) over the so.com/link redirect href
        "anchor": r'<h3[^>]*class="res-title"[^>]*>\s*(<a[^>]*>)(.*?)</a>',
        "url_pattern": r'(?:data-mdurl="([^"]+)"|href="([^"]+)")',
        "snippet": r'<p[^>]*class="res-desc"[^>]*>(.*?)</p>',
    },
    {
        "name": "bing",
        "url": "https://www.bing.com/search",
        "param": "q",
        "block": r'<li[^>]*class="b_algo"[^>]*>(.*?)</li>',
        "anchor": r'<h2[^>]*>\s*(<a[^>]*>)(.*?)</a>',
        "url_pattern": r'href="([^"]+)"',
        "snippet": r'<p[^>]*class="[^"]*b_[^"]*"[^>]*>(.*?)</p>',
    },
    {
        "name": "baidu",
        "url": "https://www.baidu.com/s",
        "param": "wd",
        "block": r'<div[^>]*class="[^"]*(?:c-container|result)[^"]*"[^>]*>(.*?)</div>',
        "anchor": r'<h3[^>]*>\s*(<a[^>]*>)(.*?)</a>',
        "url_pattern": r'href="([^"]+)"',
        "snippet": r'<[^>]*class="[^"]*(?:c-abstract|content-right)[^"]*"[^>]*>(.*?)</[^>]+>',
    },
]


def clean_text(raw: str, max_len: int = 180) -> str:
    """Strip tags/entities, collapse whitespace, truncate."""
    if not raw:
        return ""
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(text)
    text = " ".join(text.split())
    return text[:max_len]


def normalize_url(url: str) -> str:
    """Best-effort canonicalization for dedupe."""
    if not url:
        return ""
    url = html.unescape(url.strip())
    try:
        parts = urllib.parse.urlsplit(url)
        return parts.netloc + parts.path
    except Exception:
        return url[:120]


def _decode_bing_redirect(url: str) -> str:
    """https://www.bing.com/ck/a?...&u=<obfuscated base64url> -> real url.

    Bing prefixes the base64url payload with ``a1``; decode best-effort and fall
    back to the original redirect url on any failure.
    """
    if "bing.com/ck/a" not in url:
        return url
    try:
        parsed = urllib.parse.urlsplit(url)
        params = urllib.parse.parse_qs(parsed.query)
        u = params.get("u", [""])[0]
        if not u:
            return url

        def _try_decode(s: str) -> str:
            pad = "=" * (-len(s) % 4)
            raw = base64.urlsafe_b64decode(s + pad)
            return raw.decode("utf-8", errors="ignore")

        for candidate in (u, u[2:]):  # try as-is, then strip the "a1" prefix
            if not candidate:
                continue
            try:
                decoded = _try_decode(candidate)
            except Exception:
                continue
            if decoded.startswith("http://") or decoded.startswith("https://"):
                return decoded
    except Exception:
        pass
    return url


def dedupe_sources(sources: list[Source], max_len: Optional[int] = None) -> list[Source]:
    seen: set[str] = set()
    out: list[Source] = []
    for s in sources:
        key = normalize_url(s.url) or s.title
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(s)
        if max_len and len(out) >= max_len:
            break
    return out


def company_token(company: str) -> str:
    """Distinctive token of the company name (strip city prefixes), like MockMate."""
    c = (company or "").strip()
    if not c:
        return ""
    if len(c) <= 4:
        return c
    for prefix in (
        "上海", "北京", "深圳", "广州", "杭州", "南京", "成都", "武汉",
        "重庆", "天津", "西安", "苏州", "宁波", "厦门", "中国",
    ):
        if c.startswith(prefix):
            return c[len(prefix):]
    return c[-4:]


# --- provider interface ------------------------------------------------------
class SearchProvider(ABC):
    """Uniform search provider: ``search(query) -> list[Source]``.

    Implementations must NEVER raise; failures return ``[]``.
    """

    name: str = "search-engine"

    @property
    def enabled(self) -> bool:
        return True

    @abstractmethod
    def search(self, query: str, *, max_results: int = 8) -> list[Source]:
        ...


# --- keyless HTML-scraping engine --------------------------------------------
class SearchEngineProvider(SearchProvider):
    """360 / bing / baidu HTML scraping, zero API keys.

    Uses ``httpx`` with ``trust_env=True`` so it honours the http_proxy/https_proxy
    env vars (this sandbox needs ``export https_proxy=http://127.0.0.1:7890``).
    Any engine failure (captcha, timeout, blocked) degrades to the next engine /
    empty list — never raises.
    """

    name = "search-engine"

    def __init__(self, company: str = "", *, timeout: float = HTTP_TIMEOUT):
        self.company = (company or "").strip()
        self._timeout = timeout
        self._ua_index = random.randint(0, len(USER_AGENTS) - 1)
        self._client: Optional[httpx.Client] = None

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                timeout=self._timeout,
                follow_redirects=True,
                trust_env=True,  # read system proxy env (http_proxy/https_proxy)
                headers={"Accept-Language": "zh-CN,zh;q=0.9"},
            )
        return self._client

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None

    def _rotate_ua(self) -> None:
        self._ua_index = (self._ua_index + 1) % len(USER_AGENTS)
        self._get_client().headers["User-Agent"] = USER_AGENTS[self._ua_index]

    # -- public API ----------------------------------------------------------
    def search(self, query: str, *, max_results: int = 8) -> list[Source]:
        """Search all engines; stop early once we have enough results so a slow
        engine cannot stall the whole profile build."""
        out: list[Source] = []
        early_stop = max(3, min(max_results, 8) // 2 + 1)  # e.g. 8 -> 5
        try:
            for engine in SEARCH_ENGINES:
                try:
                    out.extend(self._search_engine(engine, query, max_results))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("researcher: engine %s failed for %r: %s", engine["name"], query, exc)
                if len(out) >= early_stop:
                    break
        except Exception as exc:  # noqa: BLE001 - outermost safety net
            logger.warning("researcher: SearchEngineProvider.search crashed: %s", exc)
            return []
        return dedupe_sources(out, max_len=max_results)

    # -- internals -----------------------------------------------------------
    def _search_engine(self, engine: dict, query: str, max_results: int) -> list[Source]:
        for attempt in range(MAX_RETRIES + 1):
            self._rotate_ua()
            try:
                resp = self._get_client().get(
                    engine["url"], params={engine["param"]: query}
                )
                if resp.status_code >= 400:
                    logger.info("researcher: %s HTTP %s for %r", engine["name"], resp.status_code, query)
                    return []
                results = self._parse_engine(engine, resp.text)
                logger.info(
                    "researcher: %s parsed %d results for %r (http %d, %d bytes)",
                    engine["name"], len(results), query, resp.status_code, len(resp.content),
                )
                if results:
                    return results
            except httpx.TimeoutException:
                logger.warning("researcher: %s timeout (attempt %d) %r", engine["name"], attempt + 1, query)
            except Exception as exc:  # noqa: BLE001
                logger.warning("researcher: %s error (attempt %d): %s", engine["name"], attempt + 1, exc)
            if attempt < MAX_RETRIES:
                time.sleep(0.4)
        return []

    def _parse_engine(self, engine: dict, page: str) -> list[Source]:
        sources: list[Source] = []
        for block in re.findall(engine["block"], page, re.S)[:12]:
            try:
                src = self._parse_block(engine, block)
            except Exception:  # noqa: BLE001 - one bad block never kills the page
                src = None
            if src:
                sources.append(src)
        # relevance filter: for company-specific queries keep only hits mentioning
        # the company (Mirror MockMate's _results_relevant intent).
        token = company_token(self.company)
        if token:
            sources = [s for s in sources if token in (s.title + s.snippet + s.url)]
        return sources

    def _parse_block(self, engine: dict, block: str) -> Optional[Source]:
        m = re.search(engine["anchor"], block, re.S)
        if not m:
            return None
        a_tag, title_raw = m.group(1), m.group(2)
        url = self._extract_url(a_tag, engine["url_pattern"])
        if not url:
            return None
        title = clean_text(title_raw, max_len=120)
        if not title:
            return None
        if engine["name"] == "bing":
            url = _decode_bing_redirect(url)
        snippet = ""
        sm = re.search(engine["snippet"], block, re.S)
        if sm:
            snippet = clean_text(sm.group(1), max_len=180)
        if not snippet:
            # generic fallback: strip the whole block and drop the title text
            snippet = clean_text(block, max_len=180)
            if title and snippet.startswith(title):
                snippet = snippet[len(title):].strip()[:180]
        if not snippet:
            snippet = title
        return Source(
            title=title,
            url=url,
            snippet=snippet,
            provider="search-engine",
        )

    @staticmethod
    def _extract_url(a_tag: str, url_pattern: str) -> str:
        # prefer 360's data-mdurl (real target) over the so.com/link redirect
        m = re.search(r'data-mdurl="([^"]+)"', a_tag)
        if not m:
            m = re.search(url_pattern, a_tag)
        if not m:
            return ""
        url = m.group(1) or m.group(2) or ""
        return html.unescape(url).strip()


# --- nowcoder anonymous interview posts ---------------------------------------
class NowcoderProvider(SearchProvider):
    """牛客匿名面经搜索（无需 key）。

    POST https://gw-c.nowcoder.com/api/sparta/pc/search with ``type: "post"``
    (verified against the live API; other payloads return 搜索类型不合法).
    Any failure degrades to [] — the engine-route still covers the search.
    """

    name = "nowcoder"
    URL = "https://gw-c.nowcoder.com/api/sparta/pc/search"
    HEADERS = {
        "Content-Type": "application/json",
        "Referer": "https://www.nowcoder.com/",
    }

    def __init__(self, *, timeout: float = HTTP_TIMEOUT):
        self._timeout = timeout
        self._client: Optional[httpx.Client] = None

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self._timeout, trust_env=True)
        return self._client

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None

    def search(self, query: str, *, max_results: int = 8) -> list[Source]:
        out: list[Source] = []
        try:
            resp = self._get_client().post(
                self.URL,
                json={"query": query, "type": "post", "page": 1, "pageSize": 20},
                headers=self.HEADERS,
            )
            resp.raise_for_status()
            data = resp.json()
            if not data.get("success"):
                logger.info("researcher: nowcoder search rejected: %s", data.get("msg"))
                return []
            records = (data.get("data") or {}).get("records") or []
            for rec in records:
                cd = rec.get("contentData") or {}
                title = cd.get("title") or ""
                if not title:
                    continue
                post_id = cd.get("id") or rec.get("entityId") or ""
                url = f"https://www.nowcoder.com/discuss/{post_id}" if post_id else ""
                content = cd.get("content") or cd.get("newContent") or ""
                if isinstance(content, dict):
                    content = json.dumps(content, ensure_ascii=False)
                snippet = clean_text(str(content), max_len=180)
                out.append(
                    Source(title=clean_text(title, max_len=120), url=url, snippet=snippet, provider="nowcoder")
                )
                if len(out) >= max_results:
                    break
            logger.info("researcher: nowcoder %d results for %r", len(out), query)
        except Exception as exc:  # noqa: BLE001
            logger.warning("researcher: nowcoder search failed for %r: %s", query, exc)
            return []
        return dedupe_sources(out, max_len=max_results)


# --- optional key-gated providers ---------------------------------------------
class TavilyProvider(SearchProvider):
    """Tavily web search (HTTP API, no SDK). Enabled only when a key is set."""

    name = "tavily"
    URL = "https://api.tavily.com/search"

    def __init__(self, api_key: str, *, timeout: float = HTTP_TIMEOUT):
        self._api_key = (api_key or "").strip()
        self._timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self._api_key)

    def search(self, query: str, *, max_results: int = 8) -> list[Source]:
        if not self.enabled:
            return []
        out: list[Source] = []
        try:
            resp = httpx.post(
                self.URL,
                json={
                    "api_key": self._api_key,
                    "query": query,
                    "max_results": min(max_results, 8),
                    "search_depth": "basic",
                    "include_answer": False,
                },
                timeout=self._timeout,
            )
            resp.raise_for_status()
            for item in (resp.json().get("results") or [])[:max_results]:
                out.append(
                    Source(
                        title=clean_text(item.get("title") or "", 120),
                        url=item.get("url") or "",
                        snippet=clean_text(item.get("content") or "", 180),
                        provider="tavily",
                    )
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("researcher: tavily search failed for %r: %s", query, exc)
            return []
        return out


class XiaohongshuProvider(SearchProvider):
    """小红书搜索 —— 需要 xhs_cookie，强反爬，best-effort + 优雅降级。

    仅当 cookie 非空时 enabled。当前实现为直接 HTTP 占位：解析页面内嵌的
    ``__INITIAL_STATE__`` JSON（若页面结构变化 / 需要验证码则返回空）。
    """

    name = "xiaohongshu"

    def __init__(self, cookie: str = "", *, timeout: float = HTTP_TIMEOUT):
        self._cookie = (cookie or "").strip()
        self._timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self._cookie)

    def search(self, query: str, *, max_results: int = 8) -> list[Source]:
        if not self.enabled:
            return []
        out: list[Source] = []
        try:
            resp = httpx.get(
                "https://www.xiaohongshu.com/search_result",
                params={"keyword": query, "source": "web_search_result_notes"},
                headers={
                    "Cookie": self._cookie,
                    "User-Agent": USER_AGENTS[0],
                    "Referer": "https://www.xiaohongshu.com/",
                },
                timeout=self._timeout,
                follow_redirects=True,
            )
            m = re.search(r"window\.__INITIAL_STATE__\s*=\s*({.*?});", resp.text, re.S)
            if not m:
                logger.info("researcher: xhs page has no INITIAL_STATE (captcha?) for %r", query)
                return []
            state = json.loads(m.group(1))
            notes = (state.get("search") or {}).get("notes") or []
            for note in notes[:max_results]:
                title = note.get("displayTitle") or note.get("title") or ""
                if not title:
                    continue
                note_id = note.get("noteId") or note.get("id") or ""
                url = f"https://www.xiaohongshu.com/explore/{note_id}" if note_id else ""
                out.append(
                    Source(
                        title=clean_text(str(title), 120),
                        url=url,
                        snippet=clean_text(str(note.get("desc") or note.get("description") or ""), 180),
                        provider="xiaohongshu",
                    )
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("researcher: xhs search failed for %r: %s", query, exc)
            return []
        return out


class ZhihuProvider(SearchProvider):
    """知乎搜索 —— 需要 zhihu_d_cookie，best-effort + 优雅降级。"""

    name = "zhihu"

    def __init__(self, cookie: str = "", *, timeout: float = HTTP_TIMEOUT):
        self._cookie = (cookie or "").strip()
        self._timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self._cookie)

    def search(self, query: str, *, max_results: int = 8) -> list[Source]:
        if not self.enabled:
            return []
        out: list[Source] = []
        try:
            resp = httpx.get(
                "https://www.zhihu.com/api/v4/search_v3",
                params={
                    "t": "general",
                    "q": query,
                    "correction": 1,
                    "offset": 0,
                    "limit": min(max_results, 10),
                },
                headers={
                    "Cookie": self._cookie,
                    "User-Agent": USER_AGENTS[0],
                    "Referer": "https://www.zhihu.com/",
                },
                timeout=self._timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            for item in (data.get("data") or [])[:max_results]:
                obj = item.get("object") or item
                title = clean_text(str(obj.get("title") or obj.get("question") or ""), 120)
                if not title:
                    continue
                url = obj.get("url") or obj.get("urlToken") or ""
                if url and not url.startswith("http"):
                    url = f"https://www.zhihu.com{url if url.startswith('/') else '/' + url}"
                out.append(
                    Source(
                        title=title,
                        url=url,
                        snippet=clean_text(str(obj.get("excerpt") or obj.get("content") or ""), 180),
                        provider="zhihu",
                    )
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("researcher: zhihu search failed for %r: %s", query, exc)
            return []
        return out


# --- factory + parallel runner -------------------------------------------------
def get_providers(settings=None) -> list[SearchProvider]:
    """Build the enabled provider stack from settings (mock-first philosophy:
    keyless providers always on, key-gated providers only when configured)."""
    s = settings or get_settings()
    providers: list[SearchProvider] = [
        SearchEngineProvider(company=""),  # company filtering applied per-query
        NowcoderProvider(),
    ]
    tavily = TavilyProvider(s.tavily_api_key)
    if tavily.enabled:
        providers.append(tavily)
    xhs = XiaohongshuProvider(s.xhs_cookie)
    if xhs.enabled:
        providers.append(xhs)
    zhihu = ZhihuProvider(s.zhihu_d_cookie)
    if zhihu.enabled:
        providers.append(zhihu)
    return providers


def run_queries(
    providers: list[SearchProvider],
    queries: list[str],
    *,
    per_query: int = 8,
    max_total: int = 40,
    deadline: float = 35.0,
    workers: int = 6,
    require_company_hits: str = "",
) -> list[Source]:
    """Run ``queries`` across all providers in a thread pool, bounded by a deadline.

    Returns deduplicated sources. Never raises — providers already swallow their
    own errors; this adds a global deadline so a slow network cannot hang prep.
    """
    if not providers or not queries:
        return []
    token = company_token(require_company_hits)
    tasks: list[tuple[SearchProvider, str]] = [
        (p, q) for p in providers if p.enabled for q in queries
    ]
    results: list[Source] = []
    start = time.monotonic()
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(p.search, q, max_results=per_query): (p, q) for p, q in tasks}
            for fut in as_completed(futures):
                if time.monotonic() - start > deadline:
                    logger.warning("researcher: search deadline hit; returning partial results")
                    break
                try:
                    results.extend(fut.result())
                except Exception as exc:  # noqa: BLE001 - defensive
                    logger.warning("researcher: provider task raised: %s", exc)
    except Exception as exc:  # noqa: BLE001
        logger.warning("researcher: run_queries failed: %s", exc)
    # company-tagged sources first (stable sort) so the cap keeps the most
    # valuable evidence for the profile prompt.
    if token:
        results.sort(key=lambda s: 0 if token in (s.title + s.snippet + s.url) else 1)
    sources = dedupe_sources(results, max_len=max_total)
    # company-hit tracking: count sources that mention the company token
    if token:
        tagged = [s for s in sources if token in (s.title + s.snippet + s.url)]
        logger.info("researcher: %d/%d sources mention company token %r", len(tagged), len(sources), token)
    return sources


def count_company_hits(sources: list[Source], company: str) -> int:
    token = company_token(company)
    if not token:
        return 0
    return sum(1 for s in sources if token in (s.title + s.snippet + s.url))
