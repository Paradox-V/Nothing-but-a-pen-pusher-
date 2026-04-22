# 信源汇总

一站式信息聚合平台，聚合多平台热榜、新闻资讯和 RSS 订阅，支持 AI 驱动的热点选题、文案创作和智能问答。集成微信（WCF）消息推送、监控任务调度和用户账号系统。

## 功能模块

| 模块 | 功能 |
|------|------|
| 新闻汇总 | 多源新闻自动采集（8 个 AKTools 信源）、向量去重聚类、语义搜索 |
| 热榜聚合 | 11 个平台实时热搜（微博、知乎、B 站等） |
| RSS 订阅 | 手动添加、站点发现、微信公众号转化、通用 HTML 转换、AI 搜索订阅 |
| 热点选题 | AI 驱动的选题生成，基于语义检索推荐热点标题 |
| 文案创作 | AI 文案框架生成 + 对话式迭代 + 文章生成 + 配图 |
| 智能问答 | 基于全量数据的向量检索 + DeepSeek 流式问答（ReAct Agent） |
| 监控任务 | 关键词监控、定时推送（微信/其他渠道） |
| 微信连接 | WCF 协议接入，支持联系人绑定、指令交互、Agent 对话 |
| 用户系统 | JWT 认证、注册/邀请码、角色权限（user/admin）、管理后台 |
| 冷热归档 | 新闻数据自动归档，冷库保留 180 天 |

## 技术栈

- **后端**: Python 3.10+, Flask, Gunicorn
- **数据库**: SQLite（各模块独立 db）
- **向量引擎**: ChromaDB + sentence-transformers (BAAI/bge-small-zh-v1.5)
- **AI**: LiteLLM + DeepSeek-V3（聊天、选题、文案、Agent）
- **RSS 生成**: 自建 RSSHub Docker 实例
- **微信**: WCF 协议（wcfLink HTTP 服务）
- **前端**: React + TypeScript + Vite 单页应用（暗色主题 + 复古主题）
- **部署**: Ubuntu + Nginx + systemd

## 项目结构

```
├── app.py                      # Flask Web 入口（端口 5000）
├── scheduler.py                # 独立调度进程（定时采集 + 向量搜索 API 端口 5001）
├── deploy.py                   # 部署脚本
├── config.yaml                 # 全局配置（敏感项用环境变量覆盖）
├── config.example.yaml         # 配置模板
├── .env.example                # 环境变量模板
├── requirements.txt            # 核心依赖
├── requirements-ai.txt         # AI 相关依赖
├── requirements-dev.txt        # 开发依赖
├── docker-compose.rsshub.yml   # RSSHub Docker 部署
├── modules/
│   ├── news/                   # 新闻汇总
│   │   ├── aggregator.py       # AKTools 8 源采集 + 去重
│   │   ├── vector.py           # 向量引擎（ChromaDB）
│   │   ├── db.py / routes.py
│   ├── hotlist/                # 热榜聚合
│   │   ├── fetcher.py          # 多平台热榜抓取
│   │   ├── vector.py / db.py / routes.py
│   ├── rss/                    # RSS 订阅
│   │   ├── discover.py         # RSSHub 站点发现 + 通用转换
│   │   ├── fetcher.py          # RSS 抓取
│   │   ├── parser.py           # RSS/Atom 解析
│   │   ├── wechat_mp.py        # 微信公众号 RSS 转化
│   │   ├── vector.py / db.py / routes.py
│   ├── topic/                  # 热点选题
│   ├── creator/                # 文案创作
│   │   ├── framework.py / article.py / image_gen.py
│   │   ├── db.py / routes.py
│   ├── chat/                   # 智能问答
│   │   ├── service.py / db.py / routes.py
│   ├── agent/                  # Agent 模式
│   │   ├── service.py          # ReAct Agent + 流式输出
│   │   └── tools.py            # Agent 工具集（搜索、监控、RSS）
│   ├── monitor/                # 监控任务
│   │   ├── service.py / db.py / push.py / routes.py
│   ├── wcf/                    # 微信连接
│   │   ├── service.py          # 事件消费 + 指令处理 + Agent 路由
│   │   ├── client.py / db.py
│   ├── account/                # 用户账号
│   │   ├── db.py               # 用户/会话/邀请码 CRUD
│   │   └── routes.py           # 注册/登录/个人信息 API
│   ├── admin/                  # 管理后台
│   │   └── routes.py           # 用户管理/广播/系统概览 API
│   └── archive/                # 冷热归档
├── ai/                         # AI 统一接口
│   ├── client.py / config.py / filter.py / analyzer.py
├── utils/
│   ├── config.py               # YAML 配置加载（支持环境变量覆盖）
│   ├── auth.py                 # Token 鉴权装饰器
│   ├── jwt_auth.py             # JWT 认证（生成/验证/中间件）
│   ├── url_security.py         # SSRF 防护
│   ├── rss_search.py           # RSS AI 搜索（Feedly + 内部索引）
│   ├── scheduler_client.py     # Scheduler 通信客户端
│   └── crawl_trigger.py        # 抓取触发信号
├── frontend/                   # React + TypeScript 前端源码
└── tests/                      # 测试目录
```

## 快速开始

### 1. 安装依赖

```bash
# 核心依赖
pip install -r requirements.txt

# AI 功能（可选）
pip install -r requirements-ai.txt

# 开发依赖
pip install -r requirements-dev.txt
```

### 2. 配置

复制配置模板并填写：

```bash
cp config.example.yaml config.yaml
cp .env.example .env
```

编辑 `.env` 设置敏感配置：

```ini
DEPLOY_HOST=your_server_ip
DEPLOY_USER=ubuntu
DEPLOY_SSH_KEY_PATH=~/.ssh/id_rsa
AI_API_KEY=your_api_key_here
AI_BASE_URL=https://api.deepseek.com/v1
ADMIN_TOKEN=your_secure_token_here
AKTOOLS_BASE_URL=http://127.0.0.1:8080/api/public
JWT_SECRET=your_jwt_secret_here
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

- **Token 鉴权**：配置 `ADMIN_TOKEN` 环境变量后，所有写接口需要 Bearer Token 认证
- **JWT 认证**：用户系统使用 JWT + 会话表双重验证，支持 token 吊销
- **SSRF 防护**：RSS 模块对用户提交的 URL 进行私有 IP/DNS 重绑定校验
- **XSS 防护**：前端使用 DOMPurify 清洗 Markdown 渲染输出
- **XXE 防护**：XML 解析使用 defusedxml，防止外部实体注入
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
| `/api/rss/discover/wechat` | POST | 微信公众号 RSS 转化 |
| `/api/rss/search` | POST | AI RSS 搜索 |
| `/api/rss/bulk-subscribe` | POST | 批量订阅 |
| `/api/creator/framework/*` | POST | 文案创作相关 |
| `/api/chat/sessions` | POST/DELETE | 会话管理 |
| `/api/chat/sessions/<id>/chat` | POST | 智能问答（SSE） |

### 用户账号接口

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/account/register` | POST | 注册（开放或邀请码） |
| `/api/account/login` | POST | 登录 |
| `/api/account/logout` | POST | 登出 |
| `/api/account/me` | GET/PUT | 个人信息 |

### 管理后台接口（需 ADMIN_TOKEN）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/admin/overview` | GET | 系统概览 |
| `/api/admin/users` | GET | 用户列表 |
| `/api/admin/users/<id>` | PUT/DELETE | 更新/删除用户 |
| `/api/admin/tasks` | GET | 监控任务列表 |
| `/api/admin/push-logs` | GET | 推送日志 |
| `/api/admin/wcf-bindings` | GET | 微信绑定列表 |
| `/api/admin/rss-feeds` | GET | RSS 源列表 |
| `/api/admin/broadcast` | POST | 广播消息 |
| `/api/admin/invite` | POST | 生成邀请码 |

### 监控接口

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/monitor/tasks` | GET/POST | 任务列表/创建 |
| `/api/monitor/tasks/<id>` | PUT/DELETE | 更新/删除任务 |
| `/api/monitor/tasks/<id>/run` | POST | 手动执行任务 |
| `/api/monitor/push-logs` | GET | 推送日志 |

## License

MIT
