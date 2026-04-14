"""对话历史数据库操作"""

import os
import sqlite3
from datetime import datetime


class ChatDB:
    """对话会话与消息的 SQLite 持久化"""

    def __init__(self, db_path: str = "data/chat.db"):
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
            CREATE TABLE IF NOT EXISTS chat_sessions (
                id TEXT PRIMARY KEY,
                title TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
            );
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('user','assistant','system')),
                content TEXT NOT NULL,
                sources TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
            );
            CREATE INDEX IF NOT EXISTS idx_chat_messages_session
                ON chat_messages(session_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_chat_sessions_updated
                ON chat_sessions(updated_at DESC);
        """)
        # 增量迁移（参照 NewsDB 的 MIGRATIONS 模式）
        migrations = [
            "ALTER TABLE chat_sessions ADD COLUMN mode TEXT NOT NULL DEFAULT 'simple'",
        ]
        for sql in migrations:
            try:
                conn.execute(sql)
            except sqlite3.OperationalError:
                pass
        conn.commit()
        conn.close()

    # ── 会话操作 ──────────────────────────────────────────────

    def create_session(self, session_id: str, title: str = "", mode: str = "simple") -> dict:
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO chat_sessions (id, title, mode) VALUES (?, ?, ?)",
            (session_id, title, mode),
        )
        conn.commit()
        conn.close()
        return {"id": session_id, "title": title, "mode": mode}

    def get_sessions(self, mode: str = None, limit: int = 50) -> list[dict]:
        conn = self._get_conn()
        if mode:
            rows = conn.execute(
                "SELECT s.id, s.title, s.mode, s.created_at, s.updated_at, "
                "  (SELECT COUNT(*) FROM chat_messages WHERE session_id = s.id) AS msg_count "
                "FROM chat_sessions s WHERE s.mode = ? ORDER BY s.updated_at DESC LIMIT ?",
                (mode, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT s.id, s.title, s.mode, s.created_at, s.updated_at, "
                "  (SELECT COUNT(*) FROM chat_messages WHERE session_id = s.id) AS msg_count "
                "FROM chat_sessions s ORDER BY s.updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_session(self, session_id: str) -> dict | None:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM chat_sessions WHERE id = ?", (session_id,)
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def delete_session(self, session_id: str) -> bool:
        conn = self._get_conn()
        # 先删消息，再删会话（无外键约束，应用层保证）
        conn.execute("DELETE FROM chat_messages WHERE session_id = ?", (session_id,))
        cursor = conn.execute("DELETE FROM chat_sessions WHERE id = ?", (session_id,))
        conn.commit()
        conn.close()
        return cursor.rowcount > 0

    def update_session_title_if_empty(self, session_id: str, title: str):
        """首条消息时自动设置会话标题。"""
        conn = self._get_conn()
        conn.execute(
            "UPDATE chat_sessions SET title = ?, updated_at = datetime('now','localtime') "
            "WHERE id = ? AND (title IS NULL OR title = '')",
            (title, session_id),
        )
        conn.commit()
        conn.close()

    def touch_session(self, session_id: str):
        """更新会话的 updated_at 时间戳。"""
        conn = self._get_conn()
        conn.execute(
            "UPDATE chat_sessions SET updated_at = datetime('now','localtime') WHERE id = ?",
            (session_id,),
        )
        conn.commit()
        conn.close()

    # ── 消息操作 ──────────────────────────────────────────────

    def save_message(self, session_id: str, role: str, content: str,
                     sources: str = ""):
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO chat_messages (session_id, role, content, sources) "
            "VALUES (?, ?, ?, ?)",
            (session_id, role, content, sources),
        )
        conn.commit()
        conn.close()
        self.touch_session(session_id)

    def get_messages(self, session_id: str, limit: int = 100) -> list[dict]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT id, role, content, sources, created_at "
            "FROM chat_messages WHERE session_id = ? "
            "ORDER BY created_at ASC LIMIT ?",
            (session_id, limit),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_recent_messages(self, session_id: str, limit: int = 20) -> list[dict]:
        """获取最近的 N 条消息（用于构建对话历史上下文）。

        先按时间倒序取最新 N 条，再反转为正序（符合对话时序）。
        """
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT id, role, content, sources, created_at "
            "FROM chat_messages WHERE session_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
        conn.close()
        # 反转为时间正序（最早→最新），符合对话上下文顺序
        return list(reversed([dict(r) for r in rows]))
