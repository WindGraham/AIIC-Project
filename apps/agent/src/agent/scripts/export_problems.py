#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""export_problems.py — 离线手撕代码题库导出脚本（一次性，可重跑）

从 leetcode.cn 导出精选 easy/medium 高频算法题，落成
`apps/agent/src/agent/data/problems.json`：

1. GET  https://leetcode.cn/api/problems/all/       —— 全量题单（~4400 题）
2. 过滤：非付费、未隐藏、难度 easy/medium、frontend_id 为纯数字（常规题，
   排除 LCP/剑指 Offer 等特殊编号，保证 frontend_id 可稳定排序/展示）
3. 精选：经典 tag 白名单 × curated 高频题单优先，不足再按 total_acs 补齐
   （100~150 题）
4. POST https://leetcode.cn/graphql (questionData)  —— 尽力取题面/示例/topics
   （单题失败只跳过该题的描述，不阻塞；失败题仍保留题单字段）

幂等/可重跑：
- 题单响应与每题 GraphQL 结果都缓存到 `data/.cache/`，重跑不发重复请求；
- `--refresh` 忽略缓存重新拉取；
- 输出记录按 (difficulty, frontend_id) 稳定排序，多次运行数据一致
  （文件内 `meta.exported_at` 是导出时间戳，不参与数据排序）。

用法：
    python3 export_problems.py [--limit 150] [--min 100] [--refresh]
                              [--concurrency 6] [--timeout 20] [--proxy http://...]

联网（本环境需代理）：
    export https_proxy=http://127.0.0.1:7890 http_proxy=http://127.0.0.1:7890

输出 schema（每条记录）：
    frontend_id  str   题号（纯数字字符串）
    title        str   中文题名（无中文时回退英文题名）
    title_en     str   英文题名
    title_slug   str   力扣 slug（唯一标识，用于 GraphQL / URL）
    difficulty   str   easy | medium | hard
    paid_only    bool  是否付费题（本库恒为 false）
    total_acs    int   通过人数（题单字段，频率代理）
    frequency    int   力扣题单的 frequency 字段（0-100，可能为 0）
    topics       list  题目标签展示名（中文优先）
    topic_slugs  list  题目标签 slug（用于程序化过滤）
    description  str   题面纯文本（GraphQL 拿不到时为空串）
    examples     list  [{"input": ..., "output": ...}]，尽力解析，拿不到为 []
    url          str   力扣题目链接
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib import error, request

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

PROBLEMS_API = "https://leetcode.cn/api/problems/all/"
GRAPHQL_API = "https://leetcode.cn/graphql"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

QUESTION_DATA_QUERY = """query questionData($titleSlug: String!) {
  question(titleSlug: $titleSlug) {
    questionId
    questionFrontendId
    title
    titleSlug
    translatedTitle
    translatedContent
    content
    difficulty
    topicTags { name slug translatedName }
    isPaidOnly
  }
}"""

# 经典面试 tag 白名单（slug -> 中文名）。用于"按 tag 精选"，同时可作为
# 数据里 topics 的展示名回退。注意力扣的 heap 标签 slug 新旧两种写法都收。
TAG_WHITELIST: dict[str, str] = {
    "array": "数组",
    "hash-table": "哈希表",
    "two-pointers": "双指针",
    "binary-search": "二分查找",
    "sliding-window": "滑动窗口",
    "breadth-first-search": "广度优先搜索",
    "depth-first-search": "深度优先搜索",
    "dynamic-programming": "动态规划",
    "linked-list": "链表",
    "tree": "树",
    "binary-search-tree": "二叉搜索树",
    "stack": "栈",
    "heap": "堆",
    "heap-priority-queue": "堆",
    "greedy": "贪心",
    "graph": "图",
    "sorting": "排序",
    "string": "字符串",
    "math": "数学",
    "backtracking": "回溯",
    "matrix": "矩阵",
    "queue": "队列",
    "divide-and-conquer": "分治",
    "recursion": "递归",
    "prefix-sum": "前缀和",
    "union-find": "并查集",
    "trie": "字典树",
    "design": "设计",
    "memoization": "记忆化搜索",
    "bit-manipulation": "位运算",
    "monotonic-stack": "单调栈",
    "topological-sort": "拓扑排序",
}

# 精选高频经典题（easy/medium、非付费、常规编号）。按 tag 分组便于维护，
# 实际输出顺序由排序逻辑决定。若个别 slug 在 leetcode.cn 不存在/变题，
# 脚本会跳过它并自动用 total_acs 榜补齐，不会失败。
CURATED_SLUGS: list[str] = [
    # --- Array / Hash Table ---
    "two-sum",
    "best-time-to-buy-and-sell-stock",
    "contains-duplicate",
    "product-of-array-except-self",
    "majority-element",
    "move-zeroes",
    "missing-number",
    "single-number",
    "group-anagrams",
    "top-k-frequent-elements",
    "valid-anagram",
        "two-sum-ii-input-array-is-sorted",
    "3sum",
        "subarray-sum-equals-k",
    "maximum-subarray",
    "merge-intervals",
    "insert-interval",
    "rotate-image",
    "set-matrix-zeroes",
    "spiral-matrix",
        "merge-sorted-array",
    "find-the-duplicate-number",
    "sort-colors",
        "pascals-triangle",
    # --- Two Pointers ---
    "valid-palindrome",
    "container-with-most-water",
    "remove-duplicates-from-sorted-array",
        # --- Binary Search ---
    "binary-search",
    "search-insert-position",
    "first-bad-version",
    "find-first-and-last-position-of-element-in-sorted-array",
    "search-in-rotated-sorted-array",
    "find-minimum-in-rotated-sorted-array",
    "search-a-2d-matrix",
    "sqrtx",
    "koko-eating-bananas",
    "find-peak-element",
    # --- Sliding Window ---
    "longest-substring-without-repeating-characters",
    "permutation-in-string",
    "find-all-anagrams-in-a-string",
    "max-consecutive-ones-iii",
    "longest-repeating-character-replacement",
        # --- Stack / Queue / Monotonic ---
    "valid-parentheses",
    "min-stack",
    "evaluate-reverse-polish-notation",
    "daily-temperatures",
    "next-greater-element-i",
    "implement-queue-using-stacks",
    "implement-stack-using-queues",
    "decode-string",
        # --- Heap ---
    "kth-largest-element-in-an-array",
    "k-closest-points-to-origin",
    "task-scheduler",
        "kth-largest-element-in-a-stream",
    # --- Linked List ---
    "reverse-linked-list",
    "merge-two-sorted-lists",
    "linked-list-cycle",
    "linked-list-cycle-ii",
    "remove-nth-node-from-end-of-list",
    "middle-of-the-linked-list",
    "palindrome-linked-list",
    "add-two-numbers",
    "swap-nodes-in-pairs",
    "lru-cache",
    "copy-list-with-random-pointer",
    "reorder-list",
    "odd-even-linked-list",
    "intersection-of-two-linked-lists",
    "sort-list",
    "remove-duplicates-from-sorted-list",
    # --- Tree ---
    "maximum-depth-of-binary-tree",
    "invert-binary-tree",
    "diameter-of-binary-tree",
    "balanced-binary-tree",
    "same-tree",
    "symmetric-tree",
    "binary-tree-inorder-traversal",
    "binary-tree-level-order-traversal",
    "binary-tree-zigzag-level-order-traversal",
    "validate-binary-search-tree",
    "lowest-common-ancestor-of-a-binary-tree",
    "lowest-common-ancestor-of-a-binary-search-tree",
    "construct-binary-tree-from-preorder-and-inorder-traversal",
    "kth-smallest-element-in-a-bst",
    "binary-search-tree-iterator",
    "path-sum",
        "subtree-of-another-tree",
        "convert-sorted-array-to-binary-search-tree",
        # --- BFS / DFS (graph + matrix) ---
    "number-of-islands",
    "course-schedule",
    "course-schedule-ii",
    "clone-graph",
    "surrounded-regions",
    "pacific-atlantic-water-flow",
    "rotting-oranges",
    "01-matrix",
    "flood-fill",
    "max-area-of-island",
    "open-the-lock",
    "shortest-path-in-binary-matrix",
    "word-search",
    # --- Dynamic Programming ---
    "climbing-stairs",
    "house-robber",
    "house-robber-ii",
    "house-robber-iii",
    "coin-change",
    "coin-change-2",
    "longest-increasing-subsequence",
    "word-break",
    "partition-equal-subset-sum",
    "unique-paths",
    "unique-paths-ii",
    "minimum-path-sum",
    "edit-distance",
    "longest-common-subsequence",
    "best-time-to-buy-and-sell-stock-with-cooldown",
    "decode-ways",
    "jump-game",
    "jump-game-ii",
    "maximum-product-subarray",
    "palindromic-substrings",
    "longest-palindromic-substring",
    "counting-bits",
    "perfect-squares",
        # --- Backtracking ---
    "letter-combinations-of-a-phone-number",
    "generate-parentheses",
    "permutations",
    "subsets",
    "combination-sum",
    "combination-sum-ii",
    "permutations-ii",
    "subsets-ii",
        "palindromic-partitioning",
    # --- Greedy / 其他经典 ---
    "gas-station",
    "non-overlapping-intervals",
            "valid-parenthesis-string",
    "partition-labels",
        "reverse-integer",
    "palindrome-number",
    "roman-to-integer",
    "longest-common-prefix",
    "strstr",
        ]

DIFFICULTY_LEVEL_TO_STR = {1: "easy", 2: "medium", 3: "hard"}
DIFFICULTY_ORDER = {"easy": 0, "medium": 1, "hard": 2}

# ---------------------------------------------------------------------------
# 网络
# ---------------------------------------------------------------------------


def _build_opener(proxy: str | None) -> request.OpenerDirector:
    if proxy:
        return request.build_opener(
            request.ProxyHandler({"http": proxy, "https": proxy})
        )
    # 默认 opener 会自动读取 http_proxy/https_proxy 环境变量
    return request.build_opener()


def http_get_json(url: str, timeout: int, proxy: str | None) -> dict:
    req = request.Request(
        url, headers={"User-Agent": UA, "Accept": "application/json"}
    )
    with _build_opener(proxy).open(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def graphql_question(slug: str, timeout: int, proxy: str | None) -> dict | None:
    """取单题 GraphQL 详情；返回 question 对象或 None（题不存在）。"""
    payload = json.dumps(
        {
            "operationName": "questionData",
            "variables": {"titleSlug": slug},
            "query": QUESTION_DATA_QUERY,
        }
    ).encode("utf-8")
    req = request.Request(
        GRAPHQL_API,
        data=payload,
        headers={
            "User-Agent": UA,
            "Content-Type": "application/json",
            "Referer": f"https://leetcode.cn/problems/{slug}/",
        },
        method="POST",
    )
    with _build_opener(proxy).open(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    if "errors" in body:
        raise RuntimeError(f"graphql errors: {body['errors']}")
    return (body.get("data") or {}).get("question")


def fetch_with_retry(fn, *args, attempts: int = 3, base_delay: float = 1.0, **kw):
    last: Exception | None = None
    for i in range(attempts):
        try:
            return fn(*args, **kw)
        except Exception as exc:  # noqa: BLE001 — 尽力而为，最终抛给调用方
            last = exc
            if i < attempts - 1:
                time.sleep(base_delay * (i + 1))
    assert last is not None
    raise last


# ---------------------------------------------------------------------------
# HTML -> 文本 / 示例解析
# ---------------------------------------------------------------------------


def _strip_tags(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s)).strip()


def html_to_text(h: str) -> str:
    """力扣 translatedContent/content (HTML) -> 可读纯文本（尽力而为）。"""
    if not h:
        return ""
    s = re.sub(r"<pre>", "\n\n```\n", h)
    s = re.sub(r"</pre>", "\n```\n\n", s)
    s = re.sub(r"<code>", "`", s)
    s = re.sub(r"</code>", "`", s)
    s = re.sub(r"<li>", "\n- ", s)
    s = re.sub(r"<p>|<div>|</p>|</div>|<br\s*/?>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n[ \t]+", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    # 收紧代码围栏内部的空行：```\n\n输入 -> ```\n输入
    s = re.sub(r"```\n\n+", "```\n", s)
    s = re.sub(r"\n\n+```", "\n```", s)
    return s.strip()


_PRE_SPLIT_ZH = re.compile(
    r"输入(?:</strong>)?[：: \t]*\s*(.*?)\s*输出(?:</strong>)?[：: \t]*\s*(.*?)"
    r"(?=<strong>\s*解释|<strong>\s*说明|</pre>|$)",
    re.S,
)
_PRE_SPLIT_EN = re.compile(
    r"Input\s*:\s*(.*?)\s*Output\s*:\s*(.*?)"
    r"(?=<strong>\s*Explanation|<strong>\s*Note|</pre>|$)",
    re.S,
)
# 力扣新版题面用 <div class="example-block"> 而非 <pre>
_DIV_SPLIT_ZH = re.compile(
    r"输入[：:]\s*(.*?)\s*输出[：:]\s*(.*?)(?=</div>|$)", re.S
)
_DIV_SPLIT_EN = re.compile(
    r"Input\s*:\s*(.*?)\s*Output\s*:\s*(.*?)(?=</div>|$)", re.S
)
_EXPLANATION_SEPS = ("解释：", "Explanation:", "解释:", "说明：", "提示：")


def _parse_pre(pre_html: str) -> dict | None:
    """解析单个 <pre> 块里的 输入/输出（支持 输入：/输入</strong> 两种写法）。"""
    m = _PRE_SPLIT_ZH.search(pre_html)
    if not m:
        m = _PRE_SPLIT_EN.search(pre_html)
    if not m:
        return None
    return _pair_from_match(m)


def _parse_example_block(div_html: str) -> dict | None:
    """解析单个 <div class="example-block"> 里的 输入/输出。"""
    m = _DIV_SPLIT_ZH.search(div_html)
    if not m:
        m = _DIV_SPLIT_EN.search(div_html)
    if not m:
        return None
    return _pair_from_match(m)


def _pair_from_match(m: re.Match) -> dict | None:
    inp = _strip_tags(m.group(1))
    out = _strip_tags(m.group(2))
    for sep in _EXPLANATION_SEPS:  # 截掉示例后的"解释/说明"，只留结果
        if sep in out:
            out = out.split(sep, 1)[0].rstrip()
    if not inp and not out:
        return None
    return {"input": inp, "output": out}


def parse_examples(translated_content: str | None, content: str | None) -> list[dict]:
    """从题面 HTML 尽力解析 输入/输出 示例。失败返回 []。

    依次尝试：中文 <pre> 块 -> 中文 example-block div -> 英文 <pre> -> 英文 div。
    """
    for src in (translated_content or "", content or ""):
        if not src:
            continue
        examples = []
        for pre in re.findall(r"<pre>(.*?)</pre>", src, re.S):
            ex = _parse_pre(pre)
            if ex:
                examples.append(ex)
        if not examples:
            for div in re.findall(
                r'<div class="example-block">(.*?)</div>', src, re.S
            ):
                ex = _parse_example_block(div)
                if ex:
                    examples.append(ex)
        if examples:
            return examples
    return []


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def process_problem_list(data: dict) -> list[dict]:
    """全量题单 -> 候选 dict 列表（easy/medium、非付费、纯数字编号）。"""
    candidates: list[dict] = []
    for pair in data.get("stat_status_pairs", []):
        stat = pair.get("stat") or {}
        slug = stat.get("question__title_slug") or ""
        frontend_id = stat.get("frontend_question_id") or ""
        if not slug or stat.get("question__hide"):
            continue
        if pair.get("paid_only"):
            continue
        level = (pair.get("difficulty") or {}).get("level")
        if level not in (1, 2):
            continue
        if not str(frontend_id).isdigit():  # 只留常规题号，排除 LCP/剑指 Offer
            continue
        candidates.append(
            {
                "slug": slug,
                "frontend_id": str(frontend_id),
                "title": stat.get("question__title") or "",
                "total_acs": int(stat.get("total_acs") or 0),
                "frequency": int(pair.get("frequency") or 0),
                "level": level,
            }
        )
    return candidates


def select_slugs(
    candidates: list[dict], top_n: int, limit: int
) -> tuple[list[str], list[dict]]:
    """选出需要 GraphQL 补全的 slug 集合 + 最终入选顺序。

    返回 (slugs_to_fetch, final_slugs)。
    final_slugs 先填 curated，再按 total_acs 补 tag 命中者，最后补剩余榜。
    """
    by_slug = {c["slug"]: c for c in candidates}
    by_acs = sorted(candidates, key=lambda c: (-c["total_acs"], c["frontend_id"]))

    slugs_to_fetch: list[str] = []
    seen: set[str] = set()

    def _add_to_fetch(slug: str) -> None:
        if slug in seen:
            return
        seen.add(slug)
        slugs_to_fetch.append(slug)

    for slug in CURATED_SLUGS:
        if slug in by_slug:
            _add_to_fetch(slug)
    for c in by_acs[:top_n]:
        _add_to_fetch(c["slug"])

    # 最终入选：curated 优先，随后按 acs 榜补足 limit
    final: list[str] = []
    final_set: set[str] = set()

    def _pick(slug: str) -> None:
        if slug in final_set or len(final) >= limit:
            return
        final_set.add(slug)
        final.append(slug)

    for slug in CURATED_SLUGS:
        if slug in by_slug:
            _pick(slug)
    for c in by_acs:
        if len(final) >= limit:
            break
        if c["slug"] not in final_set:
            _pick(c["slug"])

    return slugs_to_fetch, final


def fetch_details(
    slugs: list[str],
    cache_dir: Path,
    refresh: bool,
    proxy: str | None,
    timeout: int,
    concurrency: int,
) -> dict[str, dict]:
    """并发拉 GraphQL 详情，成功结果缓存到 cache_dir/gql/{slug}.json。"""
    gql_cache = cache_dir / "gql"
    gql_cache.mkdir(parents=True, exist_ok=True)
    details: dict[str, dict] = {}

    def _one(slug: str) -> tuple[str, dict | None]:
        cache_file = gql_cache / f"{slug}.json"
        if not refresh and cache_file.exists():
            try:
                return slug, json.loads(cache_file.read_text("utf-8"))
            except Exception:  # noqa: BLE001 — 缓存损坏则重拉
                pass
        try:
            q = fetch_with_retry(
                graphql_question, slug, timeout, proxy, attempts=3, base_delay=1.0
            )
        except Exception:  # noqa: BLE001 — 单题失败不阻塞整体
            return slug, None
        if not q:
            return slug, None
        try:
            cache_file.write_text(
                json.dumps(q, ensure_ascii=False, indent=1), "utf-8"
            )
        except Exception:  # noqa: BLE001 — 缓存写失败不影响结果
            pass
        return slug, q

    done = 0
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = {pool.submit(_one, s): s for s in slugs}
        for fut in as_completed(futures):
            slug, q = fut.result()
            done += 1
            if q:
                details[slug] = q
            if done % 50 == 0 or done == len(slugs):
                print(
                    f"  [details] {done}/{len(slugs)} done, "
                    f"ok={len(details)}",
                    file=sys.stderr,
                )
    return details


def build_records(
    candidates: list[dict],
    final_slugs: list[str],
    details: dict[str, dict],
) -> list[dict]:
    by_slug = {c["slug"]: c for c in candidates}
    records: list[dict] = []
    for slug in final_slugs:
        c = by_slug[slug]
        q = details.get(slug)
        if q:
            title = q.get("translatedTitle") or q.get("title") or c["title"]
            title_en = q.get("title") or c["title"]
            diff = (q.get("difficulty") or "").lower()
            if diff not in DIFFICULTY_ORDER:
                diff = DIFFICULTY_LEVEL_TO_STR.get(c["level"], "easy")
            tags = q.get("topicTags") or []
            topic_slugs = [t.get("slug") for t in tags if t.get("slug")]
            topics = [
                (t.get("translatedName") or t.get("name"))
                for t in tags
                if t.get("slug")
            ]
            zh = q.get("translatedContent") or ""
            en = q.get("content") or ""
            description = html_to_text(zh or en)
            examples = parse_examples(zh, en)
        else:
            title = c["title"]
            title_en = c["title"]
            diff = DIFFICULTY_LEVEL_TO_STR.get(c["level"], "easy")
            topic_slugs = []
            topics = []
            description = ""
            examples = []

        records.append(
            {
                "frontend_id": c["frontend_id"],
                "title": title,
                "title_en": title_en,
                "title_slug": slug,
                "difficulty": diff,
                "paid_only": False,
                "total_acs": c["total_acs"],
                "frequency": c["frequency"],
                "topics": topics,
                "topic_slugs": topic_slugs,
                "description": description,
                "examples": examples,
                "url": f"https://leetcode.cn/problems/{slug}/",
            }
        )

    # 稳定排序：难度 easy<medium<hard，同级按题号
    records.sort(
        key=lambda r: (
            DIFFICULTY_ORDER.get(r["difficulty"], 2),
            int(r["frontend_id"]) if r["frontend_id"].isdigit() else 999999,
        )
    )
    return records


def validate(records: list[dict], min_count: int) -> None:
    required = ("frontend_id", "title", "title_slug", "difficulty")
    bad = [r for r in records if not all(r.get(k) for k in required)]
    if len(records) < min_count or bad:
        print(
            f"ERROR: records={len(records)} (min {min_count}), "
            f"missing-required={len(bad)}",
            file=sys.stderr,
        )
        sys.exit(1)
    assert all(r["difficulty"] in DIFFICULTY_ORDER for r in records)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export offline coding problem bank from leetcode.cn "
        "into data/problems.json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Proxies: set http_proxy/https_proxy env vars, or pass --proxy.\n"
            "Cache: data/.cache/ (set --refresh to ignore it)."
        ),
    )
    parser.add_argument("--limit", type=int, default=150, help="max records (default 150)")
    parser.add_argument("--min", type=int, default=100, help="min records required (default 100)")
    parser.add_argument("--top-n", type=int, default=250, help="total_acs top-N candidate pool (default 250)")
    parser.add_argument("--refresh", action="store_true", help="ignore cache and refetch")
    parser.add_argument("--concurrency", type=int, default=6, help="graphql workers (default 6)")
    parser.add_argument("--timeout", type=int, default=20, help="per-request timeout s (default 20)")
    parser.add_argument("--proxy", default=None, help="explicit proxy URL (else env vars)")
    parser.add_argument(
        "--out",
        default=None,
        help="output path (default: <agent pkg>/data/problems.json)",
    )
    args = parser.parse_args()

    if not 100 <= args.limit <= 200:
        parser.error("--limit must be within [100, 200]")

    pkg_dir = Path(__file__).resolve().parents[1]  # .../src/agent
    data_dir = Path(args.out).resolve() if args.out else pkg_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    out_path = data_dir / "problems.json"
    cache_dir = data_dir / ".cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    proxy = args.proxy or os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY")

    print(f"[1/4] fetching problem list: {PROBLEMS_API}", file=sys.stderr)
    list_cache = cache_dir / "problems_all.json"
    if not args.refresh and list_cache.exists():
        try:
            list_data = json.loads(list_cache.read_text("utf-8"))
            print("  (cached)", file=sys.stderr)
        except Exception:  # noqa: BLE001
            list_data = None
    else:
        list_data = None
    if list_data is None:
        list_data = fetch_with_retry(
            lambda: http_get_json(PROBLEMS_API, args.timeout, proxy),
            attempts=3,
            base_delay=1.5,
        )
        try:
            list_cache.write_text(
                json.dumps(list_data, ensure_ascii=False), "utf-8"
            )
        except Exception:  # noqa: BLE001
            pass

    num_total = list_data.get("num_total", "?")
    candidates = process_problem_list(list_data)
    print(
        f"  num_total={num_total}, easy/medium candidates={len(candidates)}",
        file=sys.stderr,
    )

    print("[2/4] selecting curated + top-acs slugs", file=sys.stderr)
    slugs_to_fetch, final_slugs = select_slugs(
        candidates, top_n=args.top_n, limit=args.limit
    )
    print(
        f"  fetch pool={len(slugs_to_fetch)} (curated={len(CURATED_SLUGS)}), "
        f"target final={len(final_slugs)}",
        file=sys.stderr,
    )

    print("[3/4] enriching via graphql questionData (best-effort)", file=sys.stderr)
    details = fetch_details(
        slugs_to_fetch,
        cache_dir,
        refresh=args.refresh,
        proxy=proxy,
        timeout=args.timeout,
        concurrency=args.concurrency,
    )
    print(f"  details ok={len(details)}/{len(slugs_to_fetch)}", file=sys.stderr)

    print("[4/4] building records & writing json", file=sys.stderr)
    records = build_records(candidates, final_slugs, details)
    validate(records, args.min)

    meta = {
        "schema_version": 1,
        "source": "leetcode.cn",
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "counts": {
            "total": len(records),
            "easy": sum(1 for r in records if r["difficulty"] == "easy"),
            "medium": sum(1 for r in records if r["difficulty"] == "medium"),
            "hard": sum(1 for r in records if r["difficulty"] == "hard"),
            "with_description": sum(1 for r in records if r["description"]),
            "with_topics": sum(1 for r in records if r["topic_slugs"]),
            "with_examples": sum(1 for r in records if r["examples"]),
        },
        "note": (
            "Offline problem bank for the 'hand-code' round. Descriptions are "
            "best-effort; fields frontend_id/title_slug/difficulty are always "
            "present. Regenerate with scripts/export_problems.py (see data/README.md)."
        ),
    }
    payload = {"meta": meta, "problems": records}
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1) + "\n", "utf-8"
    )
    print(f"\nWrote {len(records)} records -> {out_path}", file=sys.stderr)
    print(json.dumps(meta["counts"], ensure_ascii=False, indent=2), file=sys.stderr)

    sample = records[0]
    print("\nSample record:", file=sys.stderr)
    print(json.dumps(sample, ensure_ascii=False, indent=2), file=sys.stderr)


if __name__ == "__main__":
    main()
