# 信源汇总三模块整合设计

## 概述

将 TrendRadar 项目的热榜聚合功能和 RSS 订阅功能作为独立模块，整合到信源汇总项目中，形成三大模块共存的统一平台。

**三大模块**：金融新闻汇总（原有）、热榜聚合（TrendRadar 移植）、RSS 自定义订阅（TrendRadar 移植）

## 决策记录

| 决策项 | 选择 |
|--------|------|
| 基础框架 | 信源汇总的 Flask |
| 数据存储 | 三模块分库 SQLite |
| 热榜数据源 | NewsNow API |
| 调度机制 | 守护进程定时调度 |
| 前端 UI | 扩展现有暗色主题 |
| 附加功能 | 语义分析 + AI 分析/过滤 |
| RSS 管理 | Web UI 动态管理 |

---

## 1. 项目结构

```
信源汇总/
├── app.py                      # Flask 应用入口，注册蓝图路由
├── config.yaml                 # 全局配置
├── scheduler.py                # 守护进程：定时调度三个模块的采集任务
├── requirements.txt            # 依赖管理
│
├── modules/
│   ├── __init__.py
│   ├── news/                   # 模块1: 金融新闻汇总（原有）
│   │   ├── __init__.py
│   │   ├── aggregator.py       # AKSourceAggregator（从 ak_source_aggregator.py 重构）
│   │   ├── vector.py           # NewsVectorEngine（从 news_vector.py 移植）
│   │   ├── db.py               # news.db CRUD 封装
│   │   └── routes.py           # Flask Blueprint: /api/news/*
│   │
│   ├── hotlist/                # 模块2: 热榜聚合
│   │   ├── __init__.py
│   │   ├── fetcher.py          # DataFetcher: NewsNow API 抓取（从 TrendRadar 移植）
│   │   ├── db.py               # hotlist.db CRUD 封装
│   │   └── routes.py           # Flask Blueprint: /api/hotlist/*
│   │
│   └── rss/                    # 模块3: RSS 订阅
│       ├── __init__.py
│       ├── fetcher.py          # RSSFetcher（从 TrendRadar 移植）
│       ├── parser.py           # RSSParser（从 TrendRadar 移植）
│       ├── db.py               # rss.db CRUD + 订阅源管理
│       └── routes.py           # Flask Blueprint: /api/rss/*
│
├── ai/                         # AI 分析模块（从 TrendRadar 移植，可选）
│   ├── __init__.py
│   ├── client.py               # litellm 客户端封装
│   ├── filter.py               # AI 兴趣过滤（内含 prompt 模板）
│   └── analyzer.py             # AI 新闻分析（内含 prompt 模板）
│
├── utils/                      # 公共工具
│   ├── __init__.py
│   └── time.py                 # 时间处理
│
├── data/                       # 数据目录（gitignore）
│   ├── news.db
│   ├── hotlist.db
│   ├── rss.db
│   └── chroma_db/
│
└── templates/
    └── index.html              # 统一 Web UI（从 news_viewer.py 内嵌 HTML 提取）
```

### 关键重构点

- `ak_source_aggregator.py`（756行）拆分为 `news/aggregator.py` + `news/db.py`
- `news_viewer.py`（873行）中的路由提取到各模块的 `routes.py`，内嵌 HTML 提取到 `templates/index.html`
- `news_vector.py` 直接移入 `news/vector.py`
- TrendRadar 的 `crawler/fetcher.py` 移入 `hotlist/fetcher.py`
- TrendRadar 的 `crawler/rss/` 移入 `rss/`
- 三个模块各一个 Flask Blueprint，在 `app.py` 中统一注册
- 现有 `frontend/` 目录（未完成的 Next.js 迁移）删除，不保留

### app.py 与 scheduler.py 的关系

- `app.py`：Flask Web 服务进程，处理 HTTP 请求（路由、API、页面渲染）
- `scheduler.py`：独立的守护进程，定时执行数据采集
- 两者作为**独立进程**运行，各自启动，互不依赖
- `app.py` 使用简单的 `app = Flask(__name__)` + Blueprint 注册模式（不用工厂函数）
- 手动采集按钮（`/api/*/fetch`）通过调用各模块的 fetch 函数直接执行，与 scheduler 使用相同的采集逻辑
- 两者共享 `config.yaml` 配置和 `data/` 目录

### config.yaml 加载机制

- 使用 `pyyaml` 在 `app.py` 和 `scheduler.py` 启动时各读取一次
- 封装为 `utils/config.py`（新增），提供 `load_config()` 函数返回字典
- 各模块从 config 字典中读取自己需要的配置段

---

## 2. 数据库设计（分库）

**所有 SQLite 数据库启用 WAL 模式**，以支持 scheduler 和 Flask 的并发读写。

### 2.1 news.db（原有，保留）

```sql
news (
    id INTEGER PRIMARY KEY,
    title TEXT,
    content TEXT,
    source TEXT,
    url TEXT UNIQUE,
    publish_time DATETIME,
    crawl_time DATETIME,
    content_hash TEXT,
    category TEXT,
    cluster_id INTEGER
);
```

ChromaDB 向量数据继续存放在 `data/chroma_db/`，仅新闻模块使用，结构不变。

### 2.2 hotlist.db（新增）

```sql
CREATE TABLE hot_items (
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
```

**Upsert 逻辑**：
- 每次采集为当前时间点的所有条目 INSERT 新行（`UNIQUE(url, platform, crawl_time)` 保证同批次不重复）
- 同时对已有条目做追踪：如果某个 URL+platform 在之前已存在，则 UPDATE 其 `appear_count += 1`、`last_time = 当前时间`
- 这样每个采集批次有完整的快照，同时保留了条目的热度趋势信息

```sql
CREATE TABLE crawl_batches (
    id INTEGER PRIMARY KEY,
    crawl_time DATETIME NOT NULL,
    platform_count INTEGER,
    item_count INTEGER
);
```

`crawl_batches` 由 scheduler 在每次采集结束后写入一条记录，用于：
- UI 上展示最近采集时间
- 调试采集是否正常运行

**数据清理**：scheduler 按 `purge_days` 配置定期清理 `hot_items` 中 `crawl_time` 超过保留期的记录，同时清理对应的 `crawl_batches`。

### 2.3 rss.db（新增）

```sql
CREATE TABLE rss_feeds (
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
```

**`rss_feeds.id` 生成策略**：添加订阅源时由系统自动生成，规则为 URL-friendly slug（小写字母+数字+连字符）。例如用户输入名称 "Hacker News"，生成 id 为 `hacker-news`。如果冲突则追加数字后缀 `hacker-news-2`。

```sql
CREATE TABLE rss_items (
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
```

**数据清理**：scheduler 按 `purge_days` 配置定期清理 `rss_items` 中 `crawl_time` 超过保留期的记录。被删除订阅源的关联条目一并清理（CASCADE）。

---

## 3. 调度与数据流

### 3.1 调度器

`scheduler.py` 作为守护进程运行，独立调度三个模块：

| 模块 | 采集间隔 | 说明 |
|------|----------|------|
| news | 600s（10分钟） | 沿用现有 |
| hotlist | 300s（5分钟） | 热榜变化快 |
| rss | 1800s（30分钟） | RSS 更新较慢 |

每个模块采集用 try/except 包裹，单个模块失败不影响其他模块。

### 3.2 数据流

```
scheduler.py（守护进程）
    │
    ├── news 模块 ──→ 8个金融源(httpx异步) ──→ news.db + ChromaDB
    ├── hotlist 模块 ──→ NewsNow API ──→ hotlist.db
    └── rss 模块 ──→ feedparser(多格式) ──→ rss.db
                                              │
    各模块数据 ──→ app.py(Flask路由) ──→ Web UI
                    │
                    └──→ ai/(可选层) ──→ AI分析/过滤
```

### 3.3 错误处理

- 单模块采集失败只记日志，不影响其他模块
- RSS 抓取失败写入 `rss_feeds.last_error`，UI 可展示
- NewsNow API 不可用时跳过本轮热榜采集，不中断

### 3.4 config.yaml

```yaml
scheduler:
  news_interval: 600
  hotlist_interval: 300
  rss_interval: 1800
  purge_days: 7              # 三个模块共用的数据保留天数

hotlist:
  platforms:                  # 空列表 = 采集所有可用平台
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
  enabled: false              # 默认关闭，配置 api_key 后启用
  model: "deepseek/deepseek-chat"
  api_key: ""
  base_url: ""
  interests: ""               # 兴趣描述文本，用于 AI 过滤

vector:
  model: "BAAI/bge-small-zh-v1.5"
  dedup_threshold: 0.78
  cluster_threshold: 0.85
```

---

## 4. Web UI

### 4.1 布局

在现有暗色主题基础上扩展，顶部 Tab 导航切换三个模块：

```
┌─────────────────────────────────────────────────────┐
│  信源汇总                            [手动刷新] [设置] │
├─────────┬──────────┬──────────┬─────────────────────┤
│  新闻汇总 │   热榜    │  RSS订阅  │                     │
├─────────┴──────────┴──────────┴─────────────────────┤
│  [筛选栏]  ← 各模块差异化                              │
│  [内容卡片] ← 各模块差异化                              │
│  [分页]                                             │
└─────────────────────────────────────────────────────┘
```

### 4.2 三个 Tab 差异

| | 新闻汇总 | 热榜 | RSS订阅 |
|---|---|---|---|
| 筛选栏 | 来源、分类、日期范围、关键词搜索 | 平台筛选、时间范围 | 订阅源筛选、时间范围、关键词搜索 |
| 卡片样式 | 标题+摘要+分类标签（现有） | 排名+标题+平台+热度值 | 标题+摘要+来源Feed+发布时间 |
| 特色交互 | 语义搜索开关 | 热度趋势标识（持续上榜次数） | 管理订阅源按钮 |

### 4.3 RSS 管理面板

模态框形式，支持：
- 查看所有订阅源列表（名称、URL、状态）
- 添加/编辑/删除订阅源
- 启用/禁用订阅源
- 展示订阅源健康状态（正常/错误信息）

### 4.4 技术选择

- 将现有 `news_viewer.py` 中内嵌的 HTML 提取到 `templates/index.html`，使用 Flask 的 `render_template()`
- 所有三个 Tab 的内容在一个 `index.html` 文件中，用 CSS + JS 控制 Tab 切换（display）
- 继续用 Vanilla JS，不引入前端框架
- API 调用用 fetch()
- 若 `index.html` 过大（超过 1500 行），后续可按 Tab 拆分为多个模板片段

---

## 5. API 路由

### 5.1 新闻模块

| 路由 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 主页面（含三个 Tab） |
| `/api/news` | GET | 新闻列表（分页+筛选） |
| `/api/news/status` | GET | 数据库统计 |
| `/api/news/semantic_search` | GET | 语义搜索 |
| `/api/news/categories` | GET | 分类统计 |
| `/api/news/fetch` | POST | 手动触发采集 |

### 5.2 热榜模块

| 路由 | 方法 | 说明 |
|------|------|------|
| `/api/hotlist` | GET | 热榜列表（分页+平台筛选） |
| `/api/hotlist/platforms` | GET | 平台统计 |
| `/api/hotlist/fetch` | POST | 手动触发采集 |

### 5.3 RSS 模块

| 路由 | 方法 | 说明 |
|------|------|------|
| `/api/rss/items` | GET | RSS 文章列表 |
| `/api/rss/feeds` | GET | 订阅源列表 |
| `/api/rss/feeds` | POST | 添加订阅源 |
| `/api/rss/feeds/<id>` | PUT | 修改订阅源 |
| `/api/rss/feeds/<id>` | DELETE | 删除订阅源 |
| `/api/rss/fetch` | POST | 手动触发采集 |

---

## 6. AI 模块（可选）

### 6.1 架构

AI 模块是可选的叠加层，`config.yaml` 中 `ai.enabled: false` 时所有 AI 入口隐藏。

### 6.2 文件职责

| 文件 | 职责 |
|------|------|
| `ai/client.py` | litellm 客户端封装，统一 LLM 调用 |
| `ai/filter.py` | AI 兴趣过滤：根据兴趣描述筛选新闻（内含 prompt 模板字符串） |
| `ai/analyzer.py` | AI 新闻分析：摘要生成、趋势判断（内含 prompt 模板字符串） |

Prompt 模板以 Python 字符串形式内嵌在各自的文件中，不使用外部 prompt 文件。

### 6.3 交互方式

| 场景 | 调用链 |
|------|--------|
| 新闻采集后过滤 | `news/aggregator` → `ai/filter.py` |
| 热榜 AI 分析 | 用户点击按钮 → `ai/analyzer.py` |
| RSS AI 摘要 | 用户点击按钮 → `ai/analyzer.py` |

### 6.4 降级策略

- API 调用失败时静默降级，不影响数据采集和展示
- `client.py` 内部封装 litellm，后续可替换为其他 SDK

---

## 7. 需要移植的 TrendRadar 源文件映射

| TrendRadar 源文件 | 目标位置 | 移植内容 |
|-------------------|----------|----------|
| `trendradar/crawler/fetcher.py` | `modules/hotlist/fetcher.py` | DataFetcher 类 |
| `trendradar/crawler/rss/fetcher.py` | `modules/rss/fetcher.py` | RSSFetcher 类 |
| `trendradar/crawler/rss/parser.py` | `modules/rss/parser.py` | RSSParser 类 |
| `trendradar/storage/schema.sql` | 参考 | hotlist 表设计 |
| `trendradar/storage/rss_schema.sql` | 参考 | rss 表设计 |
| `trendradar/ai/client.py` | `ai/client.py` | litellm 客户端 |
| `trendradar/ai/filter.py` | `ai/filter.py` | AI 过滤 |
| `trendradar/ai/analyzer.py` | `ai/analyzer.py` | AI 分析 |
| `trendradar/ai/prompt_loader.py` | 合并到 `ai/filter.py` + `ai/analyzer.py` | prompt 加载 |
| `trendradar/utils/time.py` | `utils/time.py` | 时间工具 |

---

## 8. 完整依赖列表

### 保留的现有依赖

| 包 | 用途 |
|----|------|
| flask | Web 框架 |
| httpx | 异步 HTTP 客户端（新闻采集） |
| chromadb | 向量数据库 |
| sentence-transformers | 语义嵌入模型（BGE） |

### 新增依赖

| 包 | 用途 | 来源 |
|----|------|------|
| feedparser | RSS/Atom/JSON Feed 解析 | TrendRadar 已用 |
| litellm | AI LLM 调用（可选） | TrendRadar 已用 |
| pyyaml | 配置文件解析 | TrendRadar 已用 |
| requests | NewsNow API 调用（热榜） | TrendRadar 已用 |
