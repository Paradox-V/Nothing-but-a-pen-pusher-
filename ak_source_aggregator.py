"""
AKTools 信源统合模块

整合 8 个 AKTools 财经新闻接口，统一输出标准 JSON 格式。
支持 httpx 异步并发获取、基于内容哈希的去重、单信源异常隔离。
内置 SQLite 持久化层，支持只存新增条目、自动过期清理。
"""

import asyncio
import hashlib
import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import httpx

logger = logging.getLogger(__name__)


# ── SQLite 持久化层 ───────────────────────────────────────

class NewsDB:
    """新闻持久化存储，基于 SQLite。"""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS news (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        source_name  TEXT    NOT NULL,
        title        TEXT    NOT NULL,
        content      TEXT    NOT NULL,
        timestamp    TEXT,
        url          TEXT,
        tags         TEXT    NOT NULL DEFAULT '[]',
        content_hash TEXT    UNIQUE NOT NULL,
        category     TEXT    NOT NULL DEFAULT '其他',
        cluster_id   TEXT,
        created_at   TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
    );
    CREATE INDEX IF NOT EXISTS idx_news_created  ON news(created_at);
    CREATE INDEX IF NOT EXISTS idx_news_source   ON news(source_name);
    CREATE INDEX IF NOT EXISTS idx_news_hash     ON news(content_hash);
    """

    MIGRATIONS = [
        "ALTER TABLE news ADD COLUMN category TEXT NOT NULL DEFAULT '其他'",
        "ALTER TABLE news ADD COLUMN cluster_id TEXT",
        "CREATE INDEX IF NOT EXISTS idx_news_category ON news(category)",
        "CREATE INDEX IF NOT EXISTS idx_news_cluster  ON news(cluster_id)",
    ]

    def __init__(self, db_path: str | Path = "news.db"):
        self.db_path = str(db_path)
        self._conn: sqlite3.Connection | None = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.executescript(self.SCHEMA)
            # 增量迁移：为旧表添加新列
            for mig in self.MIGRATIONS:
                try:
                    self._conn.execute(mig)
                    self._conn.commit()
                except sqlite3.OperationalError:
                    pass  # 列已存在
        return self._conn

    # ── 写入 ───────────────────────────────────────────────

    def insert_many(
        self,
        items: list[dict],
        categories: list[list[str]] | None = None,
        cluster_ids: list[str] | None = None,
    ) -> tuple[int, list[int]]:
        """
        批量插入新闻，基于归一化标题去重（content_hash UNIQUE）。
        若标题相同但新条目内容更长，则更新已有记录。
        categories 为 list[list[str]]，写入时 JSON 序列化。
        返回 (实际新增条数, 新增条目的 row id 列表)。
        """
        conn = self._get_conn()
        added = 0
        new_row_ids: list[int] = []
        for idx, item in enumerate(items):
            h = AKSourceAggregator._dedup_hash(item["title"], item["content"])
            cat_list = categories[idx] if categories else ["其他"]
            cat_json = json.dumps(cat_list, ensure_ascii=False)
            cid = cluster_ids[idx] if cluster_ids else None
            try:
                cur = conn.execute(
                    "INSERT INTO news (source_name, title, content, timestamp, url, tags, content_hash, category, cluster_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        item["source_name"],
                        item["title"],
                        item["content"],
                        item.get("timestamp"),
                        item.get("url"),
                        json.dumps(item.get("tags", []), ensure_ascii=False),
                        h,
                        cat_json,
                        cid,
                    ),
                )
                new_row_ids.append(cur.lastrowid)
                added += 1
            except sqlite3.IntegrityError:
                # 标题重复 —— 如果新内容更长则更新
                existing = conn.execute(
                    "SELECT id, length(content) as clen FROM news WHERE content_hash = ?",
                    (h,),
                ).fetchone()
                if existing and len(item.get("content", "")) > existing["clen"]:
                    conn.execute(
                        "UPDATE news SET content=?, source_name=?, url=?, tags=?, category=?, cluster_id=? WHERE id=?",
                        (
                            item["content"],
                            item["source_name"],
                            item.get("url"),
                            json.dumps(item.get("tags", []), ensure_ascii=False),
                            cat_json,
                            cid,
                            existing["id"],
                        ),
                    )
        conn.commit()
        return added, new_row_ids

    # ── 过期清理 ────────────────────────────────────────────

    def purge_old(self, days: int = 30) -> int:
        """删除 created_at 超过 days 天的记录，返回删除条数。"""
        conn = self._get_conn()
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        cur = conn.execute("DELETE FROM news WHERE created_at < ?", (cutoff,))
        conn.commit()
        return cur.rowcount

    # ── 查询 ────────────────────────────────────────────────

    def _build_query(self, sources=None, categories=None, keyword=None, date_from=None, date_to=None, count_only=False):
        """统一构建 SQL，支持多 source + 多 category + keyword + 时间范围。"""
        select = "COUNT(*)" if count_only else "*"
        sql = f"SELECT {select} FROM news WHERE 1=1"
        params: list[Any] = []
        if sources:
            placeholders = ",".join("?" * len(sources))
            sql += f" AND source_name IN ({placeholders})"
            params.extend(sources)
        if categories:
            # category 存的是 JSON 数组，用 LIKE 匹配每个分类名
            cat_conds = []
            for cat in categories:
                cat_conds.append("(category LIKE ?)")
                params.append(f'%"{cat}"%')
            sql += " AND (" + " AND ".join(cat_conds) + ")"
        if keyword:
            sql += " AND (title LIKE ? OR content LIKE ?)"
            params.extend([f"%{keyword}%", f"%{keyword}%"])
        if date_from:
            sql += " AND created_at >= ?"
            params.append(date_from)
        if date_to:
            sql += " AND created_at <= ?"
            params.append(date_to + " 23:59:59")
        return sql, params

    def get_all(
        self,
        sources: list[str] | None = None,
        categories: list[str] | None = None,
        keyword: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[dict]:
        """查询新闻列表，支持按多来源、多分类、关键词和时间范围过滤。"""
        conn = self._get_conn()
        sql, params = self._build_query(
            sources=sources, categories=categories, keyword=keyword,
            date_from=date_from, date_to=date_to,
        )
        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = conn.execute(sql, params).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_count(
        self,
        sources: list[str] | None = None,
        categories: list[str] | None = None,
        keyword: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> int:
        """统计符合条件的新闻条数。"""
        conn = self._get_conn()
        sql, params = self._build_query(
            sources=sources, categories=categories, keyword=keyword,
            date_from=date_from, date_to=date_to, count_only=True,
        )
        return conn.execute(sql, params).fetchone()[0]

    def get_source_stats(self) -> dict[str, int]:
        """返回每个信源的条数。"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT source_name, COUNT(*) as cnt FROM news GROUP BY source_name"
        ).fetchall()
        return {r["source_name"]: r["cnt"] for r in rows}

    def get_total_count(self) -> int:
        conn = self._get_conn()
        return conn.execute("SELECT COUNT(*) FROM news").fetchone()[0]

    def get_sources_list(self) -> list[str]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT DISTINCT source_name FROM news ORDER BY source_name"
        ).fetchall()
        return [r["source_name"] for r in rows]

    def get_category_stats(self) -> list[dict]:
        """返回每个分类的条数统计（拆解 JSON 数组计数）。"""
        conn = self._get_conn()
        rows = conn.execute("SELECT category FROM news").fetchall()
        counter: dict[str, int] = {}
        for r in rows:
            try:
                cats = json.loads(r["category"])
            except (json.JSONDecodeError, TypeError):
                cats = [r["category"]]
            for c in cats:
                counter[c] = counter.get(c, 0) + 1
        return [{"category": k, "count": v} for k, v in sorted(counter.items(), key=lambda x: -x[1])]

    def get_cluster_list(self) -> list[dict]:
        """返回所有专题（cluster_id 非空的分组），含代表性标题和条数。"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT cluster_id, COUNT(*) as cnt, "
            "MIN(title) as sample_title, "
            "GROUP_CONCAT(DISTINCT source_name) as sources "
            "FROM news WHERE cluster_id IS NOT NULL AND cluster_id != '' "
            "GROUP BY cluster_id HAVING cnt >= 2 "
            "ORDER BY cnt DESC"
        ).fetchall()
        return [
            {
                "cluster_id": r["cluster_id"],
                "count": r["cnt"],
                "sample_title": r["sample_title"],
                "sources": r["sources"],
            }
            for r in rows
        ]

    def get_cluster_news(self, cluster_id: str, limit: int = 50) -> list[dict]:
        """返回某专题下的所有新闻。"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM news WHERE cluster_id = ? "
            "ORDER BY COALESCE(timestamp, created_at) DESC LIMIT ?",
            (cluster_id, limit),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        raw_cat = row["category"] if "category" in row.keys() else "其他"
        try:
            category = json.loads(raw_cat)
            if not isinstance(category, list):
                category = [category]
        except (json.JSONDecodeError, TypeError):
            category = [raw_cat]
        return {
            "id": row["id"],
            "source_name": row["source_name"],
            "title": row["title"],
            "content": row["content"],
            "timestamp": row["timestamp"],
            "url": row["url"],
            "tags": json.loads(row["tags"]),
            "category": category,
            "cluster_id": row["cluster_id"] if "cluster_id" in row.keys() else None,
            "created_at": row["created_at"],
        }

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def migrate_category_to_json(self) -> int:
        """将旧的单值 category 迁移为 JSON 数组格式。返回迁移条数。"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT id, category FROM news WHERE category NOT LIKE '[%'"
        ).fetchall()
        if not rows:
            return 0
        for r in rows:
            cat = r["category"] or "其他"
            conn.execute(
                "UPDATE news SET category = ? WHERE id = ?",
                (json.dumps([cat], ensure_ascii=False), r["id"]),
            )
        conn.commit()
        logger.info("分类迁移: %d 条旧数据已转为 JSON 数组格式", len(rows))
        return len(rows)

    def reclassify_all(self, vector_engine=None) -> int:
        """用 Embedding 相似度批量重新分类所有数据。需要传入已初始化的 vector_engine。返回重新分类条数。"""
        from news_vector import NewsVectorEngine
        conn = self._get_conn()
        rows = conn.execute("SELECT id, title, content FROM news").fetchall()
        if not rows:
            return 0

        ids = [r["id"] for r in rows]
        texts = [f"{r['title']} {r['content']}" for r in rows]

        if vector_engine and vector_engine._initialized:
            all_cats = vector_engine.classify_texts(texts)
        else:
            all_cats = [["其他"] for _ in texts]

        # 批量更新
        conn.executemany(
            "UPDATE news SET category = ? WHERE id = ?",
            [(json.dumps(cats, ensure_ascii=False), rid) for rid, cats in zip(ids, all_cats)],
        )
        conn.commit()
        logger.info("批量重新分类: %d 条数据已更新", len(ids))
        return len(ids)


# ── 信源聚合器 ────────────────────────────────────────────

class AKSourceAggregator:
    """AKTools 信源统合聚合器"""

    BASE_URL = "http://49.232.239.68:8080/api/public"

    SOURCE_REGISTRY: dict[str, dict[str, Any]] = {
        "stock_info_global_sina": {
            "display": "新浪快讯",
            "tags": ["财经", "全球"],
            "params": None,
        },
        "news_cctv": {
            "display": "央视新闻联播",
            "tags": ["央视", "时事"],
            "params": lambda: {
                "date": (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
            },
        },
        "futures_news_shmet": {
            "display": "上海金属网",
            "tags": ["期货", "金属"],
            "params": None,
        },
        "stock_news_main_cx": {
            "display": "财联社电报(摘要)",
            "tags": ["财联社", "电报"],
            "params": None,
        },
        "stock_info_global_cls": {
            "display": "财联社电报",
            "tags": ["财联社", "电报"],
            "params": None,
        },
        "stock_info_global_em": {
            "display": "东方财富快讯",
            "tags": ["东方财富", "财经"],
            "params": None,
        },
        "stock_info_global_futu": {
            "display": "富途快讯",
            "tags": ["富途", "全球"],
            "params": None,
        },
        "stock_info_global_ths": {
            "display": "同花顺直播",
            "tags": ["同花顺", "财经"],
            "params": None,
        },
    }

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float = 30.0,
        db: NewsDB | None = None,
    ):
        self.base_url = base_url or self.BASE_URL
        self.timeout = timeout
        self.db = db or NewsDB()
        self._seen_hashes: set[str] = set()

    # ── 工具方法 ────────────────────────────────────────────

    @staticmethod
    def _extract_title(content: str, max_len: int = 20) -> str:
        if not content:
            return ""
        start, end = content.find("【"), content.find("】")
        if start != -1 and end != -1 and end > start:
            return content[start + 1 : end]
        return content[:max_len].strip()

    @staticmethod
    def _normalize_timestamp(raw: Any) -> str | None:
        if raw is None:
            return None
        s = str(raw).strip()
        if not s:
            return None
        for fmt in (
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y%m%d",
        ):
            try:
                return datetime.strptime(s, fmt).isoformat()
            except ValueError:
                continue
        return s

    @staticmethod
    def _normalize_title(title: str) -> str:
        """归一化标题用于去重：去除【】包裹符，统一空白。"""
        t = title.strip()
        # 剥离最外层 【...】
        if t.startswith("【"):
            end = t.find("】")
            if end != -1:
                t = t[end + 1:].strip()
        # 合并多余空白
        return " ".join(t.split())

    @staticmethod
    def _dedup_hash(title: str, content: str) -> str:
        """
        去重哈希：优先基于归一化标题。
        仅在标题为空或极短（<4字）时回退到内容哈希。
        """
        norm = AKSourceAggregator._normalize_title(title)
        if len(norm) >= 4:
            return hashlib.md5(norm.encode("utf-8")).hexdigest()
        # 标题无意义时退回到内容前 200 字
        text = content[:200] if content else ""
        return hashlib.md5(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _to_list(data: Any) -> list[dict]:
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("data", "result", "items", "records"):
                v = data.get(key)
                if isinstance(v, list):
                    return v
            return [data]
        return []

    # ── 各信源解析器 ────────────────────────────────────────

    def _parse_sina(self, items: list[dict]) -> list[dict]:
        out = []
        for it in items:
            content = it.get("内容", "")
            out.append({
                "source_name": "新浪快讯",
                "title": self._extract_title(content),
                "content": content,
                "timestamp": self._normalize_timestamp(it.get("时间")),
                "url": None,
                "tags": ["财经", "全球"],
            })
        return out

    def _parse_cctv(self, items: list[dict]) -> list[dict]:
        out = []
        for it in items:
            title = it.get("title", "")
            content = it.get("content", "")
            if not title:
                title = self._extract_title(content)
            out.append({
                "source_name": "央视新闻联播",
                "title": title,
                "content": content,
                "timestamp": self._normalize_timestamp(it.get("date")),
                "url": None,
                "tags": ["央视", "时事"],
            })
        return out

    def _parse_shmet(self, items: list[dict]) -> list[dict]:
        out = []
        for it in items:
            content = it.get("内容", "")
            out.append({
                "source_name": "上海金属网",
                "title": self._extract_title(content),
                "content": content,
                "timestamp": self._normalize_timestamp(it.get("发布时间")),
                "url": None,
                "tags": ["期货", "金属"],
            })
        return out

    def _parse_cls_summary(self, items: list[dict]) -> list[dict]:
        out = []
        for it in items:
            summary = it.get("summary", "")
            tag = it.get("tag", "")
            out.append({
                "source_name": "财联社电报(摘要)",
                "title": self._extract_title(summary),
                "content": summary,
                "timestamp": None,
                "url": it.get("url"),
                "tags": [tag] if tag else ["财联社"],
            })
        return out

    def _parse_cls_full(self, items: list[dict]) -> list[dict]:
        out = []
        for it in items:
            title = it.get("标题", "")
            content = it.get("内容", "")
            if not title:
                title = self._extract_title(content)
            date_part = str(it.get("发布日期", ""))
            time_part = str(it.get("发布时间", ""))
            if date_part and time_part:
                try:
                    dt = datetime.strptime(date_part[:10], "%Y-%m-%d")
                    parts = time_part.split(":")
                    dt = dt.replace(
                        hour=int(parts[0]),
                        minute=int(parts[1]),
                        second=int(parts[2].split(".")[0]),
                    )
                    ts = dt.isoformat()
                except Exception:
                    ts = self._normalize_timestamp(date_part)
            else:
                ts = self._normalize_timestamp(date_part or None)
            out.append({
                "source_name": "财联社电报",
                "title": title,
                "content": content,
                "timestamp": ts,
                "url": None,
                "tags": ["财联社"],
            })
        return out

    def _parse_em(self, items: list[dict]) -> list[dict]:
        out = []
        for it in items:
            title = it.get("标题", "")
            content = it.get("摘要", "")
            if not title:
                title = self._extract_title(content)
            out.append({
                "source_name": "东方财富快讯",
                "title": title,
                "content": content,
                "timestamp": self._normalize_timestamp(it.get("发布时间")),
                "url": it.get("链接"),
                "tags": ["东方财富", "财经"],
            })
        return out

    def _parse_futu(self, items: list[dict]) -> list[dict]:
        out = []
        for it in items:
            title = it.get("标题", "")
            content = it.get("内容", "")
            if not title:
                title = self._extract_title(content)
            out.append({
                "source_name": "富途快讯",
                "title": title,
                "content": content,
                "timestamp": self._normalize_timestamp(it.get("发布时间")),
                "url": it.get("链接"),
                "tags": ["富途", "全球"],
            })
        return out

    def _parse_ths(self, items: list[dict]) -> list[dict]:
        out = []
        for it in items:
            title = it.get("标题", "")
            content = it.get("内容", "")
            if not title:
                title = self._extract_title(content)
            out.append({
                "source_name": "同花顺直播",
                "title": title,
                "content": content,
                "timestamp": self._normalize_timestamp(it.get("发布时间")),
                "url": it.get("链接"),
                "tags": ["同花顺", "财经"],
            })
        return out

    _PARSER_MAP: dict[str, Callable] = {
        "stock_info_global_sina": _parse_sina,
        "news_cctv": _parse_cctv,
        "futures_news_shmet": _parse_shmet,
        "stock_news_main_cx": _parse_cls_summary,
        "stock_info_global_cls": _parse_cls_full,
        "stock_info_global_em": _parse_em,
        "stock_info_global_futu": _parse_futu,
        "stock_info_global_ths": _parse_ths,
    }

    # ── 核心获取逻辑 ────────────────────────────────────────

    async def _fetch_one(
        self, client: httpx.AsyncClient, endpoint: str
    ) -> list[dict]:
        cfg = self.SOURCE_REGISTRY[endpoint]
        url = f"{self.base_url}/{endpoint}"
        params = cfg["params"]() if callable(cfg["params"]) else None
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        items = self._to_list(resp.json())
        parser = self._PARSER_MAP[endpoint]
        return parser(self, items)

    async def fetch_all(self) -> tuple[list[dict], dict[str, dict]]:
        """
        并发获取所有信源并内存去重。

        Returns
        -------
        (items, sources_status)
            items: 去重后的标准格式新闻列表
            sources_status: {endpoint: {ok, count, error, display_name}}
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            tasks = [
                self._fetch_one(client, ep) for ep in self.SOURCE_REGISTRY
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        all_items: list[dict] = []
        sources_status: dict[str, dict] = {}
        self._seen_hashes.clear()

        for ep, result in zip(self.SOURCE_REGISTRY, results):
            cfg = self.SOURCE_REGISTRY[ep]
            if isinstance(result, Exception):
                sources_status[ep] = {
                    "ok": False, "count": 0,
                    "error": str(result), "display_name": cfg["display"],
                }
                logger.error("[%s] %s", ep, result)
            else:
                sources_status[ep] = {
                    "ok": True, "count": len(result),
                    "error": None, "display_name": cfg["display"],
                }
                all_items.extend(result)

        all_items.sort(key=lambda x: x.get("timestamp") or "", reverse=True)

        # 按归一化标题分组去重：同标题只保留内容最长的版本
        groups: dict[str, dict] = {}
        for item in all_items:
            h = self._dedup_hash(item["title"], item["content"])
            if h not in groups or len(item.get("content", "")) > len(groups[h].get("content", "")):
                groups[h] = item

        deduped = sorted(groups.values(), key=lambda x: x.get("timestamp") or "", reverse=True)

        return deduped, sources_status

    def _is_duplicate(self, title: str, content: str) -> bool:
        h = self._dedup_hash(title, content)
        if h in self._seen_hashes:
            return True
        self._seen_hashes.add(h)
        return False

    # ── 抓取 + 入库 一体化 ─────────────────────────────────

    def fetch_and_store(self, purge_days: int = 30) -> dict:
        """
        抓取 → 去重 → 入库（只存新增） → 清理过期。

        Returns
        -------
        dict with keys: total_raw, new_added, purged, sources_status, fetch_time, new_row_ids
        """
        items, sources_status = self._run_fetch_all()
        total_raw = sum(s["count"] for s in sources_status.values())
        new_added, new_row_ids = self.db.insert_many(items)
        purged = self.db.purge_old(days=purge_days)

        logger.info(
            "抓取完成: 原始 %d 条, 新增 %d 条, 过期清理 %d 条",
            total_raw, new_added, purged,
        )

        return {
            "total_raw": total_raw,
            "new_added": new_added,
            "purged": purged,
            "db_total": self.db.get_total_count(),
            "sources_status": sources_status,
            "fetch_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "new_items": items,
            "new_row_ids": new_row_ids,
        }

    def _run_fetch_all(self) -> tuple[list[dict], dict[str, dict]]:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, self.fetch_all()).result()
        return asyncio.run(self.fetch_all())


# ── 命令行测试 ────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    db = NewsDB("test_news.db")
    agg = AKSourceAggregator(db=db)
    result = agg.fetch_and_store()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n数据库中共 {db.get_total_count()} 条新闻")
    db.close()
