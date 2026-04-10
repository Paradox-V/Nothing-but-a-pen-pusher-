"""抓取触发信号

Web 层写入触发信号，scheduler 轮询检测后执行实际抓取。
避免 Web 进程和 scheduler 同时抓取导致并发冲突。
"""
import json
import os
import sqlite3
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class CrawlTrigger:
    """基于 SQLite 的抓取触发信号"""

    def __init__(self, db_path: str = "data/crawl_triggers.db"):
        self.db_path = db_path
        db_dir = os.path.dirname(db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS crawl_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                module TEXT NOT NULL,
                triggered_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                triggered_by TEXT NOT NULL DEFAULT 'web',
                status TEXT NOT NULL DEFAULT 'pending',
                completed_at TEXT
            );
        """)
        conn.close()

    def trigger(self, module: str) -> bool:
        """Web 层触发抓取信号"""
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO crawl_signals (module, triggered_by, status) VALUES (?, 'web', 'pending')",
                (module,),
            )
            conn.commit()
            logger.info("触发抓取信号: %s", module)
            return True
        finally:
            conn.close()

    def poll_pending(self) -> list[str]:
        """Scheduler 轮询待处理的信号，返回模块名列表"""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT DISTINCT module FROM crawl_signals WHERE status = 'pending'"
            ).fetchall()
            return [r["module"] for r in rows]
        finally:
            conn.close()

    def mark_done(self, module: str):
        """Scheduler 标记信号已处理"""
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE crawl_signals SET status = 'done', completed_at = datetime('now','localtime') "
                "WHERE module = ? AND status = 'pending'",
                (module,),
            )
            conn.commit()
        finally:
            conn.close()
