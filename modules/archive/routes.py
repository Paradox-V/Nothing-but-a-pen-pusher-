"""归档浏览路由 — Flask Blueprint

提供冷库（历史数据）的只读访问接口。
所有查询代理到 scheduler HTTP API（端口 5001）。
"""

from flask import Blueprint, jsonify, request

from utils.auth import require_auth
from utils.scheduler_client import scheduler_get

archive_bp = Blueprint("archive", __name__)


@archive_bp.route("/api/archive/news")
@require_auth
def archive_news():
    """浏览归档新闻。"""
    params = {"page": str(request.args.get("page", 1, type=int)),
              "per_page": str(request.args.get("per_page", 30, type=int))}
    for key in ("keyword", "date_from", "date_to"):
        val = request.args.get(key)
        if val:
            params[key] = val
    result = scheduler_get("/archive/news", params=params, timeout=30)
    if result is not None:
        return jsonify(result)
    return jsonify({"error": "Archive service unavailable"}), 503


@archive_bp.route("/api/archive/hotlist")
@require_auth
def archive_hotlist():
    """浏览归档热榜。"""
    params = {"page": str(request.args.get("page", 1, type=int)),
              "per_page": str(request.args.get("per_page", 30, type=int))}
    platform = request.args.get("platform")
    if platform:
        params["platform"] = platform
    result = scheduler_get("/archive/hotlist", params=params, timeout=30)
    if result is not None:
        return jsonify(result)
    return jsonify({"error": "Archive service unavailable"}), 503


@archive_bp.route("/api/archive/rss")
@require_auth
def archive_rss():
    """浏览归档 RSS。"""
    params = {"page": str(request.args.get("page", 1, type=int)),
              "per_page": str(request.args.get("per_page", 30, type=int))}
    for key in ("feed_id", "keyword"):
        val = request.args.get(key)
        if val:
            params[key] = val
    result = scheduler_get("/archive/rss", params=params, timeout=30)
    if result is not None:
        return jsonify(result)
    return jsonify({"error": "Archive service unavailable"}), 503
