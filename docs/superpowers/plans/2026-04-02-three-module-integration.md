# 三模块整合实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 TrendRadar 的热榜和 RSS 功能整合到信源汇总项目中，形成新闻汇总+热榜+RSS订阅三模块统一的 Flask 平台。

**Architecture:** 以信源汇总的 Flask 框架为基础，采用扁平模块化结构（modules/news, modules/hotlist, modules/rss），各模块独立数据库、独立 Blueprint。守护进程 scheduler.py 统一调度三个模块的采集任务。

**Tech Stack:** Python 3.10+, Flask, httpx, requests, feedparser, sentence-transformers, chromadb, litellm(可选), pyyaml

**Spec:** `docs/superpowers/specs/2026-04-02-three-module-integration-design.md`

---

## 文件清单

### 新建文件

| 文件 | 职责 |
|------|------|
| `config.yaml` | 全局配置 |
| `requirements.txt` | 依赖列表 |
| `app.py` | Flask 应用入口 |
| `scheduler.py` | 统一调度守护进程 |
| `utils/__init__.py` | 包初始化 |
| `utils/config.py` | 配置加载 |
| `utils/time.py` | 时间工具 |
| `modules/__init__.py` | 包初始化 |
| `modules/news/__init__.py` | 包初始化 |
| `modules/news/db.py` | news.db CRUD |
| `modules/news/aggregator.py` | 新闻采集 |
| `modules/news/vector.py` | 语义向量引擎 |
| `modules/news/routes.py` | 新闻 API 路由 |
| `modules/hotlist/__init__.py` | 包初始化 |
| `modules/hotlist/db.py` | hotlist.db CRUD |
| `modules/hotlist/fetcher.py` | 热榜抓取 |
| `modules/hotlist/routes.py` | 热榜 API 路由 |
| `modules/rss/__init__.py` | 包初始化 |
| `modules/rss/db.py` | rss.db CRUD + 订阅源管理 |
| `modules/rss/parser.py` | RSS 解析 |
| `modules/rss/fetcher.py` | RSS 抓取 |
| `modules/rss/routes.py` | RSS API 路由 |
| `ai/__init__.py` | 包初始化 |
| `ai/client.py` | AI 客户端封装 |
| `templates/index.html` | 统一 Web UI |

### 删除文件

| 文件 | 原因 |
|------|------|
| `frontend/` 目录 | 未完成的 Next.js 迁移，不再需要 |
| `ak_source_aggregator.py` | 已拆分为 modules/news/db.py + modules/news/aggregator.py |
| `news_viewer.py` | 已拆分为 app.py + modules/news/routes.py + templates/index.html |
| `news_vector.py` | 已移至 modules/news/vector.py |
| `scheduler_runner.py` | 已替换为统一 scheduler.py |

### 参考源文件（只读，不修改）

| 文件 | 用途 |
|------|------|
| `ak_source_aggregator.py` | NewsDB + AKSourceAggregator 提取源 |
| `news_viewer.py` | 路由和 HTML 提取源 |
| `news_vector.py` | 向量引擎移植源 |
| `scheduler_runner.py` | 调度逻辑移植源 |
| `C:/Users/35368/TrendRadar/trendradar/crawler/fetcher.py` | 热榜抓取移植参考 |
| `C:/Users/35368/TrendRadar/trendradar/crawler/rss/fetcher.py` | RSS 抓取移植参考 |
| `C:/Users/35368/TrendRadar/trendradar/crawler/rss/parser.py` | RSS 解析移植参考 |
| `C:/Users/35368/TrendRadar/trendradar/ai/client.py` | AI 客户端移植参考 |
| `C:/Users/35368/TrendRadar/trendradar/ai/filter.py` | AI 过滤移植参考 |
| `C:/Users/35368/TrendRadar/trendradar/ai/analyzer.py` | AI 分析移植参考 |
| `C:/Users/35368/TrendRadar/trendradar/utils/time.py` | 时间工具移植参考 |

---

## Task 1: 项目脚手架

**Files:**
- Create: `config.yaml`
- Create: `requirements.txt`
- Create: `utils/__init__.py`
- Create: `utils/config.py`
- Create: `utils/time.py`
- Create: `modules/__init__.py`
- Create: `modules/news/__init__.py`
- Create: `modules/hotlist/__init__.py`
- Create: `modules/rss/__init__.py`
- Create: `ai/__init__.py`
- Create: `data/.gitkeep`

- [ ] **Step 1: 创建目录结构**

```bash
cd "C:/Users/35368/Desktop/信源汇总"
mkdir -p utils modules/news modules/hotlist modules/rss ai data templates
touch utils/__init__.py modules/__init__.py modules/news/__init__.py modules/hotlist/__init__.py modules/rss/__init__.py ai/__init__.py data/.gitkeep
```

- [ ] **Step 1b: 创建 .gitignore**

```gitignore
data/*.db
data/chroma_db/
__pycache__/
*.pyc
.env
```

- [ ] **Step 1c: 迁移现有 news.db**

```bash
# 如果项目根目录已有 news.db，迁移到 data/ 目录
if [ -f news.db ]; then cp news.db data/news.db; fi
```

- [ ] **Step 2: 创建 requirements.txt**

```txt
flask>=3.0
httpx>=0.27
requests>=2.31
feedparser>=6.0
chromadb>=0.4
sentence-transformers>=2.2
pyyaml>=6.0
litellm>=1.0
```

- [ ] **Step 3: 创建 config.yaml**

```yaml
scheduler:
  news_interval: 600
  hotlist_interval: 300
  rss_interval: 1800
  purge_days: 7

hotlist:
  platforms:
    - weibo
    - zhihu
    - bilibili-hot-search
    - toutiao
    - baidu
    - wallstreetcn-hot
    - thepaper
    - cls-hot
    - ifeng
    - douyin
    - tieba
  api_url: "https://newsnow.busiyi.world/api/s"

ai:
  enabled: false
  model: "deepseek/deepseek-chat"
  api_key: ""
  base_url: ""
  interests: ""

vector:
  model: "BAAI/bge-small-zh-v1.5"
  dedup_threshold: 0.78
  cluster_threshold: 0.85
```

- [ ] **Step 4: 创建 utils/config.py**

```python
"""配置加载工具"""
import os
import yaml


def load_config(config_path=None):
    """加载 config.yaml 配置文件"""
    if config_path is None:
        config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.yaml")

    if not os.path.exists(config_path):
        return {}

    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
```

- [ ] **Step 5: 创建 utils/time.py**

从 `C:/Users/35368/TrendRadar/trendradar/utils/time.py` 移植核心时间函数。保留以下函数：
- `get_configured_time(timezone)` - 获取当前时间
- `format_iso_time_friendly(iso_str)` - ISO 时间转友好显示
- `is_within_days(iso_str, days, timezone)` - 判断是否在指定天数内

- [ ] **Step 6: 提交**

```bash
git add config.yaml requirements.txt utils/ modules/__init__.py modules/news/__init__.py modules/hotlist/__init__.py modules/rss/__init__.py ai/__init__.py data/.gitkeep
git commit -m "feat: 项目脚手架 - 目录结构、配置、依赖"
```

---

## Task 2: 新闻模块 - 数据库层

**Files:**
- Read: `ak_source_aggregator.py`（提取 NewsDB 类）
- Create: `modules/news/db.py`

- [ ] **Step 1: 从 ak_source_aggregator.py 提取 NewsDB 类到 modules/news/db.py**

从 `ak_source_aggregator.py` 中提取 `NewsDB` 类（约 200 行），做以下适配：
- 构造函数接受 `db_path` 参数（默认 `data/news.db`）
- 初始化时启用 WAL 模式：`conn.execute("PRAGMA journal_mode=WAL")`
- 自动创建 `data/` 目录
- 保留所有方法：`insert_many`, `purge_old`, `get_all`, `get_count`, `get_source_stats`, `get_category_stats`, `get_cluster_list`, `get_cluster_news`, `migrate_category_to_json`, `reclassify_all`

- [ ] **Step 2: 验证 db.py 可独立导入**

```bash
cd "C:/Users/35368/Desktop/信源汇总"
python -c "from modules.news.db import NewsDB; print('NewsDB import OK')"
```

- [ ] **Step 3: 提交**

```bash
git add modules/news/db.py
git commit -m "feat: 新闻模块 - 提取 NewsDB 数据库层"
```

---

## Task 3: 新闻模块 - 采集器 + 向量引擎

**Files:**
- Read: `ak_source_aggregator.py`（提取 AKSourceAggregator 类）
- Read: `news_vector.py`（整体移植）
- Create: `modules/news/aggregator.py`
- Create: `modules/news/vector.py`

- [ ] **Step 1: 从 ak_source_aggregator.py 提取 AKSourceAggregator 到 modules/news/aggregator.py**

从 `ak_source_aggregator.py` 中提取 `AKSourceAggregator` 类（约 400 行），做以下适配：
- `from modules.news.db import NewsDB`（替换原来的直接 import）
- 保留所有 8 个新闻源采集方法
- 保留 `fetch_all()`, `fetch_and_store()` 方法
- 构造函数接受 `db` 参数（NewsDB 实例）

- [ ] **Step 2: 将 news_vector.py 移植到 modules/news/vector.py**

将 `news_vector.py` 整体复制到 `modules/news/vector.py`，做以下适配：
- 修改 import：`from modules.news.db import NewsDB`（如需要）
- 构造函数中 `db_path` 默认值改为 `data/news.db`
- `chroma_dir` 默认值改为 `data/chroma_db`

- [ ] **Step 3: 验证两个模块可独立导入**

```bash
python -c "from modules.news.aggregator import AKSourceAggregator; print('Aggregator OK')"
python -c "from modules.news.vector import NewsVectorEngine; print('VectorEngine OK')"
```

- [ ] **Step 4: 提交**

```bash
git add modules/news/aggregator.py modules/news/vector.py
git commit -m "feat: 新闻模块 - 采集器和向量引擎"
```

---

## Task 4: 新闻模块 - Flask 路由

**Files:**
- Read: `news_viewer.py`（提取新闻相关路由）
- Create: `modules/news/routes.py`

- [ ] **Step 1: 从 news_viewer.py 提取新闻 API 路由到 modules/news/routes.py**

从 `news_viewer.py` 中提取以下路由逻辑，封装为 Flask Blueprint：

```python
from flask import Blueprint, request, jsonify

news_bp = Blueprint("news", __name__)

# 路由列表（从 news_viewer.py 提取逻辑）:
# GET  /api/news              → 新闻列表（分页+筛选）
# GET  /api/news/status       → 数据库统计
# GET  /api/news/semantic_search → 语义搜索
# GET  /api/news/categories   → 分类统计
# POST /api/news/fetch        → 手动触发采集
# GET  /api/news/clusters     → 聚类列表
# GET  /api/news/cluster/<id> → 聚类详情
```

关键适配点：
- `NewsDB` 实例在模块级别创建，或通过函数参数传入
- `NewsVectorEngine` 延迟初始化（与现有逻辑一致）
- 保留现有的查询参数处理逻辑（source, category, keyword, page, date 等）

- [ ] **Step 2: 验证 Blueprint 可注册**

```bash
python -c "from modules.news.routes import news_bp; print(f'Blueprint: {news_bp.name}, routes: {len(news_bp.deferred_functions)}')"
```

- [ ] **Step 3: 提交**

```bash
git add modules/news/routes.py
git commit -m "feat: 新闻模块 - Flask Blueprint 路由"
```

---

## Task 5: 热榜模块 - 数据库层 + 抓取器

**Files:**
- Read: `C:/Users/35368/TrendRadar/trendradar/crawler/fetcher.py`
- Create: `modules/hotlist/db.py`
- Create: `modules/hotlist/fetcher.py`

- [ ] **Step 1: 创建 modules/hotlist/db.py**

实现 `HotlistDB` 类，包含：

```python
"""热榜数据库操作"""
import os
import sqlite3
from datetime import datetime, timedelta


class HotlistDB:
    def __init__(self, db_path="data/hotlist.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS hot_items (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                url TEXT,
                platform TEXT NOT NULL,
                platform_name TEXT,
                hot_rank INTEGER,
                hot_score TEXT,
                crawl_time DATETIME NOT NULL,
                first_time DATETIME,
                last_time DATETIME,
                appear_count INTEGER DEFAULT 1,
                UNIQUE(url, platform, crawl_time)
            );
            CREATE TABLE IF NOT EXISTS crawl_batches (
                id INTEGER PRIMARY KEY,
                crawl_time DATETIME NOT NULL,
                platform_count INTEGER,
                item_count INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_hot_platform ON hot_items(platform);
            CREATE INDEX IF NOT EXISTS idx_hot_crawl_time ON hot_items(crawl_time);
        """)
        conn.close()

    def insert_batch(self, items, crawl_time):
        """插入一批热榜数据，并更新已有条目的 appear_count

        逻辑：
        - 每次采集为当前时间点的条目 INSERT 新行（UNIQUE(url, platform, crawl_time) 保证同批次不重复）
        - 如果某个 URL+platform 之前已存在，新行的 appear_count 继承累计值 +1，
          first_time 保持首次发现时间不变
        """
        conn = self._get_conn()
        inserted = 0

        for item in items:
            # 检查是否已有相同 URL+platform 的条目（取最新一条）
            existing = conn.execute(
                "SELECT id, appear_count, first_time FROM hot_items WHERE url = ? AND platform = ? ORDER BY crawl_time DESC LIMIT 1",
                (item["url"], item["platform"])
            ).fetchone()

            # 新行继承已有的累计值
            if existing:
                new_count = existing["appear_count"] + 1
                first_time = existing["first_time"]  # 保持首次发现时间
            else:
                new_count = 1
                first_time = crawl_time

            try:
                conn.execute(
                    "INSERT INTO hot_items (title, url, platform, platform_name, hot_rank, hot_score, crawl_time, first_time, last_time, appear_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (item["title"], item["url"], item["platform"], item["platform_name"],
                     item.get("hot_rank"), item.get("hot_score", ""), crawl_time, first_time, crawl_time, new_count)
                )
                inserted += 1
            except sqlite3.IntegrityError:
                pass  # 忽略重复

        # 记录批次
        platform_count = len(set(item["platform"] for item in items))
        conn.execute(
            "INSERT INTO crawl_batches (crawl_time, platform_count, item_count) VALUES (?, ?, ?)",
            (crawl_time, platform_count, inserted)
        )

        conn.commit()
        conn.close()
        return inserted

    def get_items(self, platform=None, hours=24, page=1, page_size=30):
        """获取热榜列表（分页）"""
        conn = self._get_conn()
        where = "WHERE crawl_time >= ?"
        params = [(datetime.now() - timedelta(hours=hours)).isoformat()]

        if platform:
            where += " AND platform = ?"
            params.append(platform)

        # 获取每个条目的最新状态
        total = conn.execute(
            f"SELECT COUNT(DISTINCT title || platform) FROM hot_items {where}", params
        ).fetchone()[0]

        rows = conn.execute(f"""
            SELECT h.* FROM hot_items h
            INNER JOIN (
                SELECT title, platform, MAX(crawl_time) as max_time
                FROM hot_items {where}
                GROUP BY title, platform
            ) latest ON h.title = latest.title AND h.platform = latest.platform AND h.crawl_time = latest.max_time
            ORDER BY h.hot_rank ASC
            LIMIT ? OFFSET ?
        """, params + [page_size, (page - 1) * page_size]).fetchall()

        conn.close()
        return [dict(r) for r in rows], total

    def get_platform_stats(self):
        """获取各平台统计"""
        conn = self._get_conn()
        rows = conn.execute("""
            SELECT platform, platform_name, COUNT(*) as count, MAX(crawl_time) as latest
            FROM hot_items
            WHERE crawl_time >= datetime('now', '-1 day')
            GROUP BY platform
            ORDER BY count DESC
        """).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_last_crawl_time(self):
        """获取最近一次采集时间"""
        conn = self._get_conn()
        row = conn.execute("SELECT MAX(crawl_time) as t FROM crawl_batches").fetchone()
        conn.close()
        return row["t"] if row and row["t"] else None

    def purge_old(self, days=7):
        """清理过期数据"""
        conn = self._get_conn()
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        count = conn.execute("DELETE FROM hot_items WHERE crawl_time < ?", (cutoff,)).rowcount
        conn.execute("DELETE FROM crawl_batches WHERE crawl_time < ?", (cutoff,))
        conn.commit()
        conn.close()
        return count
```

- [ ] **Step 2: 创建 modules/hotlist/fetcher.py**

从 TrendRadar 的 `trendradar/crawler/fetcher.py` 移植 `DataFetcher` 类，简化后移除 TrendRadar 特有的导入。核心逻辑保持不变（`fetch_data`, `crawl_websites`），去掉与 TrendRadar storage 的耦合。

关键适配：
- 去掉 `from trendradar.*` 导入
- `crawl_websites` 返回简化的结果（列表形式，直接可传给 HotlistDB.insert_batch）
- 新增 `fetch_and_store(db, config)` 便捷方法

```python
"""热榜数据抓取器（从 TrendRadar 移植并简化）"""
import json
import random
import time
from typing import Dict, List, Tuple, Optional, Union
import requests


# 平台 ID → 显示名称映射
PLATFORM_NAMES = {
    "toutiao": "今日头条",
    "baidu": "百度热搜",
    "wallstreetcn-hot": "华尔街见闻",
    "thepaper": "澎湃新闻",
    "bilibili-hot-search": "B站热搜",
    "cls-hot": "财联社热门",
    "ifeng": "凤凰网",
    "tieba": "贴吧",
    "weibo": "微博",
    "douyin": "抖音",
    "zhihu": "知乎",
}


class DataFetcher:
    """热榜数据抓取器"""

    DEFAULT_API_URL = "https://newsnow.busiyi.world/api/s"
    DEFAULT_HEADERS = {
        "User-Agent": "Mozilla/5.0 ...",  # 保留原 TrendRadar headers
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Connection": "keep-alive",
        "Cache-Control": "no-cache",
    }

    def __init__(self, api_url=None, proxy_url=None):
        self.api_url = api_url or self.DEFAULT_API_URL
        self.proxy_url = proxy_url

    # fetch_data() - 从 TrendRadar 直接移植，逻辑完全一致
    # crawl_websites() - 从 TrendRadar 直接移植，逻辑完全一致
    # (完整代码见 TrendRadar 源文件，此处移植时去掉 trendradar 导入)

    def fetch_all_platforms(self, platform_ids=None):
        """抓取所有指定平台，返回可入库的扁平列表"""
        if platform_ids is None:
            platform_ids = list(PLATFORM_NAMES.keys())

        ids_list = [(pid, PLATFORM_NAMES.get(pid, pid)) for pid in platform_ids]
        results, id_to_name, failed = self.crawl_websites(ids_list)

        items = []
        for platform_id, entries in results.items():
            for title, info in entries.items():
                items.append({
                    "title": title,
                    "url": info.get("url", ""),
                    "platform": platform_id,
                    "platform_name": id_to_name.get(platform_id, platform_id),
                    "hot_rank": info["ranks"][0] if info.get("ranks") else 0,
                    "hot_score": "",
                })

        return items, failed
```

- [ ] **Step 3: 验证模块可导入**

```bash
python -c "from modules.hotlist.db import HotlistDB; from modules.hotlist.fetcher import DataFetcher; print('Hotlist modules OK')"
```

- [ ] **Step 4: 提交**

```bash
git add modules/hotlist/db.py modules/hotlist/fetcher.py
git commit -m "feat: 热榜模块 - 数据库层和抓取器"
```

---

## Task 6: 热榜模块 - Flask 路由

**Files:**
- Create: `modules/hotlist/routes.py`

- [ ] **Step 1: 创建 modules/hotlist/routes.py**

```python
from flask import Blueprint, request, jsonify
from datetime import datetime
from modules.hotlist.db import HotlistDB
from modules.hotlist.fetcher import DataFetcher

hotlist_bp = Blueprint("hotlist", __name__)
db = HotlistDB()

@hotlist_bp.route("/api/hotlist", methods=["GET"])
def get_hotlist():
    platform = request.args.get("platform")
    hours = int(request.args.get("hours", 24))
    page = int(request.args.get("page", 1))
    page_size = int(request.args.get("page_size", 30))
    items, total = db.get_items(platform=platform, hours=hours, page=page, page_size=page_size)
    return jsonify({"items": items, "total": total, "page": page, "page_size": page_size})

@hotlist_bp.route("/api/hotlist/platforms", methods=["GET"])
def get_platforms():
    stats = db.get_platform_stats()
    return jsonify(stats)

@hotlist_bp.route("/api/hotlist/fetch", methods=["POST"])
def manual_fetch():
    # 调用 fetcher 抓取并存入数据库
    ...
```

- [ ] **Step 2: 提交**

```bash
git add modules/hotlist/routes.py
git commit -m "feat: 热榜模块 - Flask Blueprint 路由"
```

---

## Task 7: RSS 模块 - 解析器 + 数据库层

**Files:**
- Read: `C:/Users/35368/TrendRadar/trendradar/crawler/rss/parser.py`
- Create: `modules/rss/parser.py`
- Create: `modules/rss/db.py`

- [ ] **Step 1: 移植 RSS 解析器到 modules/rss/parser.py**

从 TrendRadar 的 `trendradar/crawler/rss/parser.py` 整体移植（约 330 行），做以下适配：
- 去掉 `from trendradar.*` 导入
- `ParsedRSSItem` dataclass 和 `RSSParser` 类完整保留
- 所有解析方法（RSS 2.0, Atom, JSON Feed）完整保留

- [ ] **Step 2: 创建 modules/rss/db.py**

实现 `RSSDB` 类，包含订阅源管理和文章 CRUD：

```python
"""RSS 数据库操作"""
import os
import re
import sqlite3
from datetime import datetime, timedelta


def generate_feed_id(name: str) -> str:
    """从名称生成 URL-friendly slug ID"""
    slug = re.sub(r'[^\w\s-]', '', name.lower())
    slug = re.sub(r'[\s_]+', '-', slug).strip('-')
    return slug or "feed"


class RSSDB:
    def __init__(self, db_path="data/rss.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS rss_feeds (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                url TEXT NOT NULL,
                format TEXT DEFAULT 'rss',
                enabled INTEGER DEFAULT 1,
                max_items INTEGER DEFAULT 20,
                max_age_days INTEGER DEFAULT 7,
                last_crawl_time DATETIME,
                last_error TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS rss_items (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                feed_id TEXT NOT NULL REFERENCES rss_feeds(id),
                url TEXT,
                author TEXT,
                summary TEXT,
                published_at DATETIME,
                crawl_time DATETIME NOT NULL,
                UNIQUE(url, feed_id)
            );
            CREATE INDEX IF NOT EXISTS idx_rss_feed_id ON rss_items(feed_id);
            CREATE INDEX IF NOT EXISTS idx_rss_crawl_time ON rss_items(crawl_time);
        """)
        conn.close()

    # 订阅源管理
    def get_feeds(self, enabled_only=False): ...
    def get_feed(self, feed_id): ...
    def add_feed(self, name, url, **kwargs): ...  # 自动生成 id，冲突加数字后缀
    def update_feed(self, feed_id, **kwargs): ...
    def delete_feed(self, feed_id): ...  # CASCADE 删除关联 items
    def update_feed_status(self, feed_id, error=None): ...  # 更新 last_crawl_time 和 last_error

    # 文章操作
    def insert_items(self, items, crawl_time): ...  # INSERT OR IGNORE 去重
    def get_items(self, feed_id=None, days=7, page=1, page_size=30): ...
    def get_feed_stats(self): ...

    # 清理
    def purge_old(self, days=7): ...
```

- [ ] **Step 3: 验证模块可导入**

```bash
python -c "from modules/rss.parser import RSSParser; from modules.rss.db import RSSDB; print('RSS modules OK')"
```

- [ ] **Step 4: 提交**

```bash
git add modules/rss/parser.py modules/rss/db.py
git commit -m "feat: RSS 模块 - 解析器和数据库层"
```

---

## Task 8: RSS 模块 - 抓取器 + 路由

**Files:**
- Read: `C:/Users/35368/TrendRadar/trendradar/crawler/rss/fetcher.py`
- Create: `modules/rss/fetcher.py`
- Create: `modules/rss/routes.py`

- [ ] **Step 1: 移植并适配 RSS 抓取器到 modules/rss/fetcher.py**

从 TrendRadar 的 `trendradar/crawler/rss/fetcher.py` 移植，关键适配：
- 去掉 `from trendradar.*` 导入
- 改用 `from modules.rss.parser import RSSParser`
- `RSSFeedConfig` 改为从数据库加载（而不是 YAML 配置）
- 新增 `fetch_and_store(db: RSSDB)` 方法：从 DB 读取 enabled feeds → 抓取 → 结果存回 DB

- [ ] **Step 2: 创建 modules/rss/routes.py**

```python
from flask import Blueprint, request, jsonify
from modules.rss.db import RSSDB

rss_bp = Blueprint("rss", __name__)
db = RSSDB()

# GET  /api/rss/items        → RSS 文章列表（分页+源筛选）
# GET  /api/rss/feeds        → 订阅源列表
# POST /api/rss/feeds        → 添加订阅源
# PUT  /api/rss/feeds/<id>   → 修改订阅源
# DELETE /api/rss/feeds/<id> → 删除订阅源
# POST /api/rss/fetch        → 手动触发采集
```

- [ ] **Step 3: 提交**

```bash
git add modules/rss/fetcher.py modules/rss/routes.py
git commit -m "feat: RSS 模块 - 抓取器和 Flask 路由"
```

---

## Task 9: AI 模块（可选）

**Files:**
- Read: `C:/Users/35368/TrendRadar/trendradar/ai/client.py`
- Read: `C:/Users/35368/TrendRadar/trendradar/ai/filter.py`
- Read: `C:/Users/35368/TrendRadar/trendradar/ai/analyzer.py`
- Create: `ai/client.py`
- Create: `ai/filter.py`
- Create: `ai/analyzer.py`

- [ ] **Step 1: 移植 AI 客户端到 ai/client.py**

从 TrendRadar 的 `trendradar/ai/client.py` 整体移植 `AIClient` 类（约 120 行）。
- 去掉 `from trendradar.*` 导入
- 保留 `chat()` 和 `validate_config()` 方法
- 在 `ai/client.py` 顶部添加 litellm 可选导入守卫：

```python
try:
    from litellm import completion
    HAS_LITELLM = True
except ImportError:
    HAS_LITELLM = False
    completion = None
```

- `AIClient.chat()` 在 `HAS_LITELLM=False` 时直接 raise RuntimeError 提示安装 litellm
- 在 `ai/__init__.py` 中添加 litellm 可选导入守卫：

```python
"""AI 分析模块（可选 - 需要 litellm）"""
try:
    from ai.client import AIClient
    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False
```

- [ ] **Step 2: 移植 AI 过滤器到 ai/filter.py**

从 TrendRadar 的 `trendradar/ai/filter.py` 简化移植（约 560 行，简化到约 200 行）：
- 去掉 TrendRadar 特有的文件系统 prompt 加载（改为内嵌 prompt 模板）
- 保留核心 `classify_batch()` 方法
- `from ai.client import AIClient`

- [ ] **Step 3: 移植 AI 分析器到 ai/analyzer.py**

从 TrendRadar 的 `trendradar/ai/analyzer.py` 简化移植（约 620 行，简化到约 300 行）：
- 去掉 prompt_loader 依赖（内嵌 prompt）
- 保留核心 `analyze()` 方法
- `from ai.client import AIClient`

- [ ] **Step 4: 验证模块可导入**

```bash
python -c "from ai.client import AIClient; print('AI client OK')"
```

- [ ] **Step 5: 提交**

```bash
git add ai/client.py ai/filter.py ai/analyzer.py
git commit -m "feat: AI 模块 - 客户端、过滤器、分析器"
```

---

## Task 10: 统一调度器

**Files:**
- Read: `scheduler_runner.py`（参考现有调度逻辑）
- Create: `scheduler.py`

- [ ] **Step 1: 创建 scheduler.py**

```python
"""
统一调度器 - 独立进程运行

定时调度三个模块的数据采集：新闻、热榜、RSS
"""
import logging
import os
import time
from datetime import datetime

os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_OFFLINE"] = "1"

from utils.config import load_config
from modules.news.db import NewsDB
from modules.news.aggregator import AKSourceAggregator
from modules.news.vector import NewsVectorEngine
from modules.hotlist.db import HotlistDB
from modules.hotlist.fetcher import DataFetcher
from modules.rss.db import RSSDB
from modules.rss.fetcher import RSSFetcher

logging.basicConfig(level=logging.INFO, format="%(asctime)s [scheduler] %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main():
    config = load_config()
    sched_cfg = config.get("scheduler", {})
    purge_days = sched_cfg.get("purge_days", 7)

    # 初始化各模块
    # --- 新闻模块 ---
    news_db = NewsDB()
    aggregator = AKSourceAggregator(db=news_db)
    vector_engine = None
    try:
        vector_engine = NewsVectorEngine()
        vector_engine.initialize()
        logger.info("向量引擎初始化成功")
    except Exception as e:
        logger.error("向量引擎初始化失败: %s", e)

    # --- 热榜模块 ---
    hotlist_db = HotlistDB()
    hotlist_cfg = config.get("hotlist", {})
    hotlist_fetcher = DataFetcher(api_url=hotlist_cfg.get("api_url"))

    # --- RSS 模块 ---
    rss_db = RSSDB()
    rss_fetcher = RSSFetcher()  # 从 DB 加载 feeds

    # 计时器
    timers = {
        "news": 0,
        "hotlist": 0,
        "rss": 0,
    }
    intervals = {
        "news": sched_cfg.get("news_interval", 600),
        "hotlist": sched_cfg.get("hotlist_interval", 300),
        "rss": sched_cfg.get("rss_interval", 1800),
    }

    logger.info("调度器启动: news=%ds, hotlist=%ds, rss=%ds, purge=%dd",
                intervals["news"], intervals["hotlist"], intervals["rss"], purge_days)

    # 启动时立即执行一次
    _run_all(aggregator, news_db, vector_engine, hotlist_db, hotlist_fetcher,
             rss_db, rss_fetcher, hotlist_cfg, purge_days)

    tick = 0
    while True:
        time.sleep(1)
        tick += 1

        for module in ["news", "hotlist", "rss"]:
            timers[module] += 1
            if timers[module] >= intervals[module]:
                timers[module] = 0
                _run_module(module, aggregator, news_db, vector_engine,
                           hotlist_db, hotlist_fetcher, rss_db, rss_fetcher,
                           hotlist_cfg, purge_days)


def _run_all(*args):
    """启动时运行所有模块"""
    for module in ["news", "hotlist", "rss"]:
        _run_module(module, *args)


def _run_module(module, aggregator, news_db, vector_engine,
                hotlist_db, hotlist_fetcher, rss_db, rss_fetcher,
                hotlist_cfg, purge_days):
    """运行单个模块的采集"""
    try:
        if module == "news":
            _run_news(aggregator, news_db, vector_engine, purge_days)
        elif module == "hotlist":
            _run_hotlist(hotlist_db, hotlist_fetcher, hotlist_cfg)
        elif module == "rss":
            _run_rss(rss_db, rss_fetcher)
    except Exception as e:
        logger.error("%s 采集异常: %s", module, e)


def _run_news(aggregator, db, vector_engine, purge_days):
    """新闻采集 + 向量处理"""
    result = aggregator.fetch_and_store(purge_days=purge_days)
    new_items = result.get("new_items", [])
    new_row_ids = result.get("new_row_ids", [])

    if vector_engine and new_items:
        _vector_pipeline(vector_engine, db, new_items, new_row_ids)

    # 同步清理 ChromaDB
    if vector_engine and result["purged"] > 0:
        try:
            vector_engine.sync_chroma_purge()
        except Exception as e:
            logger.error("ChromaDB 清理失败: %s", e)

    logger.info("新闻: 原始%d, 新增%d, 清理%d", result["total_raw"], result["new_added"], result["purged"])


def _vector_pipeline(vector_engine, db, items, row_ids):
    """向量处理管线：语义去重 → 分类 → 聚类 → 写入 ChromaDB

    移植自 scheduler_runner.py 的 _vector_pipeline（105-171行），关键改动：
    - 使用 db._get_conn() 代替直接 sqlite3.connect(DB_PATH)
    """
    import json

    try:
        # 语义去重（与 ChromaDB 已有条目比较）
        deduped = vector_engine.semantic_dedup(items)
        deduped_set = {(d["title"], d.get("content", "")[:100]) for d in deduped}

        # 分离保留的和要删除的
        deduped_items, deduped_row_ids = [], []
        removed_row_ids = []
        for item, rid in zip(items, row_ids):
            key = (item["title"], item.get("content", "")[:100])
            if key in deduped_set:
                deduped_items.append(item)
                deduped_row_ids.append(rid)
            else:
                removed_row_ids.append(rid)

        # 从 SQLite 删除语义重复的条目
        if removed_row_ids:
            conn = db._get_conn()
            placeholders = ",".join("?" * len(removed_row_ids))
            conn.execute(f"DELETE FROM news WHERE id IN ({placeholders})", removed_row_ids)
            conn.commit()
            conn.close()
            logger.info("语义去重: 从 SQLite 删除 %d 条", len(removed_row_ids))

        if not deduped_items:
            return

        # 分类
        categories = vector_engine.classify_items(deduped_items)

        # 聚类
        cluster_ids = vector_engine.assign_clusters(deduped_items)

        # 更新 SQLite 中的 category 和 cluster_id
        conn = db._get_conn()
        for rid, cat, cid in zip(deduped_row_ids, categories, cluster_ids):
            cat_json = json.dumps(cat, ensure_ascii=False) if isinstance(cat, list) else cat
            conn.execute("UPDATE news SET category = ?, cluster_id = ? WHERE id = ?", (cat_json, cid, rid))
        conn.commit()
        conn.close()

        # 写入 ChromaDB
        vector_engine.upsert_to_chroma(deduped_items, deduped_row_ids, categories, cluster_ids)

    except Exception as e:
        logger.error("向量处理管线异常: %s", e)


def _run_hotlist(db, fetcher, config):
    """热榜采集"""
    platforms = config.get("platforms") or None
    items, failed = fetcher.fetch_all_platforms(platforms)
    crawl_time = datetime.now().isoformat()
    inserted = db.insert_batch(items, crawl_time)
    logger.info("热榜: 抓取%d条, 入库%d条, 失败%d平台", len(items), inserted, len(failed))


def _run_rss(db, fetcher):
    """RSS 采集"""
    fetcher.fetch_and_store(db)
    logger.info("RSS: 采集完成")


if __name__ == "__main__":
    main()
```

注意：`_run_news` 中的向量处理管线逻辑从 `scheduler_runner.py` 的 `_vector_pipeline` 移植。

- [ ] **Step 2: 验证 scheduler.py 语法正确**

```bash
python -c "import ast; ast.parse(open('scheduler.py').read()); print('Syntax OK')"
```

- [ ] **Step 3: 提交**

```bash
git add scheduler.py
git commit -m "feat: 统一调度器 - 三模块定时采集"
```

---

## Task 11: Flask 应用入口

**Files:**
- Read: `news_viewer.py`（参考主页面路由逻辑）
- Create: `app.py`

- [ ] **Step 1: 创建 app.py**

```python
"""
信源汇总 - Flask 应用入口

三模块：新闻汇总 + 热榜 + RSS订阅
"""
from flask import Flask, render_template
from modules.news.routes import news_bp
from modules.hotlist.routes import hotlist_bp
from modules.rss.routes import rss_bp

app = Flask(__name__)

# 注册 Blueprint
app.register_blueprint(news_bp)
app.register_blueprint(hotlist_bp)
app.register_blueprint(rss_bp)


@app.route("/")
def index():
    return render_template("index.html")


if __name__ == "__main__":
    import webbrowser
    port = 5000
    webbrowser.open(f"http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=True)
```

- [ ] **Step 2: 提交**

```bash
git add app.py
git commit -m "feat: Flask 应用入口"
```

---

## Task 12: 统一 Web UI

**Files:**
- Read: `news_viewer.py`（提取内嵌 HTML/CSS/JS）
- Create: `templates/index.html`

- [ ] **Step 1: 从 news_viewer.py 提取 HTML 到 templates/index.html**

从 `news_viewer.py` 中提取内嵌的 HTML 模板（约 600 行），做以下改造：

1. **顶部导航栏**：添加三个 Tab（新闻汇总、热榜、RSS订阅）
2. **新闻汇总 Tab**：保留现有筛选栏和卡片列表
3. **热榜 Tab**：平台筛选 + 热榜卡片（排名、标题、平台名、热度值）
4. **RSS Tab**：订阅源筛选 + 文章卡片 + 管理订阅源按钮
5. **RSS 管理模态框**：添加/编辑/删除订阅源

关键 CSS/JS 改动：
- Tab 切换：`<div class="tab-content" id="tab-news/hotlist/rss">` + JS 切换 `display`
- 热榜 API：`fetch('/api/hotlist?...')`
- RSS API：`fetch('/api/rss/items?...')` + `fetch('/api/rss/feeds')`
- RSS 管理：`POST/PUT/DELETE /api/rss/feeds/...`
- 保留暗色主题 CSS

- [ ] **Step 2: 手动验证 Web UI**

```bash
cd "C:/Users/35368/Desktop/信源汇总"
python app.py
# 浏览器打开 http://localhost:5000
# 验证三个 Tab 切换正常
# 验证新闻列表加载正常
# 验证热榜数据加载（需要先运行 scheduler 采集数据）
# 验证 RSS 订阅源管理功能
```

- [ ] **Step 3: 提交**

```bash
git add templates/index.html
git commit -m "feat: 统一 Web UI - 三模块 Tab 界面"
```

---

## Task 13: 清理与最终验证

**Files:**
- Delete: `frontend/` 目录
- Delete: `ak_source_aggregator.py`, `news_viewer.py`, `news_vector.py`, `scheduler_runner.py`（已被模块化版本替代）
- Verify: 所有模块集成正常

- [ ] **Step 1: 删除废弃文件**

```bash
cd "C:/Users/35368/Desktop/信源汇总"
rm -rf frontend/
rm -f ak_source_aggregator.py news_viewer.py news_vector.py scheduler_runner.py
```

- [ ] **Step 2: 完整导入验证**

```bash
cd "C:/Users/35368/Desktop/信源汇总"
python -c "
from utils.config import load_config
from modules.news.db import NewsDB
from modules.news.aggregator import AKSourceAggregator
from modules.hotlist.db import HotlistDB
from modules.hotlist.fetcher import DataFetcher
from modules.rss.db import RSSDB
from modules.rss.parser import RSSParser
from ai.client import AIClient
print('All imports OK')
"
```

- [ ] **Step 3: 启动调度器验证**

```bash
python scheduler.py
# Ctrl+C 停止，确认各模块初始化正常
```

- [ ] **Step 4: 启动 Web 应用验证**

```bash
python app.py
# 浏览器验证三个 Tab 功能
```

- [ ] **Step 5: 最终提交**

```bash
git add .gitignore app.py scheduler.py config.yaml requirements.txt utils/ modules/ ai/ templates/
git commit -m "chore: 清理废弃文件，完成三模块整合"
```
