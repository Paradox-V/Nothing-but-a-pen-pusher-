"""
统一调度器 - 独立进程运行

定时调度三个模块的数据采集：新闻、热榜、RSS
同时提供内部向量搜索 API（端口 5001），供 Web 进程调用
"""
import json
import logging
import os
import sqlite3
import threading
import time
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs

# 离线模式：跳过 HuggingFace 网络检查
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
from modules.hotlist.vector import HotlistVectorEngine
from modules.rss.vector import RSSVectorEngine
from modules.archive.manager import ArchiveManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [scheduler] %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


# ── 内部向量 API ─────────────────────────────────────────────

VECTOR_API_PORT = 5001


class _ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    """多线程 HTTP 服务器，避免慢查询阻塞其他请求"""
    daemon_threads = True


class _VectorAPIHandler(BaseHTTPRequestHandler):
    """轻量 HTTP 处理器，代理 scheduler 已加载的向量引擎"""

    vector_engine: NewsVectorEngine | None = None
    hotlist_vector: HotlistVectorEngine | None = None
    rss_vector: RSSVectorEngine | None = None
    archive_manager = None  # ArchiveManager instance

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/semantic_search":
            self._handle_search(parsed)
        elif parsed.path == "/archive/news":
            self._handle_archive_news(parsed)
        elif parsed.path == "/archive/hotlist":
            self._handle_archive_hotlist(parsed)
        elif parsed.path == "/archive/rss":
            self._handle_archive_rss(parsed)
        elif parsed.path == "/health":
            self._json({"ok": True, "model_loaded": self.vector_engine is not None})
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/chat_search":
            self._handle_chat_search()
        else:
            self._json({"error": "not found"}, 404)

    def _handle_search(self, parsed):
        params = parse_qs(parsed.query)
        query = params.get("q", [""])[0]
        if not query:
            self._json([])
            return
        if not self.vector_engine:
            self._json({"error": "向量引擎未初始化"}, 503)
            return

        n = int(params.get("n", ["20"])[0])
        cat_raw = params.get("category", [None])[0]
        src_raw = params.get("source", [None])[0]
        categories = cat_raw.split(",") if cat_raw else None
        sources = src_raw.split(",") if src_raw else None

        results = self.vector_engine.semantic_search(
            query=query, n=n, categories=categories, sources=sources,
        )

        # 冷库回查：热库 0 结果时查冷库
        if not results and self.archive_manager and self.archive_manager._vector_ready:
            try:
                results = self.archive_manager.semantic_search_news(query, n=n)
                for r in results:
                    r["source_name"] = (r.get("source_name", "") + " [archive]").strip()
            except Exception as e:
                logger.warning("冷库语义搜索回查失败: %s", e)

        self._json(results)

    def _handle_chat_search(self):
        """多数据源向量搜索，供 QA 问答模块使用。"""
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            self._json({"error": "empty body"}, 400)
            return
        body = self.rfile.read(content_length)
        try:
            data = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._json({"error": "invalid JSON"}, 400)
            return

        query = data.get("query", "")
        top_k = data.get("top_k", 5)
        if not query:
            self._json([])
            return

        if not self.vector_engine or not self.vector_engine._initialized:
            self._json({"error": "向量引擎未初始化"}, 503)
            return

        # 嵌入查询
        query_emb = self.vector_engine._encode([query])[0]

        # 从 3 个 Collection 检索
        all_results = []

        # 新闻
        news_results = self.vector_engine.semantic_search(query, n=top_k)
        for r in news_results:
            r["source_type"] = r.get("source_type", "news")
            all_results.append(r)

        # 热榜
        if self.hotlist_vector and self.hotlist_vector._initialized:
            hot_results = self.hotlist_vector.semantic_search(query_emb, top_k=top_k)
            all_results.extend(hot_results)

        # RSS
        if self.rss_vector and self.rss_vector._initialized:
            rss_results = self.rss_vector.semantic_search(query_emb, top_k=top_k)
            all_results.extend(rss_results)

        # 按距离排序（升序 = 最相关在前）
        all_results.sort(key=lambda x: x.get("distance", 1.0))

        # 跨 Collection 去重（标题 Jaccard > 0.8 视为重复）
        deduped = []
        seen_titles = []
        for r in all_results:
            title = r.get("title", "")
            is_dup = False
            for st in seen_titles:
                if _jaccard_similarity(title, st) > 0.8:
                    is_dup = True
                    break
            if not is_dup:
                deduped.append(r)
                seen_titles.append(title)

        self._json(deduped[:10])

    # ── 冷库浏览接口 ─────────────────────────────────────────

    def _handle_archive_news(self, parsed):
        if not self.archive_manager:
            self._json({"error": "archive not enabled"}, 503)
            return
        params = parse_qs(parsed.query)
        result = self.archive_manager.search_news(
            keyword=params.get("keyword", [None])[0],
            date_from=params.get("date_from", [None])[0],
            date_to=params.get("date_to", [None])[0],
            page=int(params.get("page", ["1"])[0]),
            per_page=int(params.get("per_page", ["30"])[0]),
        )
        self._json(result)

    def _handle_archive_hotlist(self, parsed):
        if not self.archive_manager:
            self._json({"error": "archive not enabled"}, 503)
            return
        params = parse_qs(parsed.query)
        result = self.archive_manager.search_hotlist(
            platform=params.get("platform", [None])[0],
            page=int(params.get("page", ["1"])[0]),
            per_page=int(params.get("per_page", ["30"])[0]),
        )
        self._json(result)

    def _handle_archive_rss(self, parsed):
        if not self.archive_manager:
            self._json({"error": "archive not enabled"}, 503)
            return
        params = parse_qs(parsed.query)
        result = self.archive_manager.search_rss(
            feed_id=params.get("feed_id", [None])[0],
            keyword=params.get("keyword", [None])[0],
            page=int(params.get("page", ["1"])[0]),
            per_page=int(params.get("per_page", ["30"])[0]),
        )
        self._json(result)

    def _json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        logger.debug("VectorAPI: %s", fmt % args)


def _jaccard_similarity(a: str, b: str) -> float:
    """计算两个字符串的 Jaccard 相似度（基于字符集）。"""
    set_a = set(a)
    set_b = set(b)
    if not set_a and not set_b:
        return 1.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


def _start_vector_api(vector_engine, hotlist_vector=None, rss_vector=None, archive_manager=None):
    """在后台线程启动向量搜索 API（仅监听 localhost）"""
    _VectorAPIHandler.vector_engine = vector_engine
    _VectorAPIHandler.hotlist_vector = hotlist_vector
    _VectorAPIHandler.rss_vector = rss_vector
    _VectorAPIHandler.archive_manager = archive_manager
    server = _ThreadingHTTPServer(("127.0.0.1", VECTOR_API_PORT), _VectorAPIHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    logger.info("向量 API 已启动: http://127.0.0.1:%d", VECTOR_API_PORT)


def main():
    config = load_config()
    sched_cfg = config.get("scheduler", {})
    purge_days = sched_cfg.get("purge_days", 7)

    # --- 新闻模块 ---
    news_db = NewsDB()
    aggregator = AKSourceAggregator(db=news_db)
    vector_engine = None
    try:
        vector_engine = NewsVectorEngine()
        vector_engine.initialize()
        logger.info("向量引擎初始化成功")
    except Exception as e:
        logger.error("向量引擎初始化失败: %s，将以无向量模式运行", e)

    # 启动时迁移旧数据
    try:
        migrated = news_db.migrate_category_to_json()
        if migrated > 0 and vector_engine:
            news_db.reclassify_all(vector_engine=vector_engine)
            logger.info("数据迁移完成: %d 条", migrated)
    except Exception as e:
        logger.error("数据迁移失败: %s", e)

    # 首次部署回填 ChromaDB
    if vector_engine:
        try:
            backfill_count = vector_engine.backfill_existing()
            if backfill_count > 0:
                logger.info("回填完成: %d 条", backfill_count)
        except Exception as e:
            logger.error("回填失败: %s", e)

    # --- 启动向量搜索内部 API ---
    # 初始化热榜和 RSS 向量引擎（复用嵌入模型和 ChromaDB 客户端）
    hotlist_vector = None
    rss_vector = None
    if vector_engine:
        try:
            chroma_client = vector_engine.chroma_client
            encode_fn = vector_engine._encode
            hotlist_vector = HotlistVectorEngine()
            hotlist_vector.initialize(chroma_client, encode_fn)
        except Exception as e:
            logger.error("热榜向量引擎初始化失败: %s", e)
        try:
            chroma_client = vector_engine.chroma_client
            encode_fn = vector_engine._encode
            rss_vector = RSSVectorEngine()
            rss_vector.initialize(chroma_client, encode_fn)
        except Exception as e:
            logger.error("RSS 向量引擎初始化失败: %s", e)

    # --- 归档模块 ---
    archive_manager = None
    archive_cfg = config.get("archive", {})
    if archive_cfg.get("enabled"):
        try:
            archive_manager = ArchiveManager(
                archive_dir="data/archive",
                archive_days=archive_cfg.get("archive_days", purge_days),
                retention_days=archive_cfg.get("retention_days", 180),
            )
            if vector_engine:
                archive_manager.initialize_vectors(vector_engine._encode)
            logger.info("归档管理器初始化完成")
        except Exception as e:
            logger.error("归档管理器初始化失败: %s", e)

    _start_vector_api(vector_engine, hotlist_vector, rss_vector, archive_manager=archive_manager)

    # --- 代理配置 ---
    proxy_url = config.get("proxy", {}).get("url")

    # --- 热榜模块 ---
    hotlist_db = HotlistDB()
    hotlist_cfg = config.get("hotlist", {})
    hotlist_fetcher = DataFetcher(api_url=hotlist_cfg.get("api_url"), proxy_url=proxy_url)

    # --- RSS 模块 ---
    rss_db = RSSDB()
    rss_fetcher = RSSFetcher(proxy_url=proxy_url)

    # 计时器 - 每个模块独立计时
    timers = {"news": 0, "hotlist": 0, "rss": 0}
    intervals = {
        "news": sched_cfg.get("news_interval", 600),
        "hotlist": sched_cfg.get("hotlist_interval", 300),
        "rss": sched_cfg.get("rss_interval", 1800),
    }

    logger.info(
        "调度器启动: news=%ds, hotlist=%ds, rss=%ds, purge=%dd",
        intervals["news"], intervals["hotlist"], intervals["rss"], purge_days,
    )

    # 启动时立即执行一次
    for module in ["news", "hotlist", "rss"]:
        _run_module(module, news_db, aggregator, vector_engine,
                    hotlist_db, hotlist_fetcher, hotlist_cfg,
                    rss_db, rss_fetcher, purge_days,
                    hotlist_vector=hotlist_vector, rss_vector=rss_vector,
                    archive_manager=archive_manager)

    # 加载抓取触发器
    from utils.crawl_trigger import CrawlTrigger
    crawl_trigger = CrawlTrigger()

    # Scheduler 心跳文件，供 Web 层判断 scheduler 是否在线
    heartbeat_path = "data/.scheduler_heartbeat"
    os.makedirs("data", exist_ok=True)

    # Monitor 监控任务配置
    monitor_cfg = _get_monitor_config()
    monitor_timer = 0

    # WCF 事件轮询配置
    wcf_cfg = _get_wcf_config()
    wcf_timer = 0

    while True:
        time.sleep(1)

        # 更新心跳
        try:
            with open(heartbeat_path, "w") as f:
                f.write(datetime.now().isoformat())
        except Exception:
            pass

        # 检查 Web 触发的抓取信号
        try:
            pending = crawl_trigger.poll_pending()
            for module in pending:
                logger.info("收到 Web 触发的抓取信号: %s", module)
                _run_module(module, news_db, aggregator, vector_engine,
                            hotlist_db, hotlist_fetcher, hotlist_cfg,
                            rss_db, rss_fetcher, purge_days,
                            hotlist_vector=hotlist_vector, rss_vector=rss_vector,
                            archive_manager=archive_manager)
                crawl_trigger.mark_done(module)
        except Exception as e:
            logger.error("处理抓取信号失败: %s", e)

        # 定时调度
        for module in ["news", "hotlist", "rss"]:
            timers[module] += 1
            if timers[module] >= intervals[module]:
                timers[module] = 0
                _run_module(module, news_db, aggregator, vector_engine,
                            hotlist_db, hotlist_fetcher, hotlist_cfg,
                            rss_db, rss_fetcher, purge_days,
                            hotlist_vector=hotlist_vector, rss_vector=rss_vector,
                            archive_manager=archive_manager)

        # Monitor 监控任务检查
        if monitor_cfg["enabled"]:
            monitor_timer += 1
            if monitor_timer >= monitor_cfg["check_interval"]:
                monitor_timer = 0
                _check_monitor_tasks()

        # WCF 事件轮询
        if wcf_cfg["enabled"]:
            wcf_timer += 1
            if wcf_timer >= wcf_cfg["poll_interval"]:
                wcf_timer = 0
                _poll_wcf_events()


def _get_monitor_config():
    """读取 monitor 配置。"""
    config = load_config()
    monitor_cfg = config.get("monitor", {})
    return {
        "enabled": monitor_cfg.get("enabled", False),
        "check_interval": monitor_cfg.get("check_interval", 60),
        "schedules": monitor_cfg.get("schedules", {
            "daily_morning": "08:00",
            "daily_evening": "20:00",
        }),
    }


def _check_monitor_tasks():
    """检查到期任务，异步执行。防重入由 MonitorService 内部锁保证。"""
    try:
        from modules.monitor.service import get_monitor_service
        svc = get_monitor_service()
        for task in svc.get_due_tasks():
            t = threading.Thread(target=svc.run_task, args=(task["id"],), daemon=True)
            t.start()
    except Exception as e:
        logger.error("Monitor check failed: %s", e)


def _get_wcf_config():
    """读取 WCF 配置。"""
    config = load_config()
    wcf_cfg = config.get("wcf", {})
    return {
        "enabled": wcf_cfg.get("enabled", False),
        "poll_interval": wcf_cfg.get("poll_interval", 3),
    }


def _poll_wcf_events():
    """轮询 wcfLink 事件并消费。"""
    try:
        from modules.wcf.service import consume_events
        consume_events()
    except Exception as e:
        logger.error("WCF event poll failed: %s", e)


def _run_module(module, news_db, aggregator, vector_engine,
                hotlist_db, hotlist_fetcher, hotlist_cfg,
                rss_db, rss_fetcher, purge_days,
                hotlist_vector=None, rss_vector=None, archive_manager=None):
    """运行单个模块的采集，失败不影响其他模块"""
    try:
        if module == "news":
            _run_news(news_db, aggregator, vector_engine, purge_days,
                      archive_manager=archive_manager)
        elif module == "hotlist":
            _run_hotlist(hotlist_db, hotlist_fetcher, hotlist_cfg,
                         hotlist_vector=hotlist_vector,
                         archive_manager=archive_manager)
        elif module == "rss":
            _run_rss(rss_db, rss_fetcher, purge_days,
                     rss_vector=rss_vector, archive_manager=archive_manager)
    except Exception as e:
        logger.error("%s 采集异常: %s", module, e)


def _run_news(db, aggregator, vector_engine, purge_days, archive_manager=None):
    """新闻采集 + 向量处理"""
    skip_purge = archive_manager is not None
    result = aggregator.fetch_and_store(purge_days=purge_days, skip_purge=skip_purge)
    new_items = result.get("new_items", [])
    new_row_ids = result.get("new_row_ids", [])

    if vector_engine and new_items:
        _vector_pipeline(vector_engine, db, new_items, new_row_ids)

    # 归档迁移（替代 purge）
    if archive_manager:
        try:
            archive_manager._migrate_news(db, vector_engine)
        except Exception as e:
            logger.error("新闻归档迁移失败: %s", e)
    elif vector_engine and result["purged"] > 0:
        # 无归档模式：保留原有 ChromaDB 同步清理
        try:
            vector_engine.sync_chroma_purge()
        except Exception as e:
            logger.error("ChromaDB 清理失败: %s", e)

    logger.info(
        "新闻: 原始%d, 新增%d, 清理%d",
        result["total_raw"], result["new_added"], result["purged"],
    )


def _vector_pipeline(vector_engine, db, items, row_ids):
    """向量处理管线：语义去重 → 分类 → 聚类 → 写入 ChromaDB"""
    try:
        # 语义去重
        deduped = vector_engine.semantic_dedup(items)
        deduped_set = {(d["title"], d.get("content", "")[:100]) for d in deduped}

        deduped_items, deduped_row_ids = [], []
        removed_row_ids = []
        for item, rid in zip(items, row_ids):
            key = (item["title"], item.get("content", "")[:100])
            if key in deduped_set:
                deduped_items.append(item)
                deduped_row_ids.append(rid)
            else:
                removed_row_ids.append(rid)

        if removed_row_ids:
            conn = db._get_conn()
            placeholders = ",".join("?" * len(removed_row_ids))
            conn.execute(
                f"DELETE FROM news WHERE id IN ({placeholders})", removed_row_ids
            )
            conn.commit()
            conn.close()
            logger.info("语义去重: 从 SQLite 删除 %d 条", len(removed_row_ids))

        if not deduped_items:
            return

        # 分类
        categories = vector_engine.classify_items(deduped_items)
        # 聚类
        cluster_ids = vector_engine.assign_clusters(deduped_items)

        # 更新 SQLite
        conn = db._get_conn()
        for rid, cat, cid in zip(deduped_row_ids, categories, cluster_ids):
            cat_json = json.dumps(cat, ensure_ascii=False) if isinstance(cat, list) else cat
            conn.execute(
                "UPDATE news SET category = ?, cluster_id = ? WHERE id = ?",
                (cat_json, cid, rid),
            )
        conn.commit()
        conn.close()

        # 写入 ChromaDB
        vector_engine.upsert_to_chroma(
            deduped_items, deduped_row_ids, categories, cluster_ids
        )
    except Exception as e:
        logger.error("向量处理管线异常: %s", e)


def _run_hotlist(db, fetcher, config, hotlist_vector=None, archive_manager=None):
    """热榜采集 + 向量化"""
    platforms = config.get("platforms") or None
    items, failed = fetcher.fetch_all_platforms(platforms)
    crawl_time = datetime.now().isoformat()
    inserted = db.insert_batch(items, crawl_time)
    new_count = inserted["new"] if isinstance(inserted, dict) else inserted

    # 新条目向量化
    if hotlist_vector and hotlist_vector._initialized and new_count > 0:
        try:
            # 获取新增的条目（crawl_time 匹配的）
            conn = db._get_conn()
            rows = conn.execute(
                "SELECT id, title, url, platform, platform_name, hot_rank, crawl_time "
                "FROM hot_items WHERE crawl_time = ?",
                (crawl_time,),
            ).fetchall()
            conn.close()
            if rows:
                vector_items = [dict(r) for r in rows]
                hotlist_vector.upsert_items(vector_items)
        except Exception as e:
            logger.error("热榜向量化失败: %s", e)

    # 清理过期数据（归档模式用迁移替代，否则硬删）
    if archive_manager:
        try:
            archive_manager._migrate_hotlist(db, hotlist_vector)
        except Exception as e:
            logger.error("热榜归档迁移失败: %s", e)
    else:
        purged = db.purge_old(days=7)
        if hotlist_vector and hotlist_vector._initialized and purged > 0:
            try:
                conn = db._get_conn()
                existing_ids = {r[0] for r in conn.execute("SELECT id FROM hot_items").fetchall()}
                conn.close()
                hotlist_vector.sync_purge(existing_ids)
            except Exception as e:
                logger.error("热榜 ChromaDB 清理失败: %s", e)

    logger.info("热榜: 抓取%d条, 新增%d条, 更新%d条, 失败%d平台",
                len(items), new_count,
                inserted.get("updated", 0) if isinstance(inserted, dict) else 0,
                len(failed))


def _run_rss(db, fetcher, purge_days, rss_vector=None, archive_manager=None):
    """RSS 采集 + 向量化"""
    result = fetcher.fetch_and_store(db)

    # 新条目向量化
    if rss_vector and rss_vector._initialized and result.get("total_items", 0) > 0:
        try:
            # 获取最近的条目进行向量化
            feeds = db.get_feeds(enabled_only=True)
            all_items = []
            for feed in feeds:
                items = db.get_items(feed_id=feed["id"], days=1, page=1, page_size=50)
                for it in items["items"]:
                    it["feed_name"] = feed["name"]
                all_items.extend(items["items"])
            if all_items:
                rss_vector.upsert_items(all_items)
        except Exception as e:
            logger.error("RSS 向量化失败: %s", e)

    # 清理过期数据（归档模式用迁移替代，否则硬删）
    if archive_manager:
        try:
            archive_manager._migrate_rss(db, rss_vector)
        except Exception as e:
            logger.error("RSS 归档迁移失败: %s", e)
    else:
        purged = db.purge_old(days=purge_days)
        if rss_vector and rss_vector._initialized and purged > 0:
            try:
                conn = db._get_conn()
                existing_ids = {r[0] for r in conn.execute("SELECT id FROM rss_items").fetchall()}
                conn.close()
                rss_vector.sync_purge(existing_ids)
            except Exception as e:
                logger.error("RSS ChromaDB 清理失败: %s", e)

    logger.info(
        "RSS: 获取%d源, 失败%d, 共%d条",
        result.get("fetched", 0), result.get("failed", 0), result.get("total_items", 0),
    )


if __name__ == "__main__":
    main()
