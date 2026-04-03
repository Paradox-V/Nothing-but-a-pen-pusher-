# coding=utf-8
"""
RSS Flask 路由

提供 RSS 订阅源管理和条目查询的 REST API
"""

from flask import Blueprint, request, jsonify

from modules.rss.db import RSSDB
from modules.rss.fetcher import RSSFetcher
from modules.rss.discover import RSSHubDiscover

rss_bp = Blueprint("rss", __name__)


def _get_db() -> RSSDB:
    """获取数据库实例（后续可替换为 app context 注入）"""
    from flask import current_app
    db_path = current_app.config.get("RSS_DB_PATH", "data/rss.db")
    return RSSDB(db_path)


# ── 条目查询 ─────────────────────────────────────────────────


@rss_bp.route("/api/rss/items", methods=["GET"])
def get_items():
    """
    分页获取 RSS 条目

    Query params:
        feed_id (str, optional): 按源过滤
        days (int, default 7): 最近 N 天
        page (int, default 1): 页码
        page_size (int, default 30): 每页条数
    """
    feed_id = request.args.get("feed_id")
    days = request.args.get("days", 7, type=int)
    page = request.args.get("page", 1, type=int)
    page_size = request.args.get("page_size", 30, type=int)

    db = _get_db()
    result = db.get_items(
        feed_id=feed_id or None,
        days=days,
        page=page,
        page_size=page_size,
    )
    return jsonify(result)


# ── Feed CRUD ─────────────────────────────────────────────────


@rss_bp.route("/api/rss/feeds", methods=["GET"])
def get_feeds():
    """获取所有 RSS 源及其状态"""
    db = _get_db()
    feeds = db.get_feeds(enabled_only=False)
    return jsonify(feeds)


@rss_bp.route("/api/rss/feeds", methods=["POST"])
def add_feed():
    """
    添加 RSS 源

    Body JSON: {name, url, format?, max_items?, max_age_days?}
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"success": False, "error": "请求体不能为空"}), 400

    name = data.get("name", "").strip()
    url = data.get("url", "").strip()
    if not name or not url:
        return jsonify({"success": False, "error": "name 和 url 为必填项"}), 400

    kwargs = {}
    if "format" in data:
        kwargs["format"] = data["format"]
    if "max_items" in data and data["max_items"] is not None:
        kwargs["max_items"] = int(data["max_items"])
    if "max_age_days" in data and data["max_age_days"] is not None:
        kwargs["max_age_days"] = int(data["max_age_days"])

    db = _get_db()
    try:
        feed_id = db.add_feed(name, url, **kwargs)
        feed = db.get_feed(feed_id)
        return jsonify({"success": True, "feed": feed}), 201
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@rss_bp.route("/api/rss/feeds/<feed_id>", methods=["PUT"])
def update_feed(feed_id: str):
    """
    更新 RSS 源

    Body JSON: 任意可更新的 feed 字段
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"success": False, "error": "请求体不能为空"}), 400

    db = _get_db()

    # 检查 feed 是否存在
    existing = db.get_feed(feed_id)
    if not existing:
        return jsonify({"success": False, "error": f"源 {feed_id} 不存在"}), 404

    # 构建更新字段
    kwargs = {}
    allowed = {"name", "url", "format", "enabled", "max_items", "max_age_days"}
    for key in allowed:
        if key in data:
            kwargs[key] = data[key]

    if not kwargs:
        return jsonify({"success": False, "error": "没有有效的更新字段"}), 400

    try:
        ok = db.update_feed(feed_id, **kwargs)
        if ok:
            feed = db.get_feed(feed_id)
            return jsonify({"success": True, "feed": feed})
        else:
            return jsonify({"success": False, "error": "更新失败"}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@rss_bp.route("/api/rss/feeds/<feed_id>", methods=["DELETE"])
def delete_feed(feed_id: str):
    """删除 RSS 源及其所有条目"""
    db = _get_db()

    existing = db.get_feed(feed_id)
    if not existing:
        return jsonify({"success": False, "error": f"源 {feed_id} 不存在"}), 404

    ok = db.delete_feed(feed_id)
    if ok:
        return jsonify({"success": True})
    else:
        return jsonify({"success": False, "error": "删除失败"}), 500


# ── 手动触发抓取 ──────────────────────────────────────────────


@rss_bp.route("/api/rss/fetch", methods=["POST"])
def fetch_feeds():
    """手动触发 RSS 抓取"""
    try:
        db = _get_db()
        from flask import current_app
        proxy_url = current_app.config.get("PROXY_URL")
        fetcher = RSSFetcher(proxy_url=proxy_url)
        result = fetcher.fetch_and_store(db)
        return jsonify({"success": True, **result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ── 站点发现 ──────────────────────────────────────────────


@rss_bp.route("/api/rss/discover", methods=["POST"])
def discover_feed():
    """根据网站 URL 发现可订阅的 RSS 源"""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"success": False, "error": "请求体不能为空"}), 400

    url = data.get("url", "").strip()
    if not url:
        return jsonify({"success": False, "error": "请输入网站地址"}), 400

    from flask import current_app

    rsshub_config = current_app.config.get("RSSHUB_CONFIG", {})
    if not rsshub_config.get("sites"):
        return jsonify({"success": False, "error": "RSSHub 未配置"}), 503

    try:
        discoverer = RSSHubDiscover(rsshub_config)
        result = discoverer.discover(url)
        if not result.get("success"):
            status_code = 503 if "不可用" in result.get("error", "") else 400
            return jsonify(result), status_code
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@rss_bp.route("/api/rss/discover/custom", methods=["POST"])
def custom_discover_feed():
    """使用自定义 CSS 选择器生成 RSS 源"""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"success": False, "error": "请求体不能为空"}), 400

    url = data.get("url", "").strip()
    item_selector = data.get("item_selector", "").strip()
    if not url or not item_selector:
        return jsonify({"success": False, "error": "url 和 item_selector 为必填项"}), 400

    from flask import current_app

    rsshub_config = current_app.config.get("RSSHUB_CONFIG", {})

    try:
        discoverer = RSSHubDiscover(rsshub_config)
        result = discoverer.generic_discover(url, item_selector=item_selector)
        if not result.get("success"):
            return jsonify(result), 400
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
