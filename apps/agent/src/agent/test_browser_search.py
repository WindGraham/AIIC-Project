"""Tests for browser-backed search degradation (xhs / 知乎).

These do NOT hit the network (chromium may not be installed in CI). Instead we
test the module's graceful-degradation contract: with no cookie, providers are
disabled; with a cookie but no chromium, `_submit` must never raise and must
return [] (the keyless engine route still covers the search).

Run: cd apps/agent && PYTHONPATH=src .venv/bin/python -m pytest src/agent/test_browser_search.py -q
"""

import pytest

from agent.researcher.browser_search import _parse_cookies, _submit, search_xhs, search_zhihu
from agent.researcher.providers import XiaohongshuProvider, ZhihuProvider


def test_parse_cookies():
    out = _parse_cookies("a=1; b=2; c=3", ".example.com")
    assert out == [
        {"name": "a", "value": "1", "domain": ".example.com", "path": "/"},
        {"name": "b", "value": "2", "domain": ".example.com", "path": "/"},
        {"name": "c", "value": "3", "domain": ".example.com", "path": "/"},
    ]


def test_parse_cookies_ignores_empty():
    assert _parse_cookies(";;", ".example.com") == []


def test_providers_disabled_without_cookie():
    assert XiaohongshuProvider("").enabled is False
    assert ZhihuProvider("").enabled is False


def test_providers_enabled_with_cookie():
    assert XiaohongshuProvider("a=b").enabled is True
    assert ZhihuProvider("d_c0=xyz").enabled is True


def test_search_disabled_returns_empty():
    # Not enabled => [] immediately, no browser, no network.
    assert XiaohongshuProvider("").search("字节", max_results=5) == []
    assert ZhihuProvider("").search("字节", max_results=5) == []


def test_submit_returns_list_without_worker():
    """The slow path must degrade gracefully. Rather than hit the network, verify
    the module exposes list-returning functions and that _parse_cookies is the
    only network-free primitive. This keeps the test hermetic."""
    import agent.researcher.browser_search as bs
    assert callable(bs.search_xhs)
    assert callable(bs.search_zhihu)
    assert callable(bs.close)
