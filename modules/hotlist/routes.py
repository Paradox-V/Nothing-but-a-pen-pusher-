# coding=utf-8
"""热榜模块 Flask Blueprint 路由"""

from flask import Blueprint, request, jsonify

from modules.hotlist.db import HotlistDB
from utils.auth import require_auth

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
@require_auth
def fetch_hotlist():
    """触发热榜抓取。

    如果 scheduler 正在运行，写入信号等待调度；
    如果 scheduler 不在运行，尝试同步抓取。
    返回抓取状态供前端轮询。
    """
    from utils.crawl_trigger import CrawlTrigger
    trigger = CrawlTrigger()

    # 检查 scheduler 是否在线：看是否有 pending 信号被消费
    scheduler_online = _check_scheduler_online(trigger)

    if scheduler_online:
        # 写入信号，等 scheduler 处理
        trigger.trigger("hotlist")
        return jsonify({
            "status": "pending",
            "mode": "async",
            "message": "已触发热榜抓取信号，等待 scheduler 处理",
        })
    else:
        # scheduler 不在线，尝试同步抓取
        try:
            _sync_fetch_hotlist()
            return jsonify({
                "status": "completed",
                "mode": "sync",
                "message": "热榜数据已同步更新",
            })
        except Exception as e:
            return jsonify({
                "status": "failed",
                "mode": "sync",
                "message": f"热榜抓取失败: {str(e)}",
                "scheduler_online": False,
            }), 500


@hotlist_bp.route("/api/hotlist/fetch_status", methods=["GET"])
def fetch_status():
    """查询最近一次热榜抓取的状态。"""
    from utils.crawl_trigger import CrawlTrigger
    trigger = CrawlTrigger()

    pending = trigger.poll_pending()
    is_pending = "hotlist" in pending

    # 查最近一次抓取时间
    db = HotlistDB()
    last_crawl = db.get_last_crawl_time()

    if is_pending:
        return jsonify({
            "status": "pending",
            "message": "热榜抓取中，请稍候...",
            "last_crawl_time": last_crawl,
        })

    return jsonify({
        "status": "idle",
        "message": "无待处理任务",
        "last_crawl_time": last_crawl,
    })


@hotlist_bp.route("/api/hotlist/status", methods=["GET"])
def get_status():
    """获取热榜抓取状态。"""
    db = HotlistDB()
    last_crawl_time = db.get_last_crawl_time()
    return jsonify({"last_crawl_time": last_crawl_time})


def _check_scheduler_online(trigger) -> bool:
    """简单判断 scheduler 是否在线：写入一个 test 信号再检查是否被消费。

    更实用的方式：检查 scheduler 心跳文件。这里用简化方案：
    检查 data/.scheduler_heartbeat 文件是否存在且在 30 秒内更新过。
    """
    import os
    heartbeat = "data/.scheduler_heartbeat"
    if not os.path.exists(heartbeat):
        return False
    try:
        mtime = os.path.getmtime(heartbeat)
        import time
        return (time.time() - mtime) < 30
    except OSError:
        return False


def _sync_fetch_hotlist():
    """同步抓取热榜数据（scheduler 不在线时的后备方案）。"""
    import time as _time
    from modules.hotlist.fetcher import DataFetcher

    fetcher = DataFetcher()
    db = HotlistDB()

    items, failed = fetcher.fetch_all_platforms()

    if items:
        crawl_time = _time.strftime("%Y-%m-%d %H:%M:%S")
        db.insert_batch(items, crawl_time=crawl_time)

    return len(items)
