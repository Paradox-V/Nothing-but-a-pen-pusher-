"""
定时采集调度器 —— 独立进程运行

由 systemd 管理，每 10 分钟抓取一次，自动去重入库、清理过期数据。
集成向量引擎：语义去重、分类、聚类、ChromaDB 写入。
"""

import json
import logging
import os
import sqlite3
import time
from datetime import datetime

# 离线模式：跳过 HuggingFace 网络检查，直接使用本地缓存
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_OFFLINE"] = "1"

from ak_source_aggregator import AKSourceAggregator, NewsDB
from news_vector import NewsVectorEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [scheduler] %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

DB_PATH = "/opt/news_viewer/news.db"
CHROMA_DIR = "/opt/news_viewer/chroma_db"
INTERVAL = 600  # 10 分钟
PURGE_DAYS = 7


def main():
    db = NewsDB(DB_PATH)
    agg = AKSourceAggregator(db=db)

    # 初始化向量引擎
    vector_engine = NewsVectorEngine(db_path=DB_PATH, chroma_dir=CHROMA_DIR)
    try:
        vector_engine.initialize()
        logger.info("向量引擎初始化成功")
    except Exception as e:
        logger.error("向量引擎初始化失败: %s，将以无向量模式运行", e)
        vector_engine = None

    # 启动时迁移旧数据（单值 → JSON 数组）并重新分类
    try:
        migrated = db.migrate_category_to_json()
        if migrated > 0 and vector_engine and vector_engine._initialized:
            db.reclassify_all(vector_engine=vector_engine)
            logger.info("数据迁移完成: %d 条旧数据已转为多标签分类", migrated)
        elif migrated > 0:
            logger.info("数据迁移完成: %d 条旧数据已转为 JSON 数组格式（向量引擎未就绪，跳过重分类）", migrated)
    except Exception as e:
        logger.error("数据迁移失败: %s", e)

    # 首次部署回填
    if vector_engine:
        try:
            backfill_count = vector_engine.backfill_existing()
            if backfill_count > 0:
                logger.info("回填完成: %d 条", backfill_count)
        except Exception as e:
            logger.error("回填失败: %s", e)

    logger.info("调度器启动，间隔 %d 秒，保留 %d 天", INTERVAL, PURGE_DAYS)

    # 启动时立即抓取一次
    _run_once(agg, db, vector_engine)

    while True:
        time.sleep(INTERVAL)
        _run_once(agg, db, vector_engine)


def _run_once(agg: AKSourceAggregator, db: NewsDB, vector_engine: NewsVectorEngine | None):
    try:
        result = agg.fetch_and_store(purge_days=PURGE_DAYS)
        new_items = result.get("new_items", [])
        new_row_ids = result.get("new_row_ids", [])

        # 向量处理管线
        if vector_engine and new_items:
            _vector_pipeline(vector_engine, new_items, new_row_ids)

        # 同步清理 ChromaDB
        if vector_engine and result["purged"] > 0:
            try:
                vector_engine.sync_chroma_purge()
            except Exception as e:
                logger.error("ChromaDB 清理失败: %s", e)

        logger.info(
            "采集完成: 原始 %d, 新增 %d, 过期清理 %d, 库存 %d",
            result["total_raw"],
            result["new_added"],
            result["purged"],
            result["db_total"],
        )
    except Exception as e:
        logger.error("采集异常: %s", e)


def _vector_pipeline(
    vector_engine: NewsVectorEngine,
    items: list[dict],
    row_ids: list[int],
) -> None:
    """执行向量处理管线：语义去重 → 分类 → 聚类 → 写入 ChromaDB。"""
    try:
        # 语义去重（与 ChromaDB 已有条目比较）
        deduped = vector_engine.semantic_dedup(items)

        # 用 (title, content前100字) 作为唯一标识来匹配
        deduped_set = set()
        for d in deduped:
            deduped_set.add((d["title"], d.get("content", "")[:100]))

        deduped_items = []
        deduped_row_ids = []
        for item, rid in zip(items, row_ids):
            key = (item["title"], item.get("content", "")[:100])
            if key in deduped_set:
                deduped_items.append(item)
                deduped_row_ids.append(rid)

        # 从 SQLite 中删除语义重复的条目
        removed_row_ids = [
            rid for item, rid in zip(items, row_ids)
            if (item["title"], item.get("content", "")[:100]) not in deduped_set
        ]
        if removed_row_ids:
            conn = sqlite3.connect(DB_PATH)
            placeholders = ",".join("?" * len(removed_row_ids))
            conn.execute(
                f"DELETE FROM news WHERE id IN ({placeholders})",
                removed_row_ids,
            )
            conn.commit()
            conn.close()
            logger.info("语义去重: 从 SQLite 删除 %d 条", len(removed_row_ids))

        if not deduped_items:
            return

        # 分类
        categories = vector_engine.classify_items(deduped_items)

        # 聚类
        cluster_ids = vector_engine.assign_clusters(deduped_items)

        # 更新 SQLite 中的 category 和 cluster_id
        conn = sqlite3.connect(DB_PATH)
        for rid, cat, cid in zip(deduped_row_ids, categories, cluster_ids):
            cat_json = json.dumps(cat, ensure_ascii=False) if isinstance(cat, list) else cat
            conn.execute(
                "UPDATE news SET category = ?, cluster_id = ? WHERE id = ?",
                (cat_json, cid, rid),
            )
        conn.commit()
        conn.close()

        # 写入 ChromaDB
        vector_engine.upsert_to_chroma(
            deduped_items, deduped_row_ids, categories, cluster_ids
        )

    except Exception as e:
        logger.error("向量处理管线异常: %s", e)


if __name__ == "__main__":
    main()
