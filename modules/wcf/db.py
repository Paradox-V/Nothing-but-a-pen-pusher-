"""WCF 模块 SQLite 持久化 — data/wcf.db

3 张表：
  _meta(key, value)                — 游标等元数据
  wcf_bindings(...)                — 联系人绑定（UNIQUE account_id, user_id）
  wcf_binding_tasks(binding_id, task_id) — 联系人-监控任务关联
"""

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

_DB_PATH = str(Path("data") / "wcf.db")

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS _meta(
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS wcf_bindings(
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    context_token TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 0,
    last_seen_at TEXT,
    last_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(account_id, user_id)
);

CREATE TABLE IF NOT EXISTS wcf_binding_tasks(
    binding_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    PRIMARY KEY(binding_id, task_id)
);
"""


class WCFDB:
    def __init__(self, db_path: str = _DB_PATH):
        self._db_path = db_path
        self._ensure_tables()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _ensure_tables(self):
        conn = self._get_conn()
        try:
            conn.executescript(_CREATE_TABLES)
        finally:
            conn.close()

    # ── _meta ──

    def get_meta(self, key: str) -> str | None:
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT value FROM _meta WHERE key = ?", (key,)).fetchone()
            return row["value"] if row else None
        finally:
            conn.close()

    def set_meta(self, key: str, value: str):
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO _meta(key, value) VALUES(?, ?)", (key, value)
            )
            conn.commit()
        finally:
            conn.close()

    def get_cursor(self) -> int:
        val = self.get_meta("last_event_id")
        return int(val) if val else 0

    def set_cursor(self, event_id: int):
        self.set_meta("last_event_id", str(event_id))

    # ── wcf_bindings ──

    def upsert_binding(self, account_id: str, user_id: str,
                       display_name: str = "", context_token: str = "",
                       last_message: str = "") -> str:
        """插入或更新联系人。ON CONFLICT 只更新动态字段，保留 id 和 enabled。

        Returns the binding id.
        """
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn = self._get_conn()
        try:
            # 先查是否已存在
            existing = conn.execute(
                "SELECT id FROM wcf_bindings WHERE account_id = ? AND user_id = ?",
                (account_id, user_id),
            ).fetchone()

            if existing:
                binding_id = existing["id"]
                conn.execute(
                    """UPDATE wcf_bindings SET
                        display_name = COALESCE(NULLIF(?, ''), display_name),
                        context_token = COALESCE(NULLIF(?, ''), context_token),
                        last_message = ?,
                        last_seen_at = ?,
                        updated_at = ?
                    WHERE id = ?""",
                    (display_name, context_token, last_message, now, now, binding_id),
                )
            else:
                binding_id = str(uuid.uuid4())
                conn.execute(
                    """INSERT INTO wcf_bindings
                        (id, account_id, user_id, display_name, context_token,
                         enabled, last_message, last_seen_at, created_at, updated_at)
                    VALUES(?, ?, ?, ?, ?, 0, ?, ?, ?, ?)""",
                    (binding_id, account_id, user_id, display_name, context_token,
                     last_message, now, now, now),
                )

            conn.commit()
            return binding_id
        finally:
            conn.close()

    def list_bindings(self, enabled_only: bool = False) -> list[dict]:
        conn = self._get_conn()
        try:
            if enabled_only:
                rows = conn.execute(
                    "SELECT * FROM wcf_bindings WHERE enabled = 1 ORDER BY updated_at DESC"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM wcf_bindings ORDER BY updated_at DESC"
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_binding(self, binding_id: str) -> dict | None:
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM wcf_bindings WHERE id = ?", (binding_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_binding_by_user(self, account_id: str, user_id: str) -> dict | None:
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM wcf_bindings WHERE account_id = ? AND user_id = ?",
                (account_id, user_id),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def set_binding_enabled(self, binding_id: str, enabled: bool):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE wcf_bindings SET enabled = ?, updated_at = ? WHERE id = ?",
                (1 if enabled else 0, now, binding_id),
            )
            conn.commit()
        finally:
            conn.close()

    def update_binding_display_name(self, binding_id: str, display_name: str):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE wcf_bindings SET display_name = ?, updated_at = ? WHERE id = ?",
                (display_name, now, binding_id),
            )
            conn.commit()
        finally:
            conn.close()

    # ── wcf_binding_tasks ──

    def bind_task(self, binding_id: str, task_id: str):
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO wcf_binding_tasks(binding_id, task_id) VALUES(?, ?)",
                (binding_id, task_id),
            )
            conn.commit()
        finally:
            conn.close()

    def unbind_task(self, binding_id: str, task_id: str):
        conn = self._get_conn()
        try:
            conn.execute(
                "DELETE FROM wcf_binding_tasks WHERE binding_id = ? AND task_id = ?",
                (binding_id, task_id),
            )
            conn.commit()
        finally:
            conn.close()

    def get_binding_tasks(self, binding_id: str) -> list[str]:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT task_id FROM wcf_binding_tasks WHERE binding_id = ?",
                (binding_id,),
            ).fetchall()
            return [r["task_id"] for r in rows]
        finally:
            conn.close()

    def get_bindings_for_task(self, task_id: str) -> list[dict]:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """SELECT b.* FROM wcf_bindings b
                   JOIN wcf_binding_tasks bt ON b.id = bt.binding_id
                   WHERE bt.task_id = ?""",
                (task_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def delete_task_bindings(self, task_id: str):
        """监控任务删除时清理关联。"""
        conn = self._get_conn()
        try:
            conn.execute(
                "DELETE FROM wcf_binding_tasks WHERE task_id = ?", (task_id,)
            )
            conn.commit()
        finally:
            conn.close()
