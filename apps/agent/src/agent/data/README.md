# 离线手撕代码题库（data/problems.json）

AI 模拟面试官平台"手撕代码"环节的离线题源：**16h 内不做运行时抓力扣**，
一次性导出精选 easy/medium 高频算法题，随仓库提交，运行时零网络依赖。

## 文件

| 文件 | 说明 |
|---|---|
| `problems.json` | 题库本体（150 题，含题面/示例/topics） |
| `export_problems.py` | 生成脚本（位于 `../scripts/`） |
| `.cache/` | 网络响应缓存（题单 + 每题 GraphQL），不提交，重跑加速用 |

## Schema

顶层为 `{ "meta": {...}, "problems": [...] }`：

```jsonc
{
  "meta": {
    "schema_version": 1,
    "source": "leetcode.cn",
    "exported_at": "2026-08-30T07:44:12Z",
    "counts": { "total": 150, "easy": 50, "medium": 100, "hard": 0,
                "with_description": 150, "with_topics": 150, "with_examples": 150 }
  },
  "problems": [
    {
      "frontend_id": "1",            // 题号（纯数字字符串；LCP/剑指 Offer 等特殊编号已排除）
      "title": "两数之和",            // 中文题名（无中文时回退英文）
      "title_en": "Two Sum",         // 英文题名
      "title_slug": "two-sum",       // 力扣 slug，唯一标识
      "difficulty": "easy",          // easy | medium | hard
      "paid_only": false,            // 本库恒为 false（已过滤付费题）
      "total_acs": 7718433,          // 通过人数（频率代理）
      "frequency": 0,                // 力扣题单 frequency（0-100，可能为 0）
      "topics": ["数组", "哈希表"],    // 标签展示名（中文优先）
      "topic_slugs": ["array", "hash-table"],  // 标签 slug，用于程序化过滤
      "description": "给定一个整数数组 `nums` ...", // 题面纯文本（尽力而为，可能为空串）
      "examples": [{"input": "...", "output": "..."}], // 尽力解析，可能为 []
      "url": "https://leetcode.cn/problems/two-sum/"
    }
  ]
}
```

**必须字段**：`frontend_id` / `title_slug` / `difficulty`（验收保证 ≥100 条合法记录）。
`description` / `examples` 是尽力而为：GraphQL 拿不到就为空，不阻塞生成。

## 如何重新生成

```bash
# 1) 联网（本环境需要代理）
export https_proxy=http://127.0.0.1:7890 http_proxy=http://127.0.0.1:7890

# 2) 运行（默认输出 150 题到本目录 problems.json）
python3 scripts/export_problems.py

# 常用参数
python3 scripts/export_problems.py --limit 120 --min 100   # 控制题量
python3 scripts/export_problems.py --refresh               # 忽略缓存强制重拉
python3 scripts/export_problems.py --concurrency 8         # GraphQL 并发
```

脚本是**纯标准库**（urllib），无第三方依赖；幂等、可重跑：

- 题单响应（`/api/problems/all/`）与每题 GraphQL 结果缓存到 `.cache/`，
  重跑不发重复请求（`--refresh` 强制重拉）；
- 单题 GraphQL 失败只跳过该题题面，题目本身仍按题单字段保留；
- 输出记录按 `(difficulty, frontend_id)` 稳定排序，多次运行数据一致。

### 流程

1. `GET https://leetcode.cn/api/problems/all/` 拉全量题单（~4400 题）；
2. 过滤：非付费、未隐藏、难度 easy/medium、`frontend_id` 纯数字；
3. 精选：内置 **curated 高频题单**（`CURATED_SLUGS`，覆盖 array / hash-table /
   two-pointers / binary-search / sliding-window / stack / heap / linked-list /
   tree / bfs / dfs / dp / backtracking / greedy 等经典 tag）优先，不足按
   `total_acs` 榜补齐到 100~150 题；
4. `POST https://leetcode.cn/graphql`（`questionData`，按 titleSlug）尽力取
   中文题面/示例/topics。

## 已知取舍（诚实标注）

- **题面为中文**（`translatedContent`），英文题面在 `title_en`；无中文题面的
  题目回退英文题名。
- `description` 是 HTML 转纯文本的**尽力解析**，代码块转成 ``` 围栏，格式
  可能不完美但不影响 LLM 阅读理解。
- `examples` 从题面 `<pre>` 或新版 `example-block` 结构正则解析"输入/输出"，
  个别题目可能解析不到（当前 150/150）。
- `topics` 来自力扣官方 tag（中文优先）；若某题 GraphQL 失败则 `topics` 为空，
  `topic_slugs` 为空。
- 反爬/条款：仅一次性导出公开题单 + 公开题面，随仓库提交后不再请求力扣；
  生成脚本只在**显式重跑**时联网。
