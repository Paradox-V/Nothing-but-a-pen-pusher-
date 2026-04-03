"""热榜数据库操作

存储策略：每个 (title, platform) 只保留一行，每次抓取时 UPSERT 更新。
避免重复插入导致行数暴涨（旧方案每天上万行）。
"""
import os
import sqlite3
from datetime import datetime, timedelta


class HotlistDB:
    def __init__(self, db_path="data/hotlist.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS crawl_batches (
                id INTEGER PRIMARY KEY,
                crawl_time DATETIME NOT NULL,
                platform_count INTEGER,
                item_count INTEGER
            );
        """)

        # 检测是否需要从旧 schema 迁移（UNIQUE(url, platform, crawl_time) → UNIQUE(title, platform)）
        table_def = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='hot_items'"
        ).fetchone()
        if table_def and "url, platform, crawl_time" in table_def["sql"]:
            self._migrate_from_v1(conn)

        conn.executescript("""
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
                appear_count INTEGER DEFAULT 1,
                UNIQUE(title, platform)
            );
            CREATE INDEX IF NOT EXISTS idx_hot_platform ON hot_items(platform);
            CREATE INDEX IF NOT EXISTS idx_hot_crawl_time ON hot_items(crawl_time);
        """)
        conn.close()

    def _migrate_from_v1(self, conn):
        """合并旧表中同一 (title, platform) 的多行为一行"""
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS hot_items_new (
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
                UNIQUE(title, platform)
            );

            INSERT OR IGNORE INTO hot_items_new
                (title, url, platform, platform_name,
                 hot_rank, hot_score,
                 crawl_time, first_time, last_time, appear_count)
            SELECT
                title, url, platform, platform_name,
                -- 取最新一次的 rank/score（按 crawl_time 最新的那条）
                (SELECT hot_rank FROM hot_items h2
                 WHERE h2.title = h.title AND h2.platform = h.platform
                 ORDER BY h2.crawl_time DESC LIMIT 1),
                (SELECT hot_score FROM hot_items h2
                 WHERE h2.title = h.title AND h2.platform = h.platform
                 ORDER BY h2.crawl_time DESC LIMIT 1),
                MAX(crawl_time),
                MIN(COALESCE(first_time, crawl_time)),
                MAX(crawl_time),
                SUM(appear_count)
            FROM hot_items h
            GROUP BY title, platform;

            DROP TABLE hot_items;
            ALTER TABLE hot_items_new RENAME TO hot_items;
        """)

    # ------------------------------------------------------------------
    #  Core write operations
    # ------------------------------------------------------------------

    def insert_batch(self, items, crawl_time):
        """UPSERT 一批热榜条目。

        同一 (title, platform) 只保留一行：
        - 首次出现：INSERT
        - 再次出现：UPDATE hot_rank / hot_score / crawl_time / appear_count

        Args:
            items: dict 列表，每个含 title, url, platform, platform_name, hot_rank, hot_score
            crawl_time: 抓取时间（字符串或 datetime）

        Returns:
            实际新增的条目数
        """
        if isinstance(crawl_time, datetime):
            crawl_time = crawl_time.strftime("%Y-%m-%d %H:%M:%S")

        conn = self._get_conn()
        cur = conn.cursor()

        platform_set = set()
        new_count = 0

        try:
            for item in items:
                title = item.get("title", "")
                url = item.get("url", "")
                platform = item.get("platform", "")
                platform_name = item.get("platform_name", "")
                hot_rank = item.get("hot_rank")
                hot_score = item.get("hot_score", "")

                if not title or not platform:
                    continue

                platform_set.add(platform)

                row_before = cur.execute("SELECT changes()").fetchone()[0]
                cur.execute(
                    """
                    INSERT INTO hot_items
                        (title, url, platform, platform_name,
                         hot_rank, hot_score,
                         crawl_time, first_time, last_time, appear_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                    ON CONFLICT(title, platform) DO UPDATE SET
                        url = CASE WHEN LENGTH(excluded.url) > LENGTH(hot_items.url)
                                   OR hot_items.url IS NULL
                                   THEN excluded.url ELSE hot_items.url END,
                        hot_rank = excluded.hot_rank,
                        hot_score = excluded.hot_score,
                        crawl_time = excluded.crawl_time,
                        last_time = excluded.crawl_time,
                        appear_count = hot_items.appear_count + 1
                    """,
                    (
                        title, url, platform, platform_name,
                        hot_rank,
                        str(hot_score) if hot_score is not None else "",
                        crawl_time, crawl_time, crawl_time,
                    ),
                )
                if conn.total_changes and conn.total_changes > (row_before or 0):
                    new_count += 1

            # Record the crawl batch
            cur.execute(
                """
                INSERT INTO crawl_batches (crawl_time, platform_count, item_count)
                VALUES (?, ?, ?)
                """,
                (crawl_time, len(platform_set), len(items)),
            )

            conn.commit()
            return new_count
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------------
    #  Read operations
    # ------------------------------------------------------------------

    def get_items(self, platform=None, hours=24, page=1, page_size=30):
        """分页获取热榜条目。

        新 schema 下每个 (title, platform) 只有一行，无需去重。

        Args:
            platform: 按平台 ID 过滤（可选）
            hours: 回溯小时数，默认 24
            page: 页码，从 1 开始
            page_size: 每页条数

        Returns:
            {"items": [...], "total": N, "page": N, "page_size": N}
        """
        cutoff = (datetime.now() - timedelta(hours=hours)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        offset = (page - 1) * page_size

        conn = self._get_conn()

        where_parts = ["crawl_time >= ?"]
        params = [cutoff]
        if platform:
            where_parts.append("platform = ?")
            params.append(platform)
        where_clause = " AND ".join(where_parts)

        total = conn.execute(
            f"SELECT COUNT(*) FROM hot_items WHERE {where_clause}", params
        ).fetchone()[0]

        rows = conn.execute(
            f"""
            SELECT * FROM hot_items
            WHERE {where_clause}
            ORDER BY platform, hot_rank ASC
            LIMIT ? OFFSET ?
            """,
            params + [page_size, offset],
        ).fetchall()

        conn.close()
        return {
            "items": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def get_platform_stats(self):
        """每个平台的统计信息"""
        conn = self._get_conn()
        rows = conn.execute(
            """
            SELECT
                platform,
                platform_name,
                COUNT(*) AS item_count,
                MAX(crawl_time) AS latest_crawl_time
            FROM hot_items
            GROUP BY platform
            ORDER BY latest_crawl_time DESC
            """
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_last_crawl_time(self):
        """最近一次抓取时间"""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT crawl_time FROM crawl_batches ORDER BY crawl_time DESC LIMIT 1"
        ).fetchone()
        conn.close()
        return row["crawl_time"] if row else None

    # ------------------------------------------------------------------
    #  Maintenance
    # ------------------------------------------------------------------

    def purge_old(self, days=7):
        """删除 last_time 超过 days 天的条目"""
        cutoff = (datetime.now() - timedelta(days=days)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        conn = self._get_conn()
        cur = conn.execute(
            "DELETE FROM hot_items WHERE crawl_time < ?", (cutoff,)
        )
        deleted = cur.rowcount
        conn.commit()
        conn.close()
        return deleted
