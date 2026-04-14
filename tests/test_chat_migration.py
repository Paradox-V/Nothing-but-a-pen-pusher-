"""Chat DB 迁移测试 —— 验证 mode 列增量迁移"""

import os
import sqlite3
import tempfile
import pytest

from modules.chat.db import ChatDB


@pytest.fixture
def chat_db():
    """使用临时文件的 ChatDB"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    db = ChatDB(db_path=db_path)
    yield db
    os.unlink(db_path)


class TestChatMigration:
    def test_mode_column_exists(self, chat_db):
        """mode 列应该存在于新创建的数据库中"""
        conn = chat_db._get_conn()
        row = conn.execute("PRAGMA table_info(chat_sessions)").fetchone()
        columns = [dict(r)["name"] for r in conn.execute("PRAGMA table_info(chat_sessions)").fetchall()]
        conn.close()
        assert "mode" in columns

    def test_create_session_with_mode(self, chat_db):
        """create_session 应接受 mode 参数"""
        session = chat_db.create_session("test-id-1", "测试会话", mode="agent")
        assert session["mode"] == "agent"

        session2 = chat_db.create_session("test-id-2", "简单会话")
        assert session2["mode"] == "simple"

    def test_default_mode_is_simple(self, chat_db):
        """不传 mode 时默认为 simple"""
        session = chat_db.create_session("test-id-3", "默认会话")
        assert session["mode"] == "simple"

    def test_get_sessions_includes_mode(self, chat_db):
        """get_sessions 返回应包含 mode 字段"""
        chat_db.create_session("test-id-4", "Agent会话", mode="agent")
        chat_db.create_session("test-id-5", "简单会话", mode="simple")

        all_sessions = chat_db.get_sessions()
        assert all(s.get("mode") is not None for s in all_sessions)

    def test_get_sessions_filter_by_mode(self, chat_db):
        """按 mode 过滤会话"""
        chat_db.create_session("test-id-6", "Agent会话", mode="agent")
        chat_db.create_session("test-id-7", "简单会话", mode="simple")

        agent_sessions = chat_db.get_sessions(mode="agent")
        assert len(agent_sessions) == 1
        assert agent_sessions[0]["mode"] == "agent"

    def test_migration_from_old_schema(self):
        """模拟旧库升级：先创建无 mode 列的表，再初始化 ChatDB"""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        # 模拟旧库：手动创建无 mode 列的表
        conn = sqlite3.connect(db_path)
        conn.executescript("""
            CREATE TABLE chat_sessions (
                id TEXT PRIMARY KEY,
                title TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
            );
        """)
        conn.execute("INSERT INTO chat_sessions (id, title) VALUES ('old-1', '旧会话')")
        conn.commit()
        conn.close()

        # 初始化 ChatDB 触发迁移
        db = ChatDB(db_path=db_path)

        # 验证 mode 列已添加
        session = db.get_session("old-1")
        assert session is not None
        assert session.get("mode") == "simple"  # 默认值

        # 验证新创建的会话可用
        db.create_session("new-1", "新会话", mode="agent")
        session = db.get_session("new-1")
        assert session["mode"] == "agent"

        os.unlink(db_path)
