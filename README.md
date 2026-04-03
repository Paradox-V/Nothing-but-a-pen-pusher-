# 信源汇总

一站式信息聚合平台，聚合多平台热榜、新闻资讯和 RSS 订阅，支持向量去重和语义搜索。

## 功能

### 热榜聚合
一键查看 11 个平台实时热搜：微博、知乎、B站、今日头条、百度、华尔街见闻、澎湃新闻、财联社、凤凰网、抖音、百度贴吧。

### 新闻汇总
多源新闻自动采集、向量去重聚类，支持语义搜索。

### RSS 订阅
- 手动添加任意 RSS/Atom 源
- **站点发现**：输入网站地址（如 `36kr.com`），自动匹配 RSSHub 路由并预览
- **通用转换**：未匹配映射表的网站，自动通过 RSSHub Transform 生成 RSS 源
- **自定义选择器**：支持输入 CSS 选择器精确提取页面内容
- 预置 24 个平台映射（36氪、少数派、IT之家、GitHub、Hacker News、Arxiv、中国人民银行、国家统计局等）

## 技术栈

- **后端**: Python 3.10, Flask, Gunicorn
- **数据库**: SQLite（新闻/热榜/RSS 各独立 db）
- **向量引擎**: ChromaDB + sentence-transformers (BAAI/bge-small-zh-v1.5)
- **RSS 生成**: 自建 RSSHub Docker 实例
- **前端**: 原生 HTML/CSS/JS 单页应用（暗色主题）
- **部署**: Ubuntu + Nginx + systemd

## 项目结构

```
├── app.py                      # Flask Web 入口
├── scheduler.py                # 独立调度进程（定时采集 + 向量搜索 API）
├── config.yaml                 # 全局配置
├── requirements.txt
├── docker-compose.rsshub.yml   # RSSHub Docker 部署
├── modules/
│   ├── news/                   # 新闻汇总模块
│   │   ├── aggregator.py       # 多源采集 + 去重
│   │   ├── vector.py           # 向量引擎（ChromaDB）
│   │   ├── db.py               # 数据库操作
│   │   └── routes.py           # Flask API
│   ├── hotlist/                # 热榜模块
│   │   ├── fetcher.py          # 多平台热榜抓取
│   │   ├── db.py
│   │   └── routes.py
│   └── rss/                    # RSS 订阅模块
│       ├── discover.py         # RSSHub 站点发现 + 通用转换
│       ├── fetcher.py          # RSS 抓取（智能代理）
│       ├── parser.py           # RSS/Atom 解析
│       ├── db.py
│       └── routes.py           # CRUD + discover API
├── ai/                         # AI 过滤（可选）
│   ├── filter.py
│   └── analyzer.py
├── utils/
│   └── config.py               # YAML 配置加载
└── templates/
    └── index.html              # 单页前端
```

## 部署

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 启动 RSSHub（可选，用于站点发现功能）

```bash
docker compose -f docker-compose.rsshub.yml up -d
```

### 3. 配置

编辑 `config.yaml`：

```yaml
# 代理（可选，用于访问外网源）
proxy:
  url: "http://127.0.0.1:7890"

# RSSHub 站点发现
rsshub:
  base_url: "http://127.0.0.1:1200"
  sites:
    36kr.com:
      name: "36氪"
      routes:
        - path: /36kr/newsflashes
          name: "快讯"

# 调度间隔（秒）
scheduler:
  news_interval: 600
  hotlist_interval: 300
  rss_interval: 1800
```

### 4. 启动服务

```bash
# Web 服务
python app.py --port 5000 --no-browser

# 调度器（独立进程）
python scheduler.py
```

### 生产环境（systemd + Gunicorn）

```bash
# Web
gunicorn -w 2 -b 0.0.0.0:5000 app:app

# 调度器
python scheduler.py
```

## API

| 端点 | 方法 | 说明 |
|------|------|------|
| `GET /api/status` | GET | 全局状态 |
| `GET /api/news/items` | GET | 新闻列表（分页） |
| `GET /api/news/search` | GET | 语义搜索 |
| `GET /api/hotlist` | GET | 全平台热榜 |
| `GET /api/rss/feeds` | GET | RSS 源列表 |
| `POST /api/rss/feeds` | POST | 添加 RSS 源 |
| `DELETE /api/rss/feeds/:id` | DELETE | 删除 RSS 源 |
| `POST /api/rss/discover` | POST | 站点发现（映射表 + 通用转换） |
| `POST /api/rss/discover/custom` | POST | 自定义 CSS 选择器转换 |
| `POST /api/rss/fetch` | POST | 手动触发抓取 |

## RSS 智能代理

RSS 抓取采用**先直连、后代理**策略：
- `127.0.0.1` / `localhost` 地址（RSSHub 容器）直连
- 外部地址先直连尝试（5s 超时），失败后自动走代理
- 避免对无需代理的源（如 `hnrss.org`）不必要的代理开销

## License

MIT
