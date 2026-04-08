"""
热榜向量引擎 —— 将热榜条目嵌入 ChromaDB

基于 BAAI/bge-small-zh-v1.5 模型 + ChromaDB。
仅运行于调度器进程中，复用已有嵌入模型。
"""

import hashlib
import logging
import sqlite3

import chromadb

logger = logging.getLogger(__name__)


class HotlistVectorEngine:
    """热榜 ChromaDB 向量化：嵌入、去重、搜索。"""

    DEDUP_THRESHOLD = 0.85
    COLLECTION_NAME = "hotlist_embeddings"

    def __init__(self, db_path: str = "data/hotlist.db",
                 chroma_dir: str = "data/chroma_db"):
        self.db_path = db_path
        self.chroma_dir = chroma_dir
        self.collection: chromadb.Collection | None = None
        self._initialized = False

    def initialize(self, chroma_client: chromadb.PersistentClient,
                   encode_fn=None) -> None:
        """初始化（复用调度器已加载的 ChromaDB 客户端和嵌入模型）。

        Args:
            chroma_client: 已创建的 ChromaDB PersistentClient
            encode_fn: 嵌入函数，签名 (texts: list[str]) -> list[list[float]]
        """
        if self._initialized:
            return

        self.chroma_client = chroma_client
        self._encode_fn = encode_fn
        self.collection = self.chroma_client.get_or_create_collection(
            name=self.COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info("热榜向量引擎就绪，已有 %d 条向量", self.collection.count())
        self._initialized = True

    def _encode(self, texts: list[str]) -> list[list[float]]:
        if not self._encode_fn:
            return []
        return self._encode_fn(texts)

    def upsert_items(self, items: list[dict]) -> int:
        """将热榜条目嵌入并写入 ChromaDB（带去重）。

        Args:
            items: list of dict，每个含 id, title, platform, platform_name,
                   hot_rank, crawl_time

        Returns:
            实际新增的条目数
        """
        if not self._initialized or not items:
            return 0

        texts = [it["title"] for it in items]
        embeddings = self._encode(texts)
        if not embeddings:
            return 0

        new_items, new_embs, new_ids, new_metas = [], [], [], []

        for i, (item, emb) in enumerate(zip(items, embeddings)):
            # 去重：与已有向量比较
            if self.collection.count() > 0:
                results = self.collection.query(
                    query_embeddings=[emb],
                    n_results=1,
                    include=["distances"],
                )
                if results["distances"] and results["distances"][0]:
                    sim = 1 - results["distances"][0][0]
                    if sim > self.DEDUP_THRESHOLD:
                        continue

            item_id = f"hot_{item['id']}"
            new_items.append(item)
            new_embs.append(emb)
            new_ids.append(item_id)
            new_metas.append({
                "title": item["title"][:200],
                "platform": item.get("platform", ""),
                "platform_name": item.get("platform_name", ""),
                "hot_rank": item.get("hot_rank") or 0,
                "crawl_time": item.get("crawl_time", ""),
                "source_type": "hotlist",
            })

        if new_ids:
            self.collection.upsert(
                ids=new_ids,
                embeddings=new_embs,
                metadatas=new_metas,
                documents=texts[:len(new_ids)],
            )
            logger.info("热榜 ChromaDB 新增 %d 条", len(new_ids))

        return len(new_ids)

    def semantic_search(self, query_embedding: list[float], top_k: int = 5) -> list[dict]:
        """根据已有 embedding 搜索热榜条目。"""
        if not self._initialized or self.collection.count() == 0:
            return []

        n = min(top_k, self.collection.count())
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=n,
            include=["metadatas", "distances", "documents"],
        )

        output = []
        if results["ids"] and results["ids"][0]:
            for i in range(len(results["ids"][0])):
                meta = results["metadatas"][0][i] if results["metadatas"] else {}
                dist = results["distances"][0][i] if results["distances"] else 0
                doc = results["documents"][0][i] if results["documents"] else ""
                output.append({
                    "id": results["ids"][0][i],
                    "title": meta.get("title", ""),
                    "content": doc,
                    "source_name": meta.get("platform_name", meta.get("platform", "")),
                    "platform": meta.get("platform", ""),
                    "hot_rank": meta.get("hot_rank", 0),
                    "crawl_time": meta.get("crawl_time", ""),
                    "source_type": "hotlist",
                    "similarity": round(1 - dist, 4),
                    "distance": dist,
                })

        return output

    def sync_purge(self, existing_ids: set[int]) -> int:
        """清理 ChromaDB 中已从 SQLite 删除的条目。"""
        if not self._initialized:
            return 0

        chroma_ids = set(self.collection.get()["ids"])
        to_delete = [cid for cid in chroma_ids
                     if cid not in {f"hot_{rid}" for rid in existing_ids}]

        if to_delete:
            self.collection.delete(ids=to_delete)
            logger.info("热榜 ChromaDB 清理 %d 条过期条目", len(to_delete))

        return len(to_delete)
