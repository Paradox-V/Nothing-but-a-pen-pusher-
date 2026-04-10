"""
新闻模块 - Flask Blueprint 路由

从 news_viewer.py 提取的全部 API 路由，
包括新闻列表、状态查询、语义搜索、分类统计、专题聚合、手动抓取。
"""

import logging

from flask import Blueprint, jsonify, request

from modules.news.db import NewsDB

logger = logging.getLogger(__name__)

news_bp = Blueprint("news", __name__)


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
    """语义搜索：代理到 scheduler 内部向量 API，零额外内存。"""
    query = request.args.get("q", "")
    n = request.args.get("n", 20, type=int)

    if not query:
        return jsonify([])

    category = request.args.get("category") or request.args.get("categories")
    source = request.args.get("source") or request.args.get("sources")

    from utils.scheduler_client import scheduler_get
    params = {"q": query, "n": str(n)}
    if category:
        params["category"] = category
    if source:
        params["source"] = source
    result = scheduler_get("/semantic_search", params=params, timeout=30)
    if result is not None:
        return jsonify(result)

    return jsonify({"error": "语义搜索服务不可用，请检查 scheduler 是否运行"}), 503


@news_bp.route("/api/news/categories")
def api_categories():
    """分类统计。"""
    db = NewsDB()
    return jsonify(db.get_category_stats())


@news_bp.route("/api/news/fetch", methods=["POST"])
def api_fetch():
    """触发新闻采集。通过信号通知 scheduler 执行，避免并发冲突。"""
    from utils.crawl_trigger import CrawlTrigger
    trigger = CrawlTrigger()
    trigger.trigger("news")
    return jsonify({"success": True, "message": "已触发新闻抓取信号，scheduler 将在下一个周期执行"})


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
