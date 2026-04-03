# coding=utf-8
"""热榜模块 Flask Blueprint 路由"""

from flask import Blueprint, request, jsonify
from datetime import datetime

from modules.hotlist.db import HotlistDB
from modules.hotlist.fetcher import DataFetcher
from utils.config import load_config

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
    """手动触发热榜数据抓取。

    从 config.yaml 读取 api_url 和 platforms 列表，
    调用 DataFetcher 抓取数据并写入数据库。
    """
    config = load_config()
    hotlist_cfg = config.get("hotlist", {})

    api_url = hotlist_cfg.get("api_url")
    platforms = hotlist_cfg.get("platforms")
    proxy_url = config.get("proxy", {}).get("url")

    fetcher = DataFetcher(api_url=api_url, proxy_url=proxy_url)
    items, failed_ids = fetcher.fetch_all_platforms(platform_ids=platforms)

    db = HotlistDB()
    crawl_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    inserted = 0
    try:
        db.insert_batch(items, crawl_time)
        inserted = len(items)
    except Exception as e:
        return jsonify({
            "success": False,
            "inserted": 0,
            "failed": len(failed_ids),
            "error": str(e),
        }), 500

    return jsonify({
        "success": True,
        "inserted": inserted,
        "failed": len(failed_ids),
    })


@hotlist_bp.route("/api/hotlist/status", methods=["GET"])
def get_status():
    """获取热榜抓取状态。"""
    db = HotlistDB()
    last_crawl_time = db.get_last_crawl_time()
    return jsonify({"last_crawl_time": last_crawl_time})
