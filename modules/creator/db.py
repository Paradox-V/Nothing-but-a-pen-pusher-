"""文案创作模块 - SQLite 持久化层

替代 framework.py / article.py 中的内存字典存储。
"""

import json
import os
import sqlite3
import logging

logger = logging.getLogger(__name__)


class CreatorDB:
    """文案框架和生成任务的持久化存储"""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS frameworks (
        id                TEXT PRIMARY KEY,
        title             TEXT NOT NULL,
        requirements      TEXT NOT NULL DEFAULT '',
        industry          TEXT NOT NULL DEFAULT '',
        keyword           TEXT NOT NULL DEFAULT '',
        article_structure TEXT NOT NULL DEFAULT '',
        writing_approach  TEXT NOT NULL DEFAULT '',
        reference_material TEXT NOT NULL DEFAULT '',
        status            TEXT NOT NULL DEFAULT 'draft',
        chat_history      TEXT NOT NULL DEFAULT '[]',
        final_article     TEXT NOT NULL DEFAULT '',
        images            TEXT NOT NULL DEFAULT '[]',
        round             INTEGER NOT NULL DEFAULT 0,
        created_at        TEXT NOT NULL DEFAULT (datetime('now','localtime')),
        updated_at        TEXT NOT NULL DEFAULT (datetime('now','localtime'))
    );

    CREATE TABLE IF NOT EXISTS gen_tasks (
        id             TEXT PRIMARY KEY,
        framework_id   TEXT NOT NULL REFERENCES frameworks(id),
        status         TEXT NOT NULL DEFAULT 'running',
        progress       TEXT NOT NULL DEFAULT '',
        result         TEXT,
        created_at     TEXT NOT NULL DEFAULT (datetime('now','localtime'))
    );

    CREATE INDEX IF NOT EXISTS idx_fw_status ON frameworks(status);
    CREATE INDEX IF NOT EXISTS idx_task_fw    ON gen_tasks(framework_id);
    """

    def __init__(self, db_path: str = "data/creator.db"):
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
        try:
            conn.executescript(self.SCHEMA)
        finally:
            conn.close()

    # ── Framework 操作 ──────────────────────────────────────

    def save_framework(self, fw_dict: dict) -> None:
        """保存或更新框架（upsert）"""
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT INTO frameworks
                    (id, title, requirements, industry, keyword,
                     article_structure, writing_approach, reference_material,
                     status, chat_history, final_article, images, round)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                     title=excluded.title, requirements=excluded.requirements,
                     industry=excluded.industry, keyword=excluded.keyword,
                     article_structure=excluded.article_structure,
                     writing_approach=excluded.writing_approach,
                     reference_material=excluded.reference_material,
                     status=excluded.status, chat_history=excluded.chat_history,
                     final_article=excluded.final_article, images=excluded.images,
                     round=excluded.round, updated_at=datetime('now','localtime')""",
                (
                    fw_dict["id"],
                    fw_dict.get("title", ""),
                    fw_dict.get("requirements", ""),
                    fw_dict.get("industry", ""),
                    fw_dict.get("keyword", ""),
                    fw_dict.get("article_structure", ""),
                    fw_dict.get("writing_approach", ""),
                    fw_dict.get("reference_material", ""),
                    fw_dict.get("status", "draft"),
                    json.dumps(fw_dict.get("chat_history", []), ensure_ascii=False),
                    fw_dict.get("final_article", ""),
                    json.dumps(fw_dict.get("images", []), ensure_ascii=False),
                    fw_dict.get("round", 0),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def get_framework(self, fw_id: str) -> dict | None:
        """获取框架，返回字典或 None"""
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT * FROM frameworks WHERE id = ?", (fw_id,)).fetchone()
            if not row:
                return None
            d = dict(row)
            d["chat_history"] = json.loads(d["chat_history"])
            d["images"] = json.loads(d["images"])
            return d
        finally:
            conn.close()

    # ── Task 操作 ───────────────────────────────────────────

    def create_task(self, task_id: str, framework_id: str) -> None:
        """创建生成任务"""
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO gen_tasks (id, framework_id, status, progress) VALUES (?, ?, 'running', '正在生成文章...')",
                (task_id, framework_id),
            )
            conn.commit()
        finally:
            conn.close()

    def update_task(self, task_id: str, **kwargs) -> None:
        """更新任务状态"""
        if not kwargs:
            return
        fields = []
        values = []
        for k in ("status", "progress", "result"):
            if k in kwargs:
                fields.append(f"{k} = ?")
                val = kwargs[k]
                values.append(json.dumps(val, ensure_ascii=False) if k == "result" and val else val)
        if not fields:
            return
        values.append(task_id)
        conn = self._get_conn()
        try:
            conn.execute(
                f"UPDATE gen_tasks SET {', '.join(fields)} WHERE id = ?",
                values,
            )
            conn.commit()
        finally:
            conn.close()

    def get_task(self, task_id: str) -> dict | None:
        """获取任务状态"""
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT * FROM gen_tasks WHERE id = ?", (task_id,)).fetchone()
            if not row:
                return None
            d = dict(row)
            if d.get("result"):
                try:
                    d["result"] = json.loads(d["result"])
                except (json.JSONDecodeError, TypeError):
                    pass
            return d
        finally:
            conn.close()
