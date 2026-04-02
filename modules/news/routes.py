"""
新闻模块 - Flask Blueprint 路由

从 news_viewer.py 提取的全部 API 路由，
包括新闻列表、状态查询、语义搜索、分类统计、专题聚合、手动抓取。
"""

import json
import logging
import sqlite3
import threading

from flask import Blueprint, jsonify, request

from modules.news.db import NewsDB
from modules.news.vector import NewsVectorEngine

logger = logging.getLogger(__name__)

news_bp = Blueprint("news", __name__)

# ── 全局组件 ──────────────────────────────────────────────
_vector_engine = None  # 延迟加载，避免启动时加载模型
_vector_lock = threading.Lock()
_fetching = False
_fetch_lock = threading.Lock()


def _get_vector_engine():
    """延迟初始化向量引擎（线程安全）。"""
    global _vector_engine
    if _vector_engine is None:
        with _vector_lock:
            # 双重检查
            if _vector_engine is None:
                try:
                    _vector_engine = NewsVectorEngine()
                    _vector_engine.initialize()
                    logger.info("向量引擎加载成功")
                except Exception as e:
                    logger.error("向量引擎加载失败: %s", e)
                    return None
    return _vector_engine


# ── 路由 ──────────────────────────────────────────────────

@news_bp.route("/api/news")
def api_news():
    """分页新闻列表，支持 source/category/keyword/date 过滤。"""
    db = NewsDB()
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 30, type=int)
    keyword = request.args.get("keyword")
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    offset = (page - 1) * per_page

    # 多值 source 参数: ?sources=A,B 或 ?source=A,B
    source = request.args.get("source") or request.args.get("sources")
    sources = source.split(",") if source else None

    # 多值 category 参数: ?categories=A,B 或 ?category=A,B
    category = request.args.get("category") or request.args.get("categories")
    categories = category.split(",") if category else None

    items = db.get_all(
        sources=sources, categories=categories, keyword=keyword,
        date_from=date_from, date_to=date_to,
        limit=per_page, offset=offset,
    )
    total = db.get_count(
        sources=sources, categories=categories, keyword=keyword,
        date_from=date_from, date_to=date_to,
    )

    return jsonify({"items": items, "total": total, "page": page, "per_page": per_page})


@news_bp.route("/api/news/status")
def api_status():
    """数据库统计信息。"""
    db = NewsDB()
    stats = db.get_source_stats()
    return jsonify({
        "db_total": db.get_total_count(),
        "source_stats": stats,
        "sources_count": len(stats),
        "sources": db.get_sources_list(),
    })


@news_bp.route("/api/news/semantic_search")
def api_semantic_search():
    """语义搜索：基于向量引擎的相似度检索。"""
    query = request.args.get("q", "")
    n = request.args.get("n", 20, type=int)

    # 多值 category
    category = request.args.get("category") or request.args.get("categories")
    categories = category.split(",") if category else None

    # 多值 source
    source = request.args.get("source") or request.args.get("sources")
    sources = source.split(",") if source else None

    if not query:
        return jsonify([])

    engine = _get_vector_engine()
    if not engine:
        return jsonify({"error": "向量引擎未就绪"}), 503

    results = engine.semantic_search(
        query=query, n=n, categories=categories, sources=sources,
    )
    return jsonify(results)


@news_bp.route("/api/news/categories")
def api_categories():
    """分类统计。"""
    db = NewsDB()
    return jsonify(db.get_category_stats())


@news_bp.route("/api/news/fetch", methods=["POST"])
def api_fetch():
    """手动触发新闻采集 + 向量处理管线。"""
    global _fetching

    with _fetch_lock:
        if _fetching:
            return jsonify({"error": "正在抓取中，请稍候"}), 409
        _fetching = True

    try:
        from modules.news.aggregator import AKSourceAggregator

        db = NewsDB()
        agg = AKSourceAggregator(db=db)
        result = agg.fetch_and_store(purge_days=7)

        # 手动抓取也运行向量处理管线
        new_items = result.get("new_items", [])
        new_row_ids = result.get("new_row_ids", [])
        if new_items:
            engine = _get_vector_engine()
            if engine:
                _run_vector_pipeline(engine, new_items, new_row_ids)
            if result.get("purged", 0) > 0 and engine:
                try:
                    engine.sync_chroma_purge()
                except Exception:
                    pass

        stats = db.get_source_stats()
        return jsonify({
            **result,
            "source_stats": stats,
            "sources_count": len(stats),
            "sources": db.get_sources_list(),
        })
    except Exception as e:
        logger.error("手动抓取失败: %s", e)
        return jsonify({"error": str(e)}), 500
    finally:
        _fetching = False


@news_bp.route("/api/news/clusters")
def api_clusters():
    """专题聚合列表。"""
    db = NewsDB()
    return jsonify(db.get_cluster_list())


@news_bp.route("/api/news/cluster/<path:cluster_id>")
def api_cluster_detail(cluster_id):
    """专题详情：返回该专题下的所有新闻。"""
    db = NewsDB()
    items = db.get_cluster_news(cluster_id)
    return jsonify(items)


# ── 向量处理管线 ──────────────────────────────────────────

def _run_vector_pipeline(vector_engine, items, row_ids):
    """向量处理管线：语义去重 → 分类 → 聚类 → ChromaDB 写入。"""
    db_path = NewsDB().db_path
    try:
        deduped = vector_engine.semantic_dedup(items)
        deduped_set = set()
        for d in deduped:
            # 用 (title, content前100字) 作为唯一标识
            deduped_set.add((d["title"], d.get("content", "")[:100]))

        deduped_items = []
        deduped_row_ids = []
        for item, rid in zip(items, row_ids):
            key = (item["title"], item.get("content", "")[:100])
            if key in deduped_set:
                deduped_items.append(item)
                deduped_row_ids.append(rid)

        # 删除语义重复条目
        removed_row_ids = [
            rid for item, rid in zip(items, row_ids)
            if (item["title"], item.get("content", "")[:100]) not in deduped_set
        ]
        if removed_row_ids:
            conn = sqlite3.connect(db_path)
            placeholders = ",".join("?" * len(removed_row_ids))
            conn.execute(
                f"DELETE FROM news WHERE id IN ({placeholders})",
                removed_row_ids,
            )
            conn.commit()
            conn.close()

        if not deduped_items:
            return

        categories = vector_engine.classify_items(deduped_items)
        cluster_ids = vector_engine.assign_clusters(deduped_items)

        conn = sqlite3.connect(db_path)
        for rid, cat, cid in zip(deduped_row_ids, categories, cluster_ids):
            cat_json = json.dumps(cat, ensure_ascii=False) if isinstance(cat, list) else cat
            conn.execute(
                "UPDATE news SET category = ?, cluster_id = ? WHERE id = ?",
                (cat_json, cid, rid),
            )
        conn.commit()
        conn.close()

        vector_engine.upsert_to_chroma(
            deduped_items, deduped_row_ids, categories, cluster_ids
        )
    except Exception as e:
        logger.error("向量处理管线异常: %s", e)
