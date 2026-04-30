"""
向量服务 - 独立进程运行

加载 ONNX 模型 + ChromaDB，提供 HTTP API（端口 5001）。
替代原 scheduler 中的向量引擎，使调度器不加载 torch。
"""
import json
import logging
import os
import signal
import sqlite3
import threading
import time
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs
from concurrent.futures import ThreadPoolExecutor

os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_OFFLINE"] = "1"

import numpy as np
import onnxruntime as ort
from transformers import AutoTokenizer
import chromadb

from modules.news.vector import NewsVectorEngine
from modules.hotlist.vector import HotlistVectorEngine
from modules.rss.vector import RSSVectorEngine
from modules.archive.manager import ArchiveManager
from utils.config import load_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [vector-svc] %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

VECTOR_API_PORT = 5001
MAX_WORKERS = 4  # 限制并发线程数，防止内存爆炸


# ── HTTP 服务（线程池限制） ──────────────────────────────────

class _ThreadPoolHTTPServer(HTTPServer):
    """带线程池限制的 HTTP 服务器，最多 MAX_WORKERS 个并发请求。"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)

    def process_request(self, request, client_address):
        self._executor.submit(self._process_request_thread, request, client_address)

    def _process_request_thread(self, request, client_address):
        try:
            self.finish_request(request, client_address)
        except Exception:
            self.handle_error(request, client_address)
        finally:
            self.shutdown_request(request)


class _Handler(BaseHTTPRequestHandler):
    """向量服务 HTTP 处理器"""

    vector_engine: NewsVectorEngine | None = None
    hotlist_vector: HotlistVectorEngine | None = None
    rss_vector: RSSVectorEngine | None = None
    archive_manager: ArchiveManager | None = None

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/health":
            self._json({"ok": True,
                        "model_loaded": self.vector_engine is not None and self.vector_engine._initialized})
        elif path == "/semantic_search":
            self._handle_search(parsed)
        elif path == "/archive/news":
            self._handle_archive_news(parsed)
        elif path == "/archive/hotlist":
            self._handle_archive_hotlist(parsed)
        elif path == "/archive/rss":
            self._handle_archive_rss(parsed)
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/chat_search":
            self._handle_chat_search()
        elif path == "/pipeline/news":
            self._handle_pipeline_news()
        elif path == "/pipeline/hotlist":
            self._handle_pipeline_hotlist()
        elif path == "/pipeline/rss":
            self._handle_pipeline_rss()
        elif path == "/purge/news":
            self._handle_purge_news()
        elif path == "/purge/hotlist":
            self._handle_purge_hotlist()
        elif path == "/purge/rss":
            self._handle_purge_rss()
        elif path == "/purge/orphans":
            self._handle_purge_orphans()
        elif path == "/backfill":
            self._handle_backfill()
        elif path == "/migrate_categories":
            self._handle_migrate_categories()
        elif path == "/archive/migrate_news":
            self._handle_archive_migrate_news()
        elif path == "/archive/migrate_hotlist":
            self._handle_archive_migrate_hotlist()
        elif path == "/archive/migrate_rss":
            self._handle_archive_migrate_rss()
        else:
            self._json({"error": "not found"}, 404)

    # ── 新闻向量管线 ─────────────────────────────────────────

    def _handle_pipeline_news(self):
        """完整新闻向量管线：去重 -> 分类 -> 聚类 -> 写入 ChromaDB"""
        data = self._read_json()
        if not data:
            return
        items = data.get("items", [])
        row_ids = data.get("row_ids", [])
        if not items or not self.vector_engine:
            self._json({"kept_items": items, "kept_row_ids": row_ids})
            return

        try:
            # 1. 语义去重
            deduped = self.vector_engine.semantic_dedup(items)
            deduped_set = {(d["title"], d.get("content", "")[:100]) for d in deduped}
            kept_items, kept_row_ids = [], []
            removed_row_ids = []
            for item, rid in zip(items, row_ids):
                key = (item["title"], item.get("content", "")[:100])
                if key in deduped_set:
                    kept_items.append(item)
                    kept_row_ids.append(rid)
                else:
                    removed_row_ids.append(rid)

            removed = len(removed_row_ids)
            logger.info("语义去重: 移除 %d 条", removed)

            if not kept_items:
                self._json({"kept_items": [], "kept_row_ids": [],
                            "removed_row_ids": removed_row_ids})
                return

            # 2. 分类
            categories = self.vector_engine.classify_items(kept_items)
            # 3. 聚类
            cluster_ids = self.vector_engine.assign_clusters(kept_items)
            # 4. 写入 ChromaDB
            self.vector_engine.upsert_to_chroma(
                kept_items, kept_row_ids, categories, cluster_ids
            )

            self._json({
                "kept_items": kept_items,
                "kept_row_ids": kept_row_ids,
                "categories": categories,
                "cluster_ids": cluster_ids,
                "removed_row_ids": removed_row_ids,
            })
        except Exception as e:
            logger.error("新闻向量管线异常: %s", e)
            self._json({"error": str(e)}, 500)

    # ── 热榜/RSS 向量化 ──────────────────────────────────────

    def _handle_pipeline_hotlist(self):
        data = self._read_json()
        if not data:
            return
        items = data.get("items", [])
        if not items or not self.hotlist_vector:
            self._json({"upserted": 0})
            return
        try:
            count = self.hotlist_vector.upsert_items(items)
            self._json({"upserted": count})
        except Exception as e:
            logger.error("热榜向量化异常: %s", e)
            self._json({"error": str(e)}, 500)

    def _handle_pipeline_rss(self):
        data = self._read_json()
        if not data:
            return
        items = data.get("items", [])
        if not items or not self.rss_vector:
            self._json({"upserted": 0})
            return
        try:
            count = self.rss_vector.upsert_items(items)
            self._json({"upserted": count})
        except Exception as e:
            logger.error("RSS 向量化异常: %s", e)
            self._json({"error": str(e)}, 500)

    # ── 清理 ─────────────────────────────────────────────────

    def _handle_purge_news(self):
        if not self.vector_engine:
            self._json({"purged": 0})
            return
        try:
            count = self.vector_engine.sync_chroma_purge()
            self._json({"purged": count})
        except Exception as e:
            self._json({"error": str(e)}, 500)

    def _handle_purge_hotlist(self):
        data = self._read_json()
        if not data:
            return
        existing_ids = set(data.get("existing_ids", []))
        if not self.hotlist_vector:
            self._json({"purged": 0})
            return
        try:
            count = self.hotlist_vector.sync_purge(existing_ids)
            self._json({"purged": count})
        except Exception as e:
            self._json({"error": str(e)}, 500)

    def _handle_purge_rss(self):
        data = self._read_json()
        if not data:
            return
        existing_ids = set(data.get("existing_ids", []))
        if not self.rss_vector:
            self._json({"purged": 0})
            return
        try:
            count = self.rss_vector.sync_purge(existing_ids)
            self._json({"purged": count})
        except Exception as e:
            self._json({"error": str(e)}, 500)

    def _handle_purge_orphans(self):
        """清理所有 collection 中的孤儿向量（SQLite 已删除但 ChromaDB 仍存在的条目）。"""
        stats = {}
        try:
            if self.vector_engine:
                stats["news"] = self.vector_engine.sync_chroma_purge()
        except Exception as e:
            stats["news_error"] = str(e)
        try:
            if self.hotlist_vector:
                import sqlite3 as _sql
                conn = _sql.connect("/opt/news_aggregator/data/hotlist.db")
                ids = {r[0] for r in conn.execute("SELECT id FROM hot_items").fetchall()}
                conn.close()
                stats["hotlist"] = self.hotlist_vector.sync_purge(ids)
        except Exception as e:
            stats["hotlist_error"] = str(e)
        try:
            if self.rss_vector:
                import sqlite3 as _sql
                conn = _sql.connect("/opt/news_aggregator/data/rss.db")
                ids = {r[0] for r in conn.execute("SELECT id FROM rss_items").fetchall()}
                conn.close()
                stats["rss"] = self.rss_vector.sync_purge(ids)
        except Exception as e:
            stats["rss_error"] = str(e)
        self._json(stats)

    # ── 回填 & 迁移 ──────────────────────────────────────────

    def _handle_backfill(self):
        if not self.vector_engine:
            self._json({"backfilled": 0})
            return
        try:
            count = self.vector_engine.backfill_existing()
            self._json({"backfilled": count})
        except Exception as e:
            self._json({"error": str(e)}, 500)

    def _handle_migrate_categories(self):
        if not self.vector_engine:
            self._json({"migrated": 0})
            return
        try:
            from modules.news.db import NewsDB
            db = NewsDB()
            migrated = db.migrate_category_to_json()
            if migrated > 0:
                db.reclassify_all(vector_engine=self.vector_engine)
            self._json({"migrated": migrated})
        except Exception as e:
            self._json({"error": str(e)}, 500)

    # ── 归档迁移 ─────────────────────────────────────────────

    def _handle_archive_migrate_news(self):
        if not self.archive_manager:
            self._json({"error": "archive not enabled"}, 503)
            return
        try:
            from modules.news.db import NewsDB
            db = NewsDB()
            result = self.archive_manager._migrate_news(db, self.vector_engine)
            self._json(result)
        except Exception as e:
            logger.error("新闻归档迁移失败: %s", e)
            self._json({"error": str(e)}, 500)

    def _handle_archive_migrate_hotlist(self):
        if not self.archive_manager:
            self._json({"error": "archive not enabled"}, 503)
            return
        try:
            from modules.hotlist.db import HotlistDB
            db = HotlistDB()
            result = self.archive_manager._migrate_hotlist(db, self.hotlist_vector)
            self._json(result)
        except Exception as e:
            logger.error("热榜归档迁移失败: %s", e)
            self._json({"error": str(e)}, 500)

    def _handle_archive_migrate_rss(self):
        if not self.archive_manager:
            self._json({"error": "archive not enabled"}, 503)
            return
        try:
            from modules.rss.db import RSSDB
            db = RSSDB()
            result = self.archive_manager._migrate_rss(db, self.rss_vector)
            self._json(result)
        except Exception as e:
            logger.error("RSS 归档迁移失败: %s", e)
            self._json({"error": str(e)}, 500)

    # ── 搜索（原有功能） ─────────────────────────────────────

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

        if not results and self.archive_manager and self.archive_manager._vector_ready:
            try:
                results = self.archive_manager.semantic_search_news(query, n=n)
                for r in results:
                    r["source_name"] = (r.get("source_name", "") + " [archive]").strip()
            except Exception as e:
                logger.warning("冷库语义搜索回查失败: %s", e)

        self._json(results)

    def _handle_chat_search(self):
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

        query_emb = self.vector_engine._encode([query])[0]

        all_results = []
        news_results = self.vector_engine.semantic_search(query, n=top_k)
        for r in news_results:
            r["source_type"] = r.get("source_type", "news")
            all_results.append(r)

        if self.hotlist_vector and self.hotlist_vector._initialized:
            hot_results = self.hotlist_vector.semantic_search(query_emb, top_k=top_k)
            all_results.extend(hot_results)

        if self.rss_vector and self.rss_vector._initialized:
            rss_results = self.rss_vector.semantic_search(query_emb, top_k=top_k)
            all_results.extend(rss_results)

        all_results.sort(key=lambda x: x.get("distance", 1.0))

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

    # ── 冷库浏览 ─────────────────────────────────────────────

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

    # ── 工具方法 ─────────────────────────────────────────────

    def _read_json(self):
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            self._json({"error": "empty body"}, 400)
            return None
        body = self.rfile.read(content_length)
        try:
            return json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._json({"error": "invalid JSON"}, 400)
            return None

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
    set_a, set_b = set(a), set(b)
    if not set_a and not set_b:
        return 1.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


# ── 内存看门狗 ──────────────────────────────────────────────

MEMORY_LIMIT_MB = 2000   # RSS 超过此值主动退出，由 systemd 重启
MEMORY_CHECK_SEC = 60    # 每 60 秒检查一次


def _memory_watchdog():
    """后台线程：定期检查 RSS，超限则主动退出让 systemd 重启。

    解决 ChromaDB PersistentClient HNSW 索引内存持续增长的问题。
    退出码 0 让 systemd 视为正常退出，配合 Restart=always 自动拉起。
    """
    while True:
        time.sleep(MEMORY_CHECK_SEC)
        try:
            with open(f"/proc/self/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        rss_kb = int(line.split()[1])
                        rss_mb = rss_kb // 1024
                        break
                else:
                    continue

            if rss_mb > MEMORY_LIMIT_MB:
                logger.warning(
                    "内存看门狗: RSS=%dMB 超过阈值 %dMB，主动退出等待重启",
                    rss_mb, MEMORY_LIMIT_MB,
                )
                os._exit(0)
            else:
                logger.debug("内存看门狗: RSS=%dMB", rss_mb)
        except Exception:
            pass


def main():
    config = load_config()
    sched_cfg = config.get("scheduler", {})

    # --- 新闻向量引擎 ---
    vector_engine = None
    try:
        vector_engine = NewsVectorEngine()
        vector_engine.initialize()
        logger.info("新闻向量引擎初始化成功")
    except Exception as e:
        logger.error("新闻向量引擎初始化失败: %s", e)

    # 启动时迁移旧数据
    if vector_engine:
        try:
            migrated = _migrate_categories(vector_engine)
            logger.info("数据迁移: %d 条", migrated)
        except Exception as e:
            logger.error("数据迁移失败: %s", e)

    # 回填（仅首次部署，向量数为 0 时才执行，避免重启时重复回填吃内存）
    if vector_engine and vector_engine.collection.count() == 0:
        try:
            count = vector_engine.backfill_existing()
            if count > 0:
                logger.info("回填完成: %d 条", count)
        except Exception as e:
            logger.error("回填失败: %s", e)
    else:
        logger.info("跳过回填（已有向量数据）")

    # --- 热榜 & RSS 向量引擎 ---
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

    # --- 归档模块（配置控制，禁用时跳过） ---
    archive_manager = None
    archive_cfg = config.get("archive", {})
    if archive_cfg.get("enabled"):
        try:
            archive_manager = ArchiveManager(
                archive_dir="data/archive",
                archive_days=archive_cfg.get("archive_days", sched_cfg.get("purge_days", 7)),
                retention_days=archive_cfg.get("retention_days", 180),
            )
            if vector_engine:
                archive_manager.initialize_vectors(vector_engine._encode)
            logger.info("归档管理器初始化完成")
        except Exception as e:
            logger.error("归档管理器初始化失败: %s", e)
    else:
        logger.info("归档模块未启用，跳过")

    # --- 启动 HTTP 服务（线程池限制） ---
    _Handler.vector_engine = vector_engine
    _Handler.hotlist_vector = hotlist_vector
    _Handler.rss_vector = rss_vector
    _Handler.archive_manager = archive_manager

    server = _ThreadPoolHTTPServer(("127.0.0.1", VECTOR_API_PORT), _Handler)
    logger.info("向量服务已启动: http://127.0.0.1:%d (max_workers=%d)", VECTOR_API_PORT, MAX_WORKERS)

    # 启动内存看门狗
    t = threading.Thread(target=_memory_watchdog, daemon=True)
    t.start()
    logger.info("内存看门狗已启动: 限值=%dMB, 检查间隔=%ds", MEMORY_LIMIT_MB, MEMORY_CHECK_SEC)

    server.serve_forever()


def _migrate_categories(vector_engine):
    """启动时迁移旧分类数据"""
    from modules.news.db import NewsDB
    db = NewsDB()
    migrated = db.migrate_category_to_json()
    if migrated > 0:
        db.reclassify_all(vector_engine=vector_engine)
    return migrated


if __name__ == "__main__":
    main()
