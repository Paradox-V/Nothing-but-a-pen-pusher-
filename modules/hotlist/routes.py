# coding=utf-8
"""热榜模块 Flask Blueprint 路由"""

from flask import Blueprint, request, jsonify

from modules.hotlist.db import HotlistDB

hotlist_bp = Blueprint("hotlist", __name__)


@hotlist_bp.route("/api/hotlist", methods=["GET"])
def get_hotlist():
    """分页获取热榜列表。

    Query params:
        platform   (str)  - 可选，按平台 ID 过滤
        hours      (int)  - 回溯小时数，默认 24
        page       (int)  - 页码，默认 1
        page_size  (int)  - 每页条数，默认 30
    """
    platform = request.args.get("platform")
    hours = request.args.get("hours", 24, type=int)
    page = request.args.get("page", 1, type=int)
    page_size = request.args.get("page_size", 30, type=int)

    db = HotlistDB()
    result = db.get_items(
        platform=platform,
        hours=hours,
        page=page,
        page_size=page_size,
    )
    return jsonify(result)


@hotlist_bp.route("/api/hotlist/platforms", methods=["GET"])
def get_platforms():
    """获取各平台统计信息。"""
    db = HotlistDB()
    stats = db.get_platform_stats()
    # 将字段名映射为路由规范要求的格式
    platforms = []
    for row in stats:
        platforms.append({
            "platform": row["platform"],
            "platform_name": row["platform_name"],
            "count": row["item_count"],
            "latest": row["latest_crawl_time"],
        })
    return jsonify(platforms)


@hotlist_bp.route("/api/hotlist/fetch", methods=["POST"])
def fetch_hotlist():
    """触发热榜抓取信号，scheduler 执行。"""
    from utils.crawl_trigger import CrawlTrigger
    trigger = CrawlTrigger()
    trigger.trigger("hotlist")
    return jsonify({"success": True, "message": "已触发热榜抓取信号"})


@hotlist_bp.route("/api/hotlist/status", methods=["GET"])
def get_status():
    """获取热榜抓取状态。"""
    db = HotlistDB()
    last_crawl_time = db.get_last_crawl_time()
    return jsonify({"last_crawl_time": last_crawl_time})
