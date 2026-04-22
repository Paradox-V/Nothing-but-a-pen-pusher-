"""
RSS 向量引擎 —— 将 RSS 条目嵌入 ChromaDB

基于 BAAI/bge-small-zh-v1.5 模型 + ChromaDB。
仅运行于调度器进程中，复用已有嵌入模型。
"""

import logging
import sqlite3

import chromadb

logger = logging.getLogger(__name__)


class RSSVectorEngine:
    """RSS ChromaDB 向量化：嵌入、去重、搜索。"""

    DEDUP_THRESHOLD = 0.85
    COLLECTION_NAME = "rss_embeddings"

    def __init__(self, db_path: str = "data/rss.db",
                 chroma_dir: str = "data/chroma_db"):
        self.db_path = db_path
        self.chroma_dir = chroma_dir
        self.collection: chromadb.Collection | None = None
        self._initialized = False

    def initialize(self, chroma_client: chromadb.PersistentClient,
                   encode_fn=None, collection_name: str | None = None) -> None:
        """初始化（复用调度器已加载的 ChromaDB 客户端和嵌入模型）。

        Args:
            chroma_client: 已创建的 ChromaDB PersistentClient
            encode_fn: 嵌入函数，签名 (texts: list[str]) -> list[list[float]]
            collection_name: ChromaDB collection 名称，默认使用 COLLECTION_NAME
        """
        if self._initialized:
            return

        self.chroma_client = chroma_client
        self._encode_fn = encode_fn
        name = collection_name or self.COLLECTION_NAME
        self.collection = self.chroma_client.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info("RSS 向量引擎就绪，已有 %d 条向量", self.collection.count())
        self._initialized = True

    def _encode(self, texts: list[str]) -> list[list[float]]:
        if not self._encode_fn:
            return []
        return self._encode_fn(texts)

    def _text_for_embed(self, title: str, summary: str) -> str:
        combined = f"{title}。{summary[:300]}" if title else summary[:400]
        return combined.strip()

    def upsert_items(self, items: list[dict]) -> int:
        """将 RSS 条目嵌入并写入 ChromaDB（带去重）。

        Args:
            items: list of dict，每个含 id, title, feed_id, summary,
                   published_at, url, feed_name

        Returns:
            实际新增的条目数
        """
        if not self._initialized or not items:
            return 0

        texts = [self._text_for_embed(it["title"], it.get("summary", "")) for it in items]
        embeddings = self._encode(texts)
        if not embeddings:
            return 0

        new_items, new_embs, new_ids, new_metas, new_docs = [], [], [], [], []

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

            item_id = f"rss_{item['id']}"
            new_items.append(item)
            new_embs.append(emb)
            new_ids.append(item_id)
            new_docs.append(texts[i])
            new_metas.append({
                "title": item["title"][:200],
                "feed_id": item.get("feed_id", ""),
                "feed_name": item.get("feed_name", ""),
                "author": item.get("author", ""),
                "published_at": item.get("published_at", ""),
                "url": item.get("url", ""),
                "source_type": "rss",
            })

        if new_ids:
            self.collection.upsert(
                ids=new_ids,
                embeddings=new_embs,
                metadatas=new_metas,
                documents=new_docs,
            )
            logger.info("RSS ChromaDB 新增 %d 条", len(new_ids))

        return len(new_ids)

    def semantic_search(self, query_embedding: list[float], top_k: int = 5) -> list[dict]:
        """根据已有 embedding 搜索 RSS 条目。"""
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
                    "source_name": meta.get("feed_name", meta.get("feed_id", "")),
                    "feed_id": meta.get("feed_id", ""),
                    "url": meta.get("url", ""),
                    "published_at": meta.get("published_at", ""),
                    "source_type": "rss",
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
                     if cid not in {f"rss_{rid}" for rid in existing_ids}]

        if to_delete:
            self.collection.delete(ids=to_delete)
            logger.info("RSS ChromaDB 清理 %d 条过期条目", len(to_delete))

        return len(to_delete)
