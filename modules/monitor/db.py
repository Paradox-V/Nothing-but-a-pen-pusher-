"""监控任务 + 推送日志 SQLite 持久化"""

import json
import os
import sqlite3


class MonitorDB:
    """监控任务与推送日志的 SQLite 持久化"""

    def __init__(self, db_path: str = "data/monitor.db"):
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
            CREATE TABLE IF NOT EXISTS monitor_tasks (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                keywords TEXT NOT NULL,
                filters TEXT,
                schedule TEXT NOT NULL DEFAULT 'daily_morning',
                push_config TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                last_run_at TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
            );
            CREATE TABLE IF NOT EXISTS push_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                status TEXT NOT NULL,
                report_summary TEXT,
                error TEXT,
                pushed_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
            );
            CREATE INDEX IF NOT EXISTS idx_push_logs_task
                ON push_logs(task_id, pushed_at DESC);
        """)
        conn.close()

    # ── 内部字段与用户字段 ─────────────────────────────────────
    _INTERNAL_FIELDS = {"last_run_at"}
    _USER_FIELDS = {"name", "keywords", "filters", "schedule", "push_config", "is_active"}
    _ALL_MUTABLE = _USER_FIELDS | _INTERNAL_FIELDS

    # ── 任务 CRUD ─────────────────────────────────────────────

    def create_task(self, task_id: str, name: str, keywords: list,
                    filters: dict | None, schedule: str,
                    push_config: list) -> dict:
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO monitor_tasks (id, name, keywords, filters, schedule, push_config) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (task_id, name, json.dumps(keywords, ensure_ascii=False),
             json.dumps(filters or {}, ensure_ascii=False),
             schedule,
             json.dumps(push_config, ensure_ascii=False)),
        )
        conn.commit()
        # 查询后再关闭连接
        row = conn.execute("SELECT * FROM monitor_tasks WHERE id = ?", (task_id,)).fetchone()
        conn.close()
        return self._sanitize_row(dict(row)) if row else {"id": task_id, "name": name}

    def get_tasks(self) -> list[dict]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT id, name, keywords, filters, schedule, push_config, "
            "  is_active, last_run_at, created_at, updated_at "
            "FROM monitor_tasks ORDER BY updated_at DESC"
        ).fetchall()
        conn.close()
        return [self._sanitize_row(dict(r)) for r in rows]

    def get_task(self, task_id: str) -> dict | None:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM monitor_tasks WHERE id = ?", (task_id,)
        ).fetchone()
        conn.close()
        return self._sanitize_row(dict(row)) if row else None

    def get_task_raw(self, task_id: str) -> dict | None:
        """获取未脱敏的原始任务数据（内部使用）。"""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM monitor_tasks WHERE id = ?", (task_id,)
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def update_task(self, task_id: str, **kwargs) -> dict | None:
        updates = {k: v for k, v in kwargs.items() if k in self._ALL_MUTABLE}
        if not updates:
            return None
        # JSON 编码复杂字段
        if "keywords" in updates:
            updates["keywords"] = json.dumps(updates["keywords"], ensure_ascii=False)
        if "filters" in updates:
            updates["filters"] = json.dumps(updates["filters"], ensure_ascii=False)
        if "push_config" in updates:
            updates["push_config"] = json.dumps(updates["push_config"], ensure_ascii=False)

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [task_id]
        conn = self._get_conn()
        conn.execute(
            f"UPDATE monitor_tasks SET {set_clause}, "
            "updated_at = datetime('now','localtime') WHERE id = ?",
            values,
        )
        conn.commit()
        conn.close()
        return self.get_task(task_id)

    def delete_task(self, task_id: str) -> bool:
        conn = self._get_conn()
        conn.execute("DELETE FROM push_logs WHERE task_id = ?", (task_id,))
        cursor = conn.execute("DELETE FROM monitor_tasks WHERE id = ?", (task_id,))
        conn.commit()
        conn.close()
        return cursor.rowcount > 0

    def get_active_tasks(self) -> list[dict]:
        """获取所有活跃任务（未脱敏，内部使用）。"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM monitor_tasks WHERE is_active = 1"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    # ── 推送日志 ─────────────────────────────────────────────

    def log_push(self, task_id: str, status: str, report_summary: str = "",
                 error: str = ""):
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO push_logs (task_id, status, report_summary, error) "
            "VALUES (?, ?, ?, ?)",
            (task_id, status, report_summary[:500], error),
        )
        conn.commit()
        conn.close()

    def get_push_logs(self, task_id: str, limit: int = 20) -> list[dict]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT id, task_id, status, report_summary, error, pushed_at "
            "FROM push_logs WHERE task_id = ? ORDER BY pushed_at DESC LIMIT ?",
            (task_id, limit),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    # ── 脱敏 ─────────────────────────────────────────────────

    @staticmethod
    def _sanitize_row(row: dict) -> dict:
        """对 push_config 中的敏感信息做脱敏处理。"""
        if row.get("push_config"):
            try:
                configs = json.loads(row["push_config"]) if isinstance(row["push_config"], str) else row["push_config"]
                sanitized = []
                for c in configs:
                    sc = dict(c)
                    if "url" in sc:
                        url = sc["url"]
                        if len(url) > 20:
                            sc["url"] = url[:15] + "***" + url[-5:]
                    if "secret" in sc:
                        sc["secret"] = "***"
                    sanitized.append(sc)
                row["push_config"] = json.dumps(sanitized, ensure_ascii=False)
            except (json.JSONDecodeError, TypeError):
                pass
        # 解析 JSON 字段为对象
        for field in ("keywords", "filters"):
            if row.get(field) and isinstance(row[field], str):
                try:
                    row[field] = json.loads(row[field])
                except (json.JSONDecodeError, TypeError):
                    pass
        return row
