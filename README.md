# 信源汇总

一站式信息聚合平台，聚合多平台热榜、新闻资讯和 RSS 订阅，支持 AI 驱动的热点选题、文案创作和智能问答。

## 功能模块

| 模块 | 功能 |
|------|------|
| 新闻汇总 | 多源新闻自动采集、向量去重聚类、语义搜索 |
| 热榜聚合 | 11 个平台实时热搜（微博、知乎、B站等） |
| RSS 订阅 | 手动添加、站点发现、通用 HTML 转换、预置 24 个平台映射 |
| 热点选题 | AI 驱动的选题生成，基于语义检索推荐热点标题 |
| 文案创作 | AI 文案框架生成 + 对话式迭代 + 文章生成 + 配图 |
| 智能问答 | 基于全量数据的向量检索 + DeepSeek 流式问答 |

## 技术栈

- **后端**: Python 3.10, Flask, Gunicorn
- **数据库**: SQLite（新闻/热榜/RSS/创作各独立 db）
- **向量引擎**: ChromaDB + sentence-transformers (BAAI/bge-small-zh-v1.5)
- **AI**: LiteLLM + DeepSeek-V3（聊天、选题、文案）
- **RSS 生成**: 自建 RSSHub Docker 实例
- **前端**: React + TypeScript + Vite 单页应用（暗色主题 + 复古主题）
- **部署**: Ubuntu + Nginx + systemd

## 项目结构

```
├── app.py                      # Flask Web 入口（端口 5000）
├── scheduler.py                # 独立调度进程（定时采集 + 向量搜索 API 端口 5001）
├── config.yaml                 # 全局配置（敏感项用环境变量覆盖）
├── config.example.yaml         # 配置模板
├── .env.example                # 环境变量模板
├── requirements.txt
├── docker-compose.rsshub.yml   # RSSHub Docker 部署
├── modules/
│   ├── news/                   # 新闻汇总
│   │   ├── aggregator.py       # 多源采集 + 去重
│   │   ├── vector.py           # 向量引擎（ChromaDB）
│   │   ├── db.py               # 数据库操作
│   │   └── routes.py           # Flask API
│   ├── hotlist/                # 热榜聚合
│   │   ├── fetcher.py          # 多平台热榜抓取
│   │   ├── vector.py           # 热榜向量化
│   │   ├── db.py / routes.py
│   ├── rss/                    # RSS 订阅
│   │   ├── discover.py         # RSSHub 站点发现 + 通用转换
│   │   ├── fetcher.py          # RSS 抓取（智能代理）
│   │   ├── parser.py           # RSS/Atom 解析
│   │   ├── vector.py           # RSS 向量化
│   │   ├── db.py / routes.py
│   ├── topic/                  # 热点选题
│   │   ├── service.py          # 选题生成逻辑
│   │   ├── title_gen.py        # AI 标题生成
│   │   └── routes.py
│   ├── creator/                # 文案创作
│   │   ├── framework.py        # 框架生成 + 对话迭代
│   │   ├── article.py          # 文章异步生成
│   │   ├── image_gen.py        # AI 配图
│   │   ├── db.py               # 持久化存储
│   │   └── routes.py
│   └── chat/                   # 智能问答
│       ├── service.py          # QA 流式服务
│       ├── db.py / routes.py
├── ai/                         # AI 统一接口
│   ├── client.py               # LiteLLM 客户端
│   ├── config.py               # 统一 AI 配置提供器
│   ├── filter.py / analyzer.py
├── utils/
│   ├── config.py               # YAML 配置加载（支持环境变量覆盖）
│   ├── auth.py                 # Token 鉴权装饰器
│   ├── url_security.py         # SSRF 防护
│   ├── scheduler_client.py     # Scheduler 通信客户端
│   └── crawl_trigger.py        # 抓取触发信号
├── static/
│   ├── css/main.css            # 前端样式
│   └── js/app.js               # 前端逻辑
├── templates/
│   └── index.html              # 主页面
├── frontend/                   # React + TypeScript 前端源码
├── frontend_dist/              # React 构建产物（生产部署用）
└── tests/                      # 测试目录
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置

复制配置模板并填写：

```bash
cp config.example.yaml config.yaml
cp .env.example .env
```

编辑 `.env` 设置敏感配置：

```
DEPLOY_HOST=your_server_ip
DEPLOY_USER=ubuntu
DEPLOY_SSH_KEY_PATH=~/.ssh/id_rsa
AI_API_KEY=your_api_key_here
AI_BASE_URL=https://api.deepseek.com/v1
ADMIN_TOKEN=your_secure_token_here
```

### 3. 启动 RSSHub（可选）

```bash
docker compose -f docker-compose.rsshub.yml up -d
```

### 4. 启动服务

```bash
# Web 服务（端口 5000）
python app.py --port 5000 --no-browser

# 调度器（独立进程，端口 5001 提供向量搜索 API）
python scheduler.py
```

### 生产环境

```bash
# Web（Gunicorn）
gunicorn -w 2 -b 0.0.0.0:5000 app:app

# 调度器（建议用 systemd 守护）
python scheduler.py
```

## 安全说明

- **鉴权**：配置 `ADMIN_TOKEN` 环境变量后，所有写接口需要 Bearer Token 认证
- **SSRF 防护**：RSS 模块对用户提交的 URL 进行私有 IP/DNS 重绑定校验
- **XSS 防护**：前端使用 DOMPurify 清洗 Markdown 渲染输出，统一转义用户内容
- **凭据管理**：敏感配置通过环境变量注入，不硬编码在代码中

## API 概览

### 读取接口（无需认证）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/status` | GET | 全局状态 |
| `/api/news` | GET | 新闻列表（分页、分类、搜索） |
| `/api/news/semantic_search` | GET | 语义搜索 |
| `/api/news/categories` | GET | 分类统计 |
| `/api/hotlist` | GET | 热榜列表 |
| `/api/hotlist/platforms` | GET | 平台统计 |
| `/api/rss/items` | GET | RSS 条目 |
| `/api/rss/feeds` | GET | RSS 源列表 |
| `/api/scheduler/health` | GET | Scheduler 健康检查 |

### 写入接口（需 ADMIN_TOKEN）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/news/fetch` | POST | 触发新闻抓取 |
| `/api/hotlist/fetch` | POST | 触发热榜抓取 |
| `/api/rss/feeds` | POST | 添加 RSS 源 |
| `/api/rss/feeds/<id>` | PUT/DELETE | 更新/删除 RSS 源 |
| `/api/rss/fetch` | POST | 触发 RSS 抓取 |
| `/api/rss/discover` | POST | 站点发现 |
| `/api/creator/framework/*` | POST | 文案创作相关 |
| `/api/chat/sessions` | POST/DELETE | 会话管理 |
| `/api/chat/sessions/<id>/chat` | POST | 智能问答（SSE） |

## License

MIT
