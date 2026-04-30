"""
向量服务 HTTP 客户端

scheduler 调用 vector_service.py 的轻量客户端。
不加载 PyTorch/模型，所有向量操作委托给独立进程 vector_service.py（端口 5001）。
"""
import json
import logging
import urllib.parse
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://127.0.0.1:5001"
TIMEOUT = 60  # 向量操作可能较慢


class VectorClient:
    """轻量 HTTP 客户端，替代直接加载向量引擎。"""

    def __init__(self, base_url: str = DEFAULT_BASE_URL):
        self.base_url = base_url.rstrip("/")

    def is_healthy(self) -> bool:
        """检查向量服务是否在线。"""
        try:
            resp = self._get("/health")
            return resp.get("ok", False)
        except Exception:
            return False

    # ── 新闻向量管线 ──────────────────────────────────────

    def pipeline_news(self, items: list, row_ids: list) -> dict:
        """完整新闻向量管线：去重 -> 分类 -> 聚类 -> 写入 ChromaDB。

        Returns:
            {"kept_items": [...], "kept_row_ids": [...],
             "categories": [...], "cluster_ids": [...], "removed_row_ids": [...]}
        """
        return self._post("/pipeline/news", {
            "items": items,
            "row_ids": row_ids,
        })

    # ── 热榜 / RSS 向量化 ────────────────────────────────

    def pipeline_hotlist(self, items: list) -> dict:
        """热榜条目向量化。Returns {"upserted": int}"""
        return self._post("/pipeline/hotlist", {"items": items})

    def pipeline_rss(self, items: list) -> dict:
        """RSS 条目向量化。Returns {"upserted": int}"""
        return self._post("/pipeline/rss", {"items": items})

    # ── 清理 ─────────────────────────────────────────────

    def purge_news(self) -> dict:
        """清理新闻 ChromaDB 孤儿向量。Returns {"purged": int}"""
        return self._post("/purge/news", {})

    def purge_hotlist(self, existing_ids: list) -> dict:
        """清理热榜孤儿向量。Returns {"purged": int}"""
        return self._post("/purge/hotlist", {"existing_ids": existing_ids})

    def purge_rss(self, existing_ids: list) -> dict:
        """清理 RSS 孤儿向量。Returns {"purged": int}"""
        return self._post("/purge/rss", {"existing_ids": existing_ids})

    # ── 回填 & 迁移 ──────────────────────────────────────

    def backfill(self) -> dict:
        """首次部署回填。Returns {"backfilled": int}"""
        return self._post("/backfill", {})

    def migrate_categories(self) -> dict:
        """迁移旧分类数据。Returns {"migrated": int}"""
        return self._post("/migrate_categories", {})

    # ── 归档迁移 ─────────────────────────────────────────

    def archive_migrate_news(self) -> dict:
        return self._post("/archive/migrate_news", {})

    def archive_migrate_hotlist(self) -> dict:
        return self._post("/archive/migrate_hotlist", {})

    def archive_migrate_rss(self) -> dict:
        return self._post("/archive/migrate_rss", {})

    # ── 搜索 ─────────────────────────────────────────────

    def semantic_search(self, query: str, n: int = 20,
                        categories: list | None = None,
                        sources: list | None = None) -> list:
        """语义搜索新闻。"""
        params = [f"q={urllib.parse.quote(query)}", f"n={n}"]
        if categories:
            params.append(f"category={','.join(categories)}")
        if sources:
            params.append(f"source={','.join(sources)}")
        try:
            return self._get("/semantic_search?" + "&".join(params))
        except Exception as e:
            logger.error("语义搜索失败: %s", e)
            return []

    # ── 内部方法 ─────────────────────────────────────────

    def _get(self, path: str):
        url = f"{self.base_url}{path}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _post(self, path: str, data: dict):
        url = f"{self.base_url}{path}"
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            logger.error("VectorClient POST %s failed: %s %s", path, e.code, err_body)
            return {"error": f"HTTP {e.code}", "detail": err_body}
        except urllib.error.URLError as e:
            logger.error("VectorClient POST %s connection failed: %s", path, e.reason)
            return {"error": "connection_failed", "detail": str(e.reason)}
