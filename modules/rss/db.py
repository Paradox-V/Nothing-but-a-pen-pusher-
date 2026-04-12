# coding=utf-8
"""RSS 数据库操作"""

import os
import re
import sqlite3
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional


def generate_feed_id(name: str) -> str:
    """从名称生成 URL-friendly slug ID"""
    slug = re.sub(r'[^\w\s-]', '', name.lower())
    slug = re.sub(r'[\s_]+', '-', slug).strip('-')
    return slug or "feed"


class RSSDB:
    """RSS 数据库操作封装"""

    def __init__(self, db_path: str = "data/rss.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
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

    # ── Feed CRUD ──────────────────────────────────────────────

    def get_feeds(self, enabled_only: bool = False) -> List[Dict[str, Any]]:
        """
        获取所有 RSS 源

        Args:
            enabled_only: 是否只返回启用的源

        Returns:
            Feed 字典列表
        """
        conn = self._get_conn()
        try:
            if enabled_only:
                rows = conn.execute(
                    "SELECT * FROM rss_feeds WHERE enabled = 1 ORDER BY created_at"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM rss_feeds ORDER BY created_at"
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_feed(self, feed_id: str) -> Optional[Dict[str, Any]]:
        """
        获取单个 RSS 源

        Args:
            feed_id: Feed ID

        Returns:
            Feed 字典，不存在则返回 None
        """
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM rss_feeds WHERE id = ?", (feed_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def add_feed(self, name: str, url: str, **kwargs) -> str:
        """
        添加 RSS 源，自动生成 ID

        如果生成的 ID 已存在，会追加数字后缀（如 hacker-news-2）

        Args:
            name: Feed 名称
            url: Feed URL
            **kwargs: 其他字段（format, enabled, max_items, max_age_days）

        Returns:
            生成的 Feed ID
        """
        base_id = generate_feed_id(name)
        feed_id = base_id

        conn = self._get_conn()
        try:
            # 解决 ID 冲突：追加数字后缀
            suffix = 2
            while conn.execute(
                "SELECT 1 FROM rss_feeds WHERE id = ?", (feed_id,)
            ).fetchone():
                feed_id = f"{base_id}-{suffix}"
                suffix += 1

            format_ = kwargs.get("format", "rss")
            enabled = int(kwargs.get("enabled", True))
            max_items = kwargs.get("max_items", 20)
            max_age_days = kwargs.get("max_age_days", 7)

            conn.execute(
                """INSERT INTO rss_feeds (id, name, url, format, enabled, max_items, max_age_days)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (feed_id, name, url, format_, enabled, max_items, max_age_days),
            )
            conn.commit()
            return feed_id
        finally:
            conn.close()

    def update_feed(self, feed_id: str, **kwargs) -> bool:
        """
        更新 RSS 源字段

        Args:
            feed_id: Feed ID
            **kwargs: 要更新的字段

        Returns:
            是否更新成功
        """
        if not kwargs:
            return False

        allowed = {"name", "url", "format", "enabled", "max_items", "max_age_days"}
        fields = []
        values = []
        for k, v in kwargs.items():
            if k in allowed:
                fields.append(f"{k} = ?")
                values.append(v)

        if not fields:
            return False

        values.append(feed_id)
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                f"UPDATE rss_feeds SET {', '.join(fields)} WHERE id = ?",
                values,
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def delete_feed(self, feed_id: str) -> bool:
        """
        删除 RSS 源及其所有条目

        Args:
            feed_id: Feed ID

        Returns:
            是否删除成功
        """
        conn = self._get_conn()
        try:
            # 先删除关联的条目
            conn.execute("DELETE FROM rss_items WHERE feed_id = ?", (feed_id,))
            cursor = conn.execute("DELETE FROM rss_feeds WHERE id = ?", (feed_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def update_feed_status(self, feed_id: str, error: Optional[str] = None):
        """
        更新 RSS 源的爬取状态（爬取完成后调用）

        Args:
            feed_id: Feed ID
            error: 错误信息，无错误则为 None
        """
        now = datetime.now().isoformat()
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE rss_feeds SET last_crawl_time = ?, last_error = ? WHERE id = ?",
                (now, error, feed_id),
            )
            conn.commit()
        finally:
            conn.close()

    # ── Item 操作 ─────────────────────────────────────────────

    def insert_items(self, items: List[Dict[str, Any]], crawl_time: str) -> int:
        """
        批量插入条目（URL+Feed 冲突时忽略）

        Args:
            items: 条目字典列表，每个包含 title, feed_id, url, author, summary, published_at
            crawl_time: 爬取时间（ISO 格式字符串）

        Returns:
            成功插入的条目数
        """
        if not items:
            return 0

        conn = self._get_conn()
        try:
            inserted = 0
            for item in items:
                cur = conn.execute(
                    """INSERT OR IGNORE INTO rss_items
                       (title, feed_id, url, author, summary, published_at, crawl_time)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        item["title"],
                        item["feed_id"],
                        item.get("url"),
                        item.get("author"),
                        item.get("summary"),
                        item.get("published_at"),
                        crawl_time,
                    ),
                )
                # cur.rowcount: 1=成功插入, 0=被 IGNORE（已存在）
                if cur.rowcount > 0:
                    inserted += 1
            conn.commit()
            return inserted
        finally:
            conn.close()

    def get_items(
        self,
        feed_id: Optional[str] = None,
        days: int = 7,
        page: int = 1,
        page_size: int = 30,
        keyword: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        分页获取条目

        Args:
            feed_id: 可选的 Feed ID 过滤
            days: 获取最近 N 天的条目
            page: 页码（从 1 开始）
            page_size: 每页条数
            keyword: 可选的关键词搜索（匹配 title 或 summary）

        Returns:
            {"items": [...], "total": N, "page": N, "page_size": N}
        """
        since = (datetime.now() - timedelta(days=days)).isoformat()
        offset = (page - 1) * page_size

        # 构建 WHERE 子句
        conditions = ["crawl_time >= ?"]
        params: list[Any] = [since]

        if feed_id:
            conditions.append("feed_id = ?")
            params.append(feed_id)

        if keyword:
            conditions.append("(title LIKE ? OR summary LIKE ?)")
            params.append(f"%{keyword}%")
            params.append(f"%{keyword}%")

        where = " AND ".join(conditions)

        conn = self._get_conn()
        try:
            total = conn.execute(
                f"SELECT COUNT(*) FROM rss_items WHERE {where}", params
            ).fetchone()[0]

            rows = conn.execute(
                f"""SELECT * FROM rss_items
                    WHERE {where}
                    ORDER BY published_at DESC, crawl_time DESC
                    LIMIT ? OFFSET ?""",
                params + [page_size, offset],
            ).fetchall()

            return {
                "items": [dict(r) for r in rows],
                "total": total,
                "page": page,
                "page_size": page_size,
            }
        finally:
            conn.close()

    # ── 统计 & 清理 ──────────────────────────────────────────

    def get_feed_stats(self) -> List[Dict[str, Any]]:
        """
        获取每个 Feed 的统计信息

        Returns:
            统计列表，每项包含 feed_id, name, item_count, last_crawl_time, last_error
        """
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """SELECT f.id AS feed_id, f.name, f.last_crawl_time, f.last_error,
                          COALESCE(c.item_count, 0) AS item_count
                   FROM rss_feeds f
                   LEFT JOIN (
                       SELECT feed_id, COUNT(*) AS item_count
                       FROM rss_items
                       GROUP BY feed_id
                   ) c ON f.id = c.feed_id
                   ORDER BY f.created_at"""
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def purge_old(self, days: int = 7) -> int:
        """
        删除超过指定天数的旧条目

        Args:
            days: 保留天数

        Returns:
            删除的条目数
        """
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "DELETE FROM rss_items WHERE crawl_time < ?", (cutoff,)
            )
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()

    # ── 归档辅助 ────────────────────────────────────────────

    def get_archive_candidates(self, cutoff: str, limit: int = 500) -> list[dict]:
        """获取 crawl_time 早于 cutoff 的记录（归档候选），按 id 升序。"""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM rss_items WHERE crawl_time < ? ORDER BY id LIMIT ?",
                (cutoff, limit),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def delete_by_ids(self, ids: list[int]) -> int:
        """按 id 列表批量删除记录，返回删除条数。"""
        if not ids:
            return 0
        conn = self._get_conn()
        try:
            placeholders = ",".join("?" * len(ids))
            cur = conn.execute(
                f"DELETE FROM rss_items WHERE id IN ({placeholders})", ids
            )
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()

    def get_all_feeds(self) -> list[dict]:
        """获取所有 RSS 源信息（供冷库同步用）。"""
        conn = self._get_conn()
        try:
            rows = conn.execute("SELECT * FROM rss_feeds").fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
