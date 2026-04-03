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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [scheduler] %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


# ── 内部向量 API ─────────────────────────────────────────────

VECTOR_API_PORT = 5001


class _VectorAPIHandler(BaseHTTPRequestHandler):
    """轻量 HTTP 处理器，代理 scheduler 已加载的向量引擎"""

    vector_engine: NewsVectorEngine | None = None

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/semantic_search":
            self._handle_search(parsed)
        elif parsed.path == "/health":
            self._json({"ok": True, "model_loaded": self.vector_engine is not None})
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
        self._json(results)

    def _json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        logger.debug("VectorAPI: %s", fmt % args)


def _start_vector_api(vector_engine):
    """在后台线程启动向量搜索 API（仅监听 localhost）"""
    _VectorAPIHandler.vector_engine = vector_engine
    server = HTTPServer(("127.0.0.1", VECTOR_API_PORT), _VectorAPIHandler)
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
    if vector_engine:
        _start_vector_api(vector_engine)

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
                    rss_db, rss_fetcher, purge_days)

    while True:
        time.sleep(1)
        for module in ["news", "hotlist", "rss"]:
            timers[module] += 1
            if timers[module] >= intervals[module]:
                timers[module] = 0
                _run_module(module, news_db, aggregator, vector_engine,
                            hotlist_db, hotlist_fetcher, hotlist_cfg,
                            rss_db, rss_fetcher, purge_days)


def _run_module(module, news_db, aggregator, vector_engine,
                hotlist_db, hotlist_fetcher, hotlist_cfg,
                rss_db, rss_fetcher, purge_days):
    """运行单个模块的采集，失败不影响其他模块"""
    try:
        if module == "news":
            _run_news(news_db, aggregator, vector_engine, purge_days)
        elif module == "hotlist":
            _run_hotlist(hotlist_db, hotlist_fetcher, hotlist_cfg)
        elif module == "rss":
            _run_rss(rss_db, rss_fetcher, purge_days)
    except Exception as e:
        logger.error("%s 采集异常: %s", module, e)


def _run_news(db, aggregator, vector_engine, purge_days):
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


def _run_hotlist(db, fetcher, config):
    """热榜采集"""
    platforms = config.get("platforms") or None
    items, failed = fetcher.fetch_all_platforms(platforms)
    crawl_time = datetime.now().isoformat()
    inserted = db.insert_batch(items, crawl_time)
    # 清理过期数据
    db.purge_old(days=7)
    logger.info("热榜: 抓取%d条, 入库%d条, 失败%d平台", len(items), inserted, len(failed))


def _run_rss(db, fetcher, purge_days):
    """RSS 采集"""
    result = fetcher.fetch_and_store(db)
    # 清理过期数据
    db.purge_old(days=purge_days)
    logger.info(
        "RSS: 获取%d源, 失败%d, 共%d条",
        result.get("fetched", 0), result.get("failed", 0), result.get("total_items", 0),
    )


if __name__ == "__main__":
    main()
