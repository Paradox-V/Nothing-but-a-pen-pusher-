"""归档管理器 — 热/冷数据迁移

在 scheduler 进程中运行，定期将热库中超过 archive_days 的数据
迁移到独立的冷库（SQLite + ChromaDB），供历史浏览和语义搜索备用。
"""

import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta

import chromadb

from modules.news.vector import NewsVectorEngine
from modules.hotlist.vector import HotlistVectorEngine
from modules.rss.vector import RSSVectorEngine

logger = logging.getLogger(__name__)

MIGRATE_BATCH_SIZE = 500


class ArchiveManager:
    """管理热库 → 冷库的数据迁移。"""

    # 冷库建表 SQL（id 不加 AUTOINCREMENT，允许显式插入）
    ARCHIVE_SCHEMAS = {
        "news": """
            CREATE TABLE IF NOT EXISTS news (
                id INTEGER PRIMARY KEY,
                source_name TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TEXT,
                url TEXT,
                tags TEXT NOT NULL DEFAULT '[]',
                content_hash TEXT UNIQUE NOT NULL,
                category TEXT NOT NULL DEFAULT '其他',
                cluster_id TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_news_created ON news(created_at);
            CREATE INDEX IF NOT EXISTS idx_news_hash ON news(content_hash);
        """,
        "hotlist": """
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
                appear_count INTEGER DEFAULT 1
            );
            CREATE INDEX IF NOT EXISTS idx_hot_crawl_time ON hot_items(crawl_time);
        """,
        "rss_feeds": """
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
        """,
        "rss_items": """
            CREATE TABLE IF NOT EXISTS rss_items (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                feed_id TEXT NOT NULL,
                url TEXT,
                author TEXT,
                summary TEXT,
                published_at DATETIME,
                crawl_time DATETIME NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_rss_feed_id ON rss_items(feed_id);
            CREATE INDEX IF NOT EXISTS idx_rss_crawl_time ON rss_items(crawl_time);
        """,
    }

    def __init__(self, archive_dir: str = "data/archive",
                 archive_days: int = 7, retention_days: int = 180):
        self.archive_dir = archive_dir
        self.archive_days = archive_days
        self.retention_days = retention_days
        self.news_db_path = os.path.join(archive_dir, "news_archive.db")
        self.hotlist_db_path = os.path.join(archive_dir, "hotlist_archive.db")
        self.rss_db_path = os.path.join(archive_dir, "rss_archive.db")
        self.archive_chroma_dir = os.path.join(archive_dir, "chroma_archive")

        os.makedirs(archive_dir, exist_ok=True)
        os.makedirs(self.archive_chroma_dir, exist_ok=True)
        self._init_archive_dbs()

        # 向量引擎延迟初始化
        self.news_vector: NewsVectorEngine | None = None
        self.hotlist_vector: HotlistVectorEngine | None = None
        self.rss_vector: RSSVectorEngine | None = None
        self._vector_ready = False

    def _init_archive_dbs(self):
        """在冷库路径创建表结构。"""
        # news
        conn = sqlite3.connect(self.news_db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(self.ARCHIVE_SCHEMAS["news"])
        conn.close()
        # hotlist
        conn = sqlite3.connect(self.hotlist_db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(self.ARCHIVE_SCHEMAS["hotlist"])
        conn.close()
        # rss (feeds + items)
        conn = sqlite3.connect(self.rss_db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(self.ARCHIVE_SCHEMAS["rss_feeds"])
        conn.executescript(self.ARCHIVE_SCHEMAS["rss_items"])
        conn.close()
        logger.info("冷库数据库初始化完成")

    def initialize_vectors(self, encode_fn):
        """初始化冷向量引擎。失败时只禁用语义搜索，不影响 DB 归档。"""
        try:
            archive_chroma = chromadb.PersistentClient(path=self.archive_chroma_dir)
            self.news_vector = NewsVectorEngine(db_path=self.news_db_path)
            self.news_vector.initialize_with_client(
                archive_chroma, encode_fn, "news_archive")
            self.hotlist_vector = HotlistVectorEngine(db_path=self.hotlist_db_path)
            self.hotlist_vector.initialize(
                archive_chroma, encode_fn, collection_name="hotlist_archive")
            self.rss_vector = RSSVectorEngine(db_path=self.rss_db_path)
            self.rss_vector.initialize(
                archive_chroma, encode_fn, collection_name="rss_archive")
            self._vector_ready = True
            logger.info("冷向量引擎初始化完成")
        except Exception as e:
            logger.error("冷向量引擎初始化失败，语义搜索回查将不可用: %s", e)
            self._vector_ready = False

    @property
    def cutoff(self) -> str:
        """归档截止时间字符串。"""
        return (datetime.now() - timedelta(days=self.archive_days)).strftime(
            "%Y-%m-%d %H:%M:%S")

    # ── 迁移入口 ─────────────────────────────────────────────

    def migrate_all(self, hot_news_db, hot_news_vector,
                    hot_hotlist_db, hot_hotlist_vector,
                    hot_rss_db, hot_rss_vector) -> dict:
        """调度三模块迁移 + 冷库过期清理。"""
        stats = {}
        try:
            stats["news"] = self._migrate_news(hot_news_db, hot_news_vector)
        except Exception as e:
            logger.error("新闻归档迁移失败: %s", e)
            stats["news"] = {"error": str(e)}
        try:
            stats["hotlist"] = self._migrate_hotlist(hot_hotlist_db, hot_hotlist_vector)
        except Exception as e:
            logger.error("热榜归档迁移失败: %s", e)
            stats["hotlist"] = {"error": str(e)}
        try:
            stats["rss"] = self._migrate_rss(hot_rss_db, hot_rss_vector)
        except Exception as e:
            logger.error("RSS 归档迁移失败: %s", e)
            stats["rss"] = {"error": str(e)}
        try:
            stats["purge"] = self._purge_archive()
        except Exception as e:
            logger.error("冷库过期清理失败: %s", e)
        return stats

    # ── 新闻迁移 ─────────────────────────────────────────────

    def _migrate_news(self, hot_db, hot_vector) -> dict:
        total_migrated = 0
        while True:
            rows = hot_db.get_archive_candidates(self.cutoff, limit=MIGRATE_BATCH_SIZE)
            if not rows:
                break
            ids = [r["id"] for r in rows]
            # 1. 写冷库
            self._insert_news_batch(rows)
            # 2. 写冷向量（不删热向量）
            chroma_migrated = 0
            if self._vector_ready and hot_vector and hot_vector._initialized:
                chroma_migrated = self._copy_chroma(
                    hot_vector.collection, self.news_vector.collection, "", ids)
            # 3. 校验冷库 DB
            if not self._verify_ids_in_db(self.news_db_path, "news", ids):
                logger.error("新闻冷库 DB 校验失败，跳过本批删除")
                break
            # 4. 校验冷向量
            if self._vector_ready and chroma_migrated > 0:
                if not self._verify_ids_in_chroma(self.news_vector.collection, "", ids):
                    logger.error("新闻冷向量校验失败，跳过本批删除")
                    break
            # 5. 删热库
            hot_db.delete_by_ids(ids)
            # 6. 删热向量
            if self._vector_ready and hot_vector and hot_vector._initialized:
                self._delete_chroma_ids(hot_vector.collection, "", ids)
            total_migrated += len(ids)
            if len(rows) < MIGRATE_BATCH_SIZE:
                break
        logger.info("新闻归档: 迁移 %d 条", total_migrated)
        return {"migrated": total_migrated}

    def _insert_news_batch(self, rows: list[dict]) -> int:
        """批量插入新闻到冷库（INSERT OR IGNORE 幂等）。"""
        conn = sqlite3.connect(self.news_db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        inserted = 0
        try:
            for r in rows:
                try:
                    tags = r.get("tags", "[]")
                    if not isinstance(tags, str):
                        tags = json.dumps(tags, ensure_ascii=False)
                    category = r.get("category", "其他")
                    if not isinstance(category, str):
                        category = json.dumps(category, ensure_ascii=False)
                    conn.execute(
                        """INSERT OR IGNORE INTO news
                           (id, source_name, title, content, timestamp, url, tags,
                            content_hash, category, cluster_id, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (r["id"], r["source_name"], r["title"], r["content"],
                         r.get("timestamp"), r.get("url"),
                         tags, r["content_hash"],
                         category, r.get("cluster_id"),
                         r.get("created_at")),
                    )
                    inserted += 1
                except sqlite3.IntegrityError:
                    pass
            conn.commit()
        finally:
            conn.close()
        return inserted

    # ── 热榜迁移 ─────────────────────────────────────────────

    def _migrate_hotlist(self, hot_db, hot_vector) -> dict:
        total_migrated = 0
        while True:
            rows = hot_db.get_archive_candidates(self.cutoff, limit=MIGRATE_BATCH_SIZE)
            if not rows:
                break
            ids = [r["id"] for r in rows]
            # 1. 写冷库
            self._insert_hotlist_batch(rows)
            # 2. 写冷向量
            chroma_migrated = 0
            if self._vector_ready and hot_vector and hot_vector._initialized:
                chroma_migrated = self._copy_chroma(
                    hot_vector.collection, self.hotlist_vector.collection, "hot_", ids)
            # 3. 校验
            if not self._verify_ids_in_db(self.hotlist_db_path, "hot_items", ids):
                logger.error("热榜冷库校验失败，跳过本批删除")
                break
            if self._vector_ready and chroma_migrated > 0:
                if not self._verify_ids_in_chroma(self.hotlist_vector.collection, "hot_", ids):
                    logger.error("热榜冷向量校验失败，跳过本批删除")
                    break
            # 4. 删热库 + 热向量
            hot_db.delete_by_ids(ids)
            if self._vector_ready and hot_vector and hot_vector._initialized:
                self._delete_chroma_ids(hot_vector.collection, "hot_", ids)
            total_migrated += len(ids)
            if len(rows) < MIGRATE_BATCH_SIZE:
                break
        logger.info("热榜归档: 迁移 %d 条", total_migrated)
        return {"migrated": total_migrated}

    def _insert_hotlist_batch(self, rows: list[dict]) -> int:
        conn = sqlite3.connect(self.hotlist_db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        inserted = 0
        try:
            for r in rows:
                try:
                    conn.execute(
                        """INSERT OR IGNORE INTO hot_items
                           (id, title, url, platform, platform_name, hot_rank,
                            hot_score, crawl_time, first_time, last_time, appear_count)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (r["id"], r["title"], r.get("url"), r["platform"],
                         r.get("platform_name"), r.get("hot_rank"),
                         r.get("hot_score", ""), r.get("crawl_time"),
                         r.get("first_time"), r.get("last_time"),
                         r.get("appear_count", 1)),
                    )
                    inserted += 1
                except sqlite3.IntegrityError:
                    pass
            conn.commit()
        finally:
            conn.close()
        return inserted

    # ── RSS 迁移 ─────────────────────────────────────────────

    def _migrate_rss(self, hot_db, hot_vector) -> dict:
        # 先同步 feeds
        try:
            feeds = hot_db.get_all_feeds()
            self._sync_rss_feeds(feeds)
        except Exception as e:
            logger.warning("RSS feeds 同步失败: %s", e)

        total_migrated = 0
        while True:
            rows = hot_db.get_archive_candidates(self.cutoff, limit=MIGRATE_BATCH_SIZE)
            if not rows:
                break
            ids = [r["id"] for r in rows]
            self._insert_rss_batch(rows)
            chroma_migrated = 0
            if self._vector_ready and hot_vector and hot_vector._initialized:
                chroma_migrated = self._copy_chroma(
                    hot_vector.collection, self.rss_vector.collection, "rss_", ids)
            if not self._verify_ids_in_db(self.rss_db_path, "rss_items", ids):
                logger.error("RSS 冷库校验失败，跳过本批删除")
                break
            if self._vector_ready and chroma_migrated > 0:
                if not self._verify_ids_in_chroma(self.rss_vector.collection, "rss_", ids):
                    logger.error("RSS 冷向量校验失败，跳过本批删除")
                    break
            hot_db.delete_by_ids(ids)
            if self._vector_ready and hot_vector and hot_vector._initialized:
                self._delete_chroma_ids(hot_vector.collection, "rss_", ids)
            total_migrated += len(ids)
            if len(rows) < MIGRATE_BATCH_SIZE:
                break
        logger.info("RSS 归档: 迁移 %d 条", total_migrated)
        return {"migrated": total_migrated}

    def _insert_rss_batch(self, rows: list[dict]) -> int:
        conn = sqlite3.connect(self.rss_db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        inserted = 0
        try:
            for r in rows:
                try:
                    conn.execute(
                        """INSERT OR IGNORE INTO rss_items
                           (id, title, feed_id, url, author, summary,
                            published_at, crawl_time)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (r["id"], r["title"], r.get("feed_id"), r.get("url"),
                         r.get("author"), r.get("summary"),
                         r.get("published_at"), r.get("crawl_time")),
                    )
                    inserted += 1
                except sqlite3.IntegrityError:
                    pass
            conn.commit()
        finally:
            conn.close()
        return inserted

    def _sync_rss_feeds(self, feeds: list[dict]):
        """同步 RSS feeds 到冷库（INSERT OR REPLACE，只增不删）。"""
        if not feeds:
            return
        conn = sqlite3.connect(self.rss_db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            for f in feeds:
                conn.execute(
                    """INSERT OR REPLACE INTO rss_feeds
                       (id, name, url, format, enabled, max_items, max_age_days,
                        last_crawl_time, last_error, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (f["id"], f["name"], f["url"], f.get("format", "rss"),
                     f.get("enabled", 1), f.get("max_items", 20),
                     f.get("max_age_days", 7), f.get("last_crawl_time"),
                     f.get("last_error"), f.get("created_at")),
                )
            conn.commit()
        finally:
            conn.close()

    # ── 向量操作 ─────────────────────────────────────────────

    def _copy_chroma(self, hot_col, archive_col, id_prefix: str, row_ids: list[int]) -> int:
        """复制向量：get from hot → upsert to archive（不删热向量）。返回迁移条数。"""
        chroma_ids = [f"{id_prefix}{rid}" for rid in row_ids]
        total = 0
        for start in range(0, len(chroma_ids), 500):
            batch = chroma_ids[start:start + 500]
            try:
                result = hot_col.get(ids=batch, include=["embeddings", "documents", "metadatas"])
            except Exception:
                continue
            if result["ids"]:
                archive_col.upsert(
                    ids=result["ids"],
                    embeddings=result["embeddings"],
                    documents=result["documents"],
                    metadatas=result["metadatas"],
                )
                total += len(result["ids"])
        return total

    def _delete_chroma_ids(self, collection, id_prefix: str, row_ids: list[int]):
        """删除指定 id 的向量（热库清理用，校验通过后才调用）。"""
        chroma_ids = [f"{id_prefix}{rid}" for rid in row_ids]
        for start in range(0, len(chroma_ids), 500):
            batch = chroma_ids[start:start + 500]
            try:
                collection.delete(ids=batch)
            except Exception as e:
                logger.warning("热向量删除失败: %s", e)

    # ── 校验 ─────────────────────────────────────────────────

    def _verify_ids_in_db(self, db_path: str, table: str, ids: list[int]) -> bool:
        """校验冷库 DB 中是否包含所有指定 id。"""
        if not ids:
            return True
        conn = sqlite3.connect(db_path)
        try:
            placeholders = ",".join("?" * len(ids))
            count = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE id IN ({placeholders})", ids
            ).fetchone()[0]
            return count == len(ids)
        finally:
            conn.close()

    def _verify_ids_in_chroma(self, collection, id_prefix: str, row_ids: list[int]) -> bool:
        """校验冷 ChromaDB 中是否包含所有指定 id。"""
        if not row_ids:
            return True
        chroma_ids = [f"{id_prefix}{rid}" for rid in row_ids]
        try:
            existing = collection.get(ids=chroma_ids, include=[])
            return len(existing["ids"]) == len(chroma_ids)
        except Exception:
            return False

    # ── 冷库过期清理 ─────────────────────────────────────────

    def _purge_archive(self) -> dict:
        """清理冷库中超过 retention_days 的数据。"""
        stats = {}
        cutoff = (datetime.now() - timedelta(days=self.retention_days)).strftime(
            "%Y-%m-%d %H:%M:%S")

        # 新闻
        conn = sqlite3.connect(self.news_db_path)
        cur = conn.execute("DELETE FROM news WHERE created_at < ?", (cutoff,))
        stats["news_purged"] = cur.rowcount
        conn.commit()
        conn.close()

        # 热榜
        conn = sqlite3.connect(self.hotlist_db_path)
        cur = conn.execute("DELETE FROM hot_items WHERE crawl_time < ?", (cutoff,))
        stats["hotlist_purged"] = cur.rowcount
        conn.commit()
        conn.close()

        # RSS
        cutoff_iso = (datetime.now() - timedelta(days=self.retention_days)).isoformat()
        conn = sqlite3.connect(self.rss_db_path)
        cur = conn.execute("DELETE FROM rss_items WHERE crawl_time < ?", (cutoff_iso,))
        stats["rss_purged"] = cur.rowcount
        conn.commit()
        conn.close()

        if any(v > 0 for v in stats.values()):
            logger.info("冷库过期清理: %s", stats)
            # 同步清理冷向量
            if self._vector_ready:
                self._sync_purge_archive_vectors()

        return stats

    def _sync_purge_archive_vectors(self):
        """清理冷 ChromaDB 中已从冷库 SQLite 删除的孤儿向量。"""
        # 新闻
        if self.news_vector and self.news_vector._initialized:
            try:
                self.news_vector.sync_chroma_purge()
            except Exception as e:
                logger.warning("新闻冷向量清理失败: %s", e)
        # 热榜
        if self.hotlist_vector and self.hotlist_vector._initialized:
            try:
                conn = sqlite3.connect(self.hotlist_db_path)
                existing_ids = {r[0] for r in conn.execute("SELECT id FROM hot_items").fetchall()}
                conn.close()
                self.hotlist_vector.sync_purge(
                    {f"hot_{rid}" for rid in existing_ids})
            except Exception as e:
                logger.warning("热榜冷向量清理失败: %s", e)
        # RSS
        if self.rss_vector and self.rss_vector._initialized:
            try:
                conn = sqlite3.connect(self.rss_db_path)
                existing_ids = {r[0] for r in conn.execute("SELECT id FROM rss_items").fetchall()}
                conn.close()
                self.rss_vector.sync_purge(
                    {f"rss_{rid}" for rid in existing_ids})
            except Exception as e:
                logger.warning("RSS 冷向量清理失败: %s", e)

    # ── 冷库搜索接口 ─────────────────────────────────────────

    def search_news(self, keyword=None, date_from=None, date_to=None,
                    page=1, per_page=30) -> dict:
        """冷库新闻浏览（SQL 查询）。"""
        conditions = ["1=1"]
        params = []
        if keyword:
            conditions.append("(title LIKE ? OR content LIKE ?)")
            params.extend([f"%{keyword}%", f"%{keyword}%"])
        if date_from:
            conditions.append("created_at >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("created_at <= ?")
            params.append(date_to + " 23:59:59")
        where = " AND ".join(conditions)
        offset = (page - 1) * per_page

        conn = sqlite3.connect(self.news_db_path)
        conn.row_factory = sqlite3.Row
        try:
            total = conn.execute(
                f"SELECT COUNT(*) FROM news WHERE {where}", params).fetchone()[0]
            rows = conn.execute(
                f"SELECT * FROM news WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                params + [per_page, offset]).fetchall()
            return {
                "items": [dict(r) for r in rows],
                "total": total,
                "page": page,
                "per_page": per_page,
            }
        finally:
            conn.close()

    def search_hotlist(self, platform=None, page=1, per_page=30) -> dict:
        """冷库热榜浏览。"""
        conditions = ["1=1"]
        params = []
        if platform:
            conditions.append("platform = ?")
            params.append(platform)
        where = " AND ".join(conditions)
        offset = (page - 1) * per_page

        conn = sqlite3.connect(self.hotlist_db_path)
        conn.row_factory = sqlite3.Row
        try:
            total = conn.execute(
                f"SELECT COUNT(*) FROM hot_items WHERE {where}", params).fetchone()[0]
            rows = conn.execute(
                f"SELECT * FROM hot_items WHERE {where} ORDER BY crawl_time DESC LIMIT ? OFFSET ?",
                params + [per_page, offset]).fetchall()
            return {
                "items": [dict(r) for r in rows],
                "total": total,
                "page": page,
                "per_page": per_page,
            }
        finally:
            conn.close()

    def search_rss(self, feed_id=None, keyword=None, page=1, per_page=30) -> dict:
        """冷库 RSS 浏览。"""
        conditions = ["1=1"]
        params = []
        if feed_id:
            conditions.append("feed_id = ?")
            params.append(feed_id)
        if keyword:
            conditions.append("(title LIKE ? OR summary LIKE ?)")
            params.extend([f"%{keyword}%", f"%{keyword}%"])
        where = " AND ".join(conditions)
        offset = (page - 1) * per_page

        conn = sqlite3.connect(self.rss_db_path)
        conn.row_factory = sqlite3.Row
        try:
            total = conn.execute(
                f"SELECT COUNT(*) FROM rss_items WHERE {where}", params).fetchone()[0]
            rows = conn.execute(
                f"SELECT * FROM rss_items WHERE {where} ORDER BY crawl_time DESC LIMIT ? OFFSET ?",
                params + [per_page, offset]).fetchall()
            items = []
            for r in rows:
                item = dict(r)
                items.append(item)
            return {
                "items": items,
                "total": total,
                "page": page,
                "per_page": per_page,
            }
        finally:
            conn.close()

    def semantic_search_news(self, query: str, n: int = 20) -> list[dict]:
        """冷库新闻语义搜索。"""
        if not self._vector_ready or not self.news_vector or not self.news_vector._initialized:
            return []
        return self.news_vector.semantic_search(query, n=n)

    def federated_search(self, query_text: str, top_k: int = 5) -> list[dict]:
        """跨冷库三 collection 联合搜索（chat 备用）。"""
        if not self._vector_ready:
            return []
        all_results = []

        # 新闻
        if self.news_vector and self.news_vector._initialized:
            try:
                results = self.news_vector.semantic_search(query_text, n=top_k)
                for r in results:
                    r["source_type"] = "archive_news"
                all_results.extend(results)
            except Exception as e:
                logger.warning("冷库新闻搜索失败: %s", e)

        # 热榜
        if self.hotlist_vector and self.hotlist_vector._initialized:
            try:
                query_emb = self.hotlist_vector._encode([query_text])[0] if self.hotlist_vector._encode_fn else None
                if query_emb:
                    results = self.hotlist_vector.semantic_search(query_emb, top_k=top_k)
                    for r in results:
                        r["source_type"] = "archive_hotlist"
                    all_results.extend(results)
            except Exception as e:
                logger.warning("冷库热榜搜索失败: %s", e)

        # RSS
        if self.rss_vector and self.rss_vector._initialized:
            try:
                query_emb = self.rss_vector._encode([query_text])[0] if self.rss_vector._encode_fn else None
                if query_emb:
                    results = self.rss_vector.semantic_search(query_emb, top_k=top_k)
                    for r in results:
                        r["source_type"] = "archive_rss"
                    all_results.extend(results)
            except Exception as e:
                logger.warning("冷库 RSS 搜索失败: %s", e)

        all_results.sort(key=lambda x: x.get("distance", 1.0))
        return all_results[:10]
