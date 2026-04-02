"""
新闻模块 - 数据库层

从 ak_source_aggregator.py 提取的 NewsDB 类，
采用每次请求新连接的模式以实现线程安全。
"""

import hashlib
import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


class NewsDB:
    """新闻持久化存储，基于 SQLite。"""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS news (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        source_name  TEXT    NOT NULL,
        title        TEXT    NOT NULL,
        content      TEXT    NOT NULL,
        timestamp    TEXT,
        url          TEXT,
        tags         TEXT    NOT NULL DEFAULT '[]',
        content_hash TEXT    UNIQUE NOT NULL,
        category     TEXT    NOT NULL DEFAULT '其他',
        cluster_id   TEXT,
        created_at   TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
    );
    CREATE INDEX IF NOT EXISTS idx_news_created  ON news(created_at);
    CREATE INDEX IF NOT EXISTS idx_news_source   ON news(source_name);
    CREATE INDEX IF NOT EXISTS idx_news_hash     ON news(content_hash);
    """

    MIGRATIONS = [
        "ALTER TABLE news ADD COLUMN category TEXT NOT NULL DEFAULT '其他'",
        "ALTER TABLE news ADD COLUMN cluster_id TEXT",
        "CREATE INDEX IF NOT EXISTS idx_news_category ON news(category)",
        "CREATE INDEX IF NOT EXISTS idx_news_cluster  ON news(cluster_id)",
    ]

    def __init__(self, db_path: str = "data/news.db"):
        self.db_path = str(db_path)
        # 自动创建 data/ 目录
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        # 初始化表结构
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """每次创建新连接，确保线程安全。"""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """初始化数据库表结构和增量迁移。"""
        conn = self._get_conn()
        try:
            conn.executescript(self.SCHEMA)
            # 增量迁移：为旧表添加新列
            for mig in self.MIGRATIONS:
                try:
                    conn.execute(mig)
                    conn.commit()
                except sqlite3.OperationalError:
                    pass  # 列已存在
        finally:
            conn.close()

    # ── 去重哈希（独立实现，不依赖 AKSourceAggregator） ────────

    @staticmethod
    def _normalize_title(title: str) -> str:
        """归一化标题用于去重：去除【】包裹符，统一空白。"""
        t = title.strip()
        if t.startswith("\u3010"):
            end = t.find("\u3011")
            if end != -1:
                t = t[end + 1:].strip()
        return " ".join(t.split())

    @staticmethod
    def _dedup_hash(title: str, content: str) -> str:
        """去重哈希：优先基于归一化标题，标题过短时回退到内容哈希。"""
        norm = NewsDB._normalize_title(title)
        if len(norm) >= 4:
            return hashlib.md5(norm.encode("utf-8")).hexdigest()
        text = content[:200] if content else ""
        return hashlib.md5(text.encode("utf-8")).hexdigest()

    # ── 写入 ───────────────────────────────────────────────

    def insert_many(
        self,
        items: list[dict],
        categories: list[list[str]] | None = None,
        cluster_ids: list[str] | None = None,
    ) -> tuple[int, list[int]]:
        """
        批量插入新闻，基于归一化标题去重（content_hash UNIQUE）。
        若标题相同但新条目内容更长，则更新已有记录。
        categories 为 list[list[str]]，写入时 JSON 序列化。
        返回 (实际新增条数, 新增条目的 row id 列表)。
        """
        conn = self._get_conn()
        try:
            added = 0
            new_row_ids: list[int] = []
            for idx, item in enumerate(items):
                h = self._dedup_hash(item["title"], item["content"])
                cat_list = categories[idx] if categories else ["其他"]
                cat_json = json.dumps(cat_list, ensure_ascii=False)
                cid = cluster_ids[idx] if cluster_ids else None
                try:
                    cur = conn.execute(
                        "INSERT INTO news (source_name, title, content, timestamp, url, tags, content_hash, category, cluster_id) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            item["source_name"],
                            item["title"],
                            item["content"],
                            item.get("timestamp"),
                            item.get("url"),
                            json.dumps(item.get("tags", []), ensure_ascii=False),
                            h,
                            cat_json,
                            cid,
                        ),
                    )
                    new_row_ids.append(cur.lastrowid)
                    added += 1
                except sqlite3.IntegrityError:
                    # 标题重复 —— 如果新内容更长则更新
                    existing = conn.execute(
                        "SELECT id, length(content) as clen FROM news WHERE content_hash = ?",
                        (h,),
                    ).fetchone()
                    if existing and len(item.get("content", "")) > existing["clen"]:
                        conn.execute(
                            "UPDATE news SET content=?, source_name=?, url=?, tags=?, category=?, cluster_id=? WHERE id=?",
                            (
                                item["content"],
                                item["source_name"],
                                item.get("url"),
                                json.dumps(item.get("tags", []), ensure_ascii=False),
                                cat_json,
                                cid,
                                existing["id"],
                            ),
                        )
            conn.commit()
            return added, new_row_ids
        finally:
            conn.close()

    # ── 过期清理 ────────────────────────────────────────────

    def purge_old(self, days: int = 30) -> int:
        """删除 created_at 超过 days 天的记录，返回删除条数。"""
        conn = self._get_conn()
        try:
            cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
            cur = conn.execute("DELETE FROM news WHERE created_at < ?", (cutoff,))
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()

    # ── 查询辅助 ────────────────────────────────────────────

    def _build_query(self, sources=None, categories=None, keyword=None, date_from=None, date_to=None, count_only=False):
        """统一构建 SQL，支持多 source + 多 category + keyword + 时间范围。"""
        select = "COUNT(*)" if count_only else "*"
        sql = f"SELECT {select} FROM news WHERE 1=1"
        params: list[Any] = []
        if sources:
            placeholders = ",".join("?" * len(sources))
            sql += f" AND source_name IN ({placeholders})"
            params.extend(sources)
        if categories:
            cat_conds = []
            for cat in categories:
                cat_conds.append("(category LIKE ?)")
                params.append(f'%"{cat}"%')
            sql += " AND (" + " AND ".join(cat_conds) + ")"
        if keyword:
            sql += " AND (title LIKE ? OR content LIKE ?)"
            params.extend([f"%{keyword}%", f"%{keyword}%"])
        if date_from:
            sql += " AND created_at >= ?"
            params.append(date_from)
        if date_to:
            sql += " AND created_at <= ?"
            params.append(date_to + " 23:59:59")
        return sql, params

    # ── 查询 ────────────────────────────────────────────────

    def get_all(
        self,
        sources: list[str] | None = None,
        categories: list[str] | None = None,
        keyword: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[dict]:
        """查询新闻列表，支持按多来源、多分类、关键词和时间范围过滤。"""
        conn = self._get_conn()
        try:
            sql, params = self._build_query(
                sources=sources, categories=categories, keyword=keyword,
                date_from=date_from, date_to=date_to,
            )
            sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_dict(r) for r in rows]
        finally:
            conn.close()

    def get_count(
        self,
        sources: list[str] | None = None,
        categories: list[str] | None = None,
        keyword: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> int:
        """统计符合条件的新闻条数。"""
        conn = self._get_conn()
        try:
            sql, params = self._build_query(
                sources=sources, categories=categories, keyword=keyword,
                date_from=date_from, date_to=date_to, count_only=True,
            )
            return conn.execute(sql, params).fetchone()[0]
        finally:
            conn.close()

    def get_source_stats(self) -> dict[str, int]:
        """返回每个信源的条数。"""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT source_name, COUNT(*) as cnt FROM news GROUP BY source_name"
            ).fetchall()
            return {r["source_name"]: r["cnt"] for r in rows}
        finally:
            conn.close()

    def get_total_count(self) -> int:
        """返回新闻总条数。"""
        conn = self._get_conn()
        try:
            return conn.execute("SELECT COUNT(*) FROM news").fetchone()[0]
        finally:
            conn.close()

    def get_sources_list(self) -> list[str]:
        """返回所有信源名称列表。"""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT DISTINCT source_name FROM news ORDER BY source_name"
            ).fetchall()
            return [r["source_name"] for r in rows]
        finally:
            conn.close()

    def get_category_stats(self) -> list[dict]:
        """返回每个分类的条数统计（拆解 JSON 数组计数）。"""
        conn = self._get_conn()
        try:
            rows = conn.execute("SELECT category FROM news").fetchall()
            counter: dict[str, int] = {}
            for r in rows:
                try:
                    cats = json.loads(r["category"])
                except (json.JSONDecodeError, TypeError):
                    cats = [r["category"]]
                for c in cats:
                    counter[c] = counter.get(c, 0) + 1
            return [{"category": k, "count": v} for k, v in sorted(counter.items(), key=lambda x: -x[1])]
        finally:
            conn.close()

    def get_cluster_list(self) -> list[dict]:
        """返回所有专题（cluster_id 非空的分组），含代表性标题和条数。"""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT cluster_id, COUNT(*) as cnt, "
                "MIN(title) as sample_title, "
                "GROUP_CONCAT(DISTINCT source_name) as sources "
                "FROM news WHERE cluster_id IS NOT NULL AND cluster_id != '' "
                "GROUP BY cluster_id HAVING cnt >= 2 "
                "ORDER BY cnt DESC"
            ).fetchall()
            return [
                {
                    "cluster_id": r["cluster_id"],
                    "count": r["cnt"],
                    "sample_title": r["sample_title"],
                    "sources": r["sources"],
                }
                for r in rows
            ]
        finally:
            conn.close()

    def get_cluster_news(self, cluster_id: str, limit: int = 50) -> list[dict]:
        """返回某专题下的所有新闻。"""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM news WHERE cluster_id = ? "
                "ORDER BY COALESCE(timestamp, created_at) DESC LIMIT ?",
                (cluster_id, limit),
            ).fetchall()
            return [self._row_to_dict(r) for r in rows]
        finally:
            conn.close()

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        raw_cat = row["category"] if "category" in row.keys() else "其他"
        try:
            category = json.loads(raw_cat)
            if not isinstance(category, list):
                category = [category]
        except (json.JSONDecodeError, TypeError):
            category = [raw_cat]
        return {
            "id": row["id"],
            "source_name": row["source_name"],
            "title": row["title"],
            "content": row["content"],
            "timestamp": row["timestamp"],
            "url": row["url"],
            "tags": json.loads(row["tags"]),
            "category": category,
            "cluster_id": row["cluster_id"] if "cluster_id" in row.keys() else None,
            "created_at": row["created_at"],
        }

    def migrate_category_to_json(self) -> int:
        """将旧的单值 category 迁移为 JSON 数组格式。返回迁移条数。"""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT id, category FROM news WHERE category NOT LIKE '[%'"
            ).fetchall()
            if not rows:
                return 0
            for r in rows:
                cat = r["category"] or "其他"
                conn.execute(
                    "UPDATE news SET category = ? WHERE id = ?",
                    (json.dumps([cat], ensure_ascii=False), r["id"]),
                )
            conn.commit()
            logger.info("分类迁移: %d 条旧数据已转为 JSON 数组格式", len(rows))
            return len(rows)
        finally:
            conn.close()

    def reclassify_all(self, vector_engine=None) -> int:
        """用 Embedding 相似度批量重新分类所有数据。需要传入已初始化的 vector_engine。返回重新分类条数。"""
        from news_vector import NewsVectorEngine
        conn = self._get_conn()
        try:
            rows = conn.execute("SELECT id, title, content FROM news").fetchall()
            if not rows:
                return 0

            ids = [r["id"] for r in rows]
            texts = [f"{r['title']} {r['content']}" for r in rows]

            if vector_engine and vector_engine._initialized:
                all_cats = vector_engine.classify_texts(texts)
            else:
                all_cats = [["其他"] for _ in texts]

            # 批量更新
            conn.executemany(
                "UPDATE news SET category = ? WHERE id = ?",
                [(json.dumps(cats, ensure_ascii=False), rid) for rid, cats in zip(ids, all_cats)],
            )
            conn.commit()
            logger.info("批量重新分类: %d 条数据已更新", len(ids))
            return len(ids)
        finally:
            conn.close()
