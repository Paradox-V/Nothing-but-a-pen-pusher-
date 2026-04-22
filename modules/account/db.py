"""账号数据库 — data/account.db

两张表：
  users(id, username, password_hash, email, enabled, role, created_at, updated_at, last_login_at)
  user_sessions(id, user_id, created_at, expires_at, revoked)
  invite_codes(code, created_by, used_by, expires_at, created_at)
"""

import os
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import bcrypt

_DB_PATH = str(Path("data") / "account.db")

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    email TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    role TEXT NOT NULL DEFAULT 'user',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS user_sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS invite_codes (
    code TEXT PRIMARY KEY,
    created_by TEXT,
    used_by TEXT,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON user_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_revoked ON user_sessions(revoked, expires_at);
"""


class AccountDB:
    def __init__(self, db_path: str = _DB_PATH):
        self._db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
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

    # ── 用户 CRUD ────────────────────────────────────────────────

    def create_user(self, username: str, password: str,
                    email: str = "", role: str = "user") -> dict:
        """创建用户，密码使用 bcrypt 哈希存储。

        Returns:
            用户字典（不含 password_hash）

        Raises:
            ValueError: 用户名已存在
        """
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        user_id = str(uuid.uuid4())
        password_hash = bcrypt.hashpw(
            password.encode("utf-8"), bcrypt.gensalt(rounds=12)
        ).decode("utf-8")

        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO users (id, username, password_hash, email, role, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_id, username, password_hash, email or "", role, now, now),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            raise ValueError(f"用户名「{username}」已存在")
        finally:
            conn.close()

        return self.get_user_by_id(user_id)

    def get_user_by_username(self, username: str) -> dict | None:
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT id, username, email, enabled, role, created_at, updated_at, last_login_at "
                "FROM users WHERE username = ?", (username,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_user_by_id(self, user_id: str) -> dict | None:
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT id, username, email, enabled, role, created_at, updated_at, last_login_at "
                "FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    # 允许更新的列名白名单（防止 SQL 注入）
    _UPDATE_ALLOWED_COLS = frozenset({
        "username", "email", "enabled", "role", "password_hash", "last_login_at", "updated_at"
    })

    def update_user(self, user_id: str, **kwargs) -> dict | None:
        """更新用户字段，password 自动转 bcrypt。"""
        allowed = {"username", "email", "enabled", "role", "password", "last_login_at"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return None

        # 密码单独处理
        if "password" in updates:
            updates["password_hash"] = bcrypt.hashpw(
                updates.pop("password").encode("utf-8"), bcrypt.gensalt(rounds=12)
            ).decode("utf-8")

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        updates["updated_at"] = now

        # 二次过滤列名，确保只有白名单列进入 SET 子句（防 SQL 注入）
        updates = {k: v for k, v in updates.items() if k in self._UPDATE_ALLOWED_COLS}
        if not updates:
            return self.get_user_by_id(user_id)

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [user_id]

        conn = self._get_conn()
        try:
            conn.execute(f"UPDATE users SET {set_clause} WHERE id = ?", values)
            conn.commit()
        finally:
            conn.close()
        return self.get_user_by_id(user_id)

    def delete_user(self, user_id: str) -> bool:
        """删除用户及其所有 sessions。"""
        conn = self._get_conn()
        try:
            conn.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))
            cursor = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def list_users(self, page: int = 1, page_size: int = 20) -> dict:
        """分页获取用户列表（不含密码哈希）。"""
        offset = (page - 1) * page_size
        conn = self._get_conn()
        try:
            total = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            rows = conn.execute(
                "SELECT id, username, email, enabled, role, created_at, updated_at, last_login_at "
                "FROM users ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (page_size, offset),
            ).fetchall()
            return {
                "items": [dict(r) for r in rows],
                "total": total,
                "page": page,
                "page_size": page_size,
            }
        finally:
            conn.close()

    def get_user_count(self) -> int:
        conn = self._get_conn()
        try:
            return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        finally:
            conn.close()

    # ── 密码验证 ─────────────────────────────────────────────────

    def verify_password(self, username: str, password: str) -> dict | None:
        """验证用户名+密码，成功返回用户字典，失败返回 None。"""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT id, username, password_hash, email, enabled, role, "
                "created_at, updated_at, last_login_at "
                "FROM users WHERE username = ?", (username,)
            ).fetchone()
        finally:
            conn.close()

        if not row:
            return None

        user = dict(row)
        password_hash = user.pop("password_hash")

        if not bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8")):
            return None

        if not user.get("enabled"):
            return None

        return user

    # ── Session 管理 ─────────────────────────────────────────────

    def create_session(self, user_id: str, expires_in_hours: int = 72) -> str:
        """创建用户 session，返回 session id（用作 JWT jti）。"""
        now = datetime.now()
        session_id = str(uuid.uuid4())
        expires_at = (now + timedelta(hours=expires_in_hours)).strftime("%Y-%m-%d %H:%M:%S")
        now_str = now.strftime("%Y-%m-%d %H:%M:%S")

        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO user_sessions (id, user_id, created_at, expires_at) "
                "VALUES (?, ?, ?, ?)",
                (session_id, user_id, now_str, expires_at),
            )
            conn.commit()
        finally:
            conn.close()
        return session_id

    def revoke_session(self, jti: str):
        """吊销 session。"""
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE user_sessions SET revoked = 1 WHERE id = ?", (jti,)
            )
            conn.commit()
        finally:
            conn.close()

    def is_session_valid(self, jti: str) -> bool:
        """检查 session 是否有效（未吊销且未过期）。"""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT revoked, expires_at FROM user_sessions WHERE id = ?", (jti,)
            ).fetchone()
        finally:
            conn.close()

        if not row:
            return False
        if row["revoked"]:
            return False
        expires_at = row["expires_at"]
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return expires_at > now

    # ── 邀请码 ─────────────────────────────────────────────────

    def create_invite_code(self, created_by: str = "") -> str:
        """生成一次性邀请码，有效期 24 小时。"""
        import secrets as _secrets
        code = _secrets.token_urlsafe(16)
        now = datetime.now()
        expires_at = (now + timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
        now_str = now.strftime("%Y-%m-%d %H:%M:%S")

        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO invite_codes (code, created_by, expires_at, created_at) "
                "VALUES (?, ?, ?, ?)",
                (code, created_by, expires_at, now_str),
            )
            conn.commit()
        finally:
            conn.close()
        return code

    def use_invite_code(self, code: str, user_id: str) -> bool:
        """使用邀请码，成功返回 True。"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT code, used_by, expires_at FROM invite_codes WHERE code = ?",
                (code,)
            ).fetchone()
            if not row:
                return False
            if row["used_by"]:
                return False  # 已被使用
            if row["expires_at"] <= now:
                return False  # 已过期
            conn.execute(
                "UPDATE invite_codes SET used_by = ? WHERE code = ?",
                (user_id, code)
            )
            conn.commit()
            return True
        finally:
            conn.close()

    def is_invite_code_valid(self, code: str) -> bool:
        """检查邀请码是否有效（未使用且未过期）。"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT used_by, expires_at FROM invite_codes WHERE code = ?",
                (code,)
            ).fetchone()
        finally:
            conn.close()

        if not row:
            return False
        return not row["used_by"] and row["expires_at"] > now
