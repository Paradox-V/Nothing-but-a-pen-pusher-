"""热榜数据库操作"""
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
                UNIQUE(url, platform, crawl_time)
            );
            CREATE TABLE IF NOT EXISTS crawl_batches (
                id INTEGER PRIMARY KEY,
                crawl_time DATETIME NOT NULL,
                platform_count INTEGER,
                item_count INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_hot_platform ON hot_items(platform);
            CREATE INDEX IF NOT EXISTS idx_hot_crawl_time ON hot_items(crawl_time);
        """)
        conn.close()

    # ------------------------------------------------------------------
    #  Core write operations
    # ------------------------------------------------------------------

    def insert_batch(self, items, crawl_time):
        """Insert a batch of hot list items.

        For each item, if a row with the same (url, platform) already exists
        in the table, the NEW row inherits the accumulated ``appear_count``
        (old count + 1) and the earliest ``first_time``.  The old row's
        ``last_time`` / ``appear_count`` are **not** modified -- the new row
        carries the full history forward.

        Args:
            items: iterable of dicts with keys
                title, url, platform, platform_name, hot_rank, hot_score
            crawl_time: datetime string or datetime for this crawl run
        """
        if isinstance(crawl_time, datetime):
            crawl_time = crawl_time.strftime("%Y-%m-%d %H:%M:%S")

        conn = self._get_conn()
        cur = conn.cursor()

        platform_set = set()
        item_count = 0

        try:
            for item in items:
                title = item.get("title", "")
                url = item.get("url", "")
                platform = item.get("platform", "")
                platform_name = item.get("platform_name", "")
                hot_rank = item.get("hot_rank")
                hot_score = item.get("hot_score", "")

                platform_set.add(platform)

                # Look for an existing record with the same url+platform to
                # inherit appear_count / first_time.
                existing = cur.execute(
                    """
                    SELECT appear_count, first_time
                    FROM hot_items
                    WHERE url = ? AND platform = ?
                    ORDER BY crawl_time DESC
                    LIMIT 1
                    """,
                    (url, platform),
                ).fetchone()

                if existing:
                    new_count = existing["appear_count"] + 1
                    first_time = existing["first_time"]
                else:
                    new_count = 1
                    first_time = crawl_time

                try:
                    cur.execute(
                        """
                        INSERT INTO hot_items
                            (title, url, platform, platform_name,
                             hot_rank, hot_score, crawl_time,
                             first_time, last_time, appear_count)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            title,
                            url,
                            platform,
                            platform_name,
                            hot_rank,
                            str(hot_score) if hot_score is not None else "",
                            crawl_time,
                            first_time,
                            crawl_time,
                            new_count,
                        ),
                    )
                    item_count += 1
                except sqlite3.IntegrityError:
                    # UNIQUE(url, platform, crawl_time) duplicate -- skip
                    pass

            # Record the crawl batch
            cur.execute(
                """
                INSERT INTO crawl_batches (crawl_time, platform_count, item_count)
                VALUES (?, ?, ?)
                """,
                (crawl_time, len(platform_set), item_count),
            )

            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------------
    #  Read operations
    # ------------------------------------------------------------------

    def get_items(self, platform=None, hours=24, page=1, page_size=30):
        """Get paginated hot list items.

        For each unique (title, platform) pair only the row with the latest
        ``crawl_time`` is returned.

        Args:
            platform: filter by platform id (optional)
            hours: look-back window in hours (default 24)
            page: 1-based page number
            page_size: rows per page

        Returns:
            dict with keys ``items`` (list of row-dicts), ``total``,
            ``page``, ``page_size``.
        """
        cutoff = (datetime.now() - timedelta(hours=hours)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        offset = (page - 1) * page_size

        conn = self._get_conn()

        # Build the filtered latest-row subquery
        where_parts = ["hi.crawl_time >= ?"]
        params = [cutoff]
        if platform:
            where_parts.append("hi.platform = ?")
            params.append(platform)

        where_clause = " AND ".join(where_parts)

        # Count total unique (title, platform) pairs in the window
        count_row = conn.execute(
            f"""
            SELECT COUNT(*) AS cnt
            FROM hot_items hi
            WHERE hi.id IN (
                SELECT h2.id
                FROM hot_items h2
                WHERE h2.title = hi.title
                  AND h2.platform = hi.platform
                  AND h2.crawl_time >= ?
                ORDER BY h2.crawl_time DESC
                LIMIT 1
            )
            AND {where_clause}
            """,
            [cutoff] + params,
        ).fetchone()
        total = count_row["cnt"] if count_row else 0

        # Fetch the page of results
        rows = conn.execute(
            f"""
            SELECT hi.*
            FROM hot_items hi
            WHERE hi.id IN (
                SELECT h2.id
                FROM hot_items h2
                WHERE h2.title = hi.title
                  AND h2.platform = hi.platform
                  AND h2.crawl_time >= ?
                ORDER BY h2.crawl_time DESC
                LIMIT 1
            )
            AND {where_clause}
            ORDER BY hi.platform, hi.hot_rank ASC
            LIMIT ? OFFSET ?
            """,
            [cutoff] + params + [page_size, offset],
        ).fetchall()

        conn.close()

        items = [dict(r) for r in rows]
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def get_platform_stats(self):
        """Get per-platform statistics.

        Returns:
            list of dicts with keys platform, platform_name, item_count,
            latest_crawl_time.
        """
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
        """Return the most recent crawl batch time, or None."""
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
        """Delete items older than *days* days.

        Returns:
            Number of rows deleted.
        """
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
