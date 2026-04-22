# coding=utf-8
"""
RSS Flask 路由

提供 RSS 订阅源管理和条目查询的 REST API
"""

import logging

from flask import Blueprint, request, jsonify

from modules.rss.db import RSSDB
from modules.rss.fetcher import RSSFetcher
from modules.rss.discover import RSSHubDiscover
from utils.auth import require_auth
from utils.url_security import validate_url

logger = logging.getLogger(__name__)

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
        keyword (str, optional): 搜索标题或摘要
    """
    feed_id = request.args.get("feed_id")
    days = request.args.get("days", 7, type=int)
    page = request.args.get("page", 1, type=int)
    page_size = request.args.get("page_size", 30, type=int)
    keyword = request.args.get("keyword")

    db = _get_db()
    result = db.get_items(
        feed_id=feed_id or None,
        days=days,
        page=page,
        page_size=page_size,
        keyword=keyword or None,
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
@require_auth
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

    # SSRF 校验
    is_safe, url_error = validate_url(url)
    if not is_safe:
        return jsonify({"success": False, "error": f"URL 校验失败: {url_error}"}), 400

    kwargs = {}
    if "format" in data:
        kwargs["format"] = data["format"]
    if "max_items" in data and data["max_items"] is not None:
        kwargs["max_items"] = int(data["max_items"])
    if "max_age_days" in data and data["max_age_days"] is not None:
        kwargs["max_age_days"] = int(data["max_age_days"])

    # 从用户 JWT 获取 owner_id（若有）
    try:
        from flask import g
        owner_id = getattr(g, "current_user_id", None)
        if owner_id:
            kwargs["owner_id"] = owner_id
    except Exception:
        pass

    db = _get_db()
    try:
        feed_id = db.add_feed(name, url, **kwargs)
        feed = db.get_feed(feed_id)
        return jsonify({"success": True, "feed": feed}), 201
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@rss_bp.route("/api/rss/feeds/<feed_id>", methods=["PUT"])
@require_auth
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

    # 构建更新字段（带类型校验）
    kwargs = {}
    allowed = {"name", "url", "format", "enabled", "max_items", "max_age_days"}
    for key in allowed:
        if key in data:
            val = data[key]
            if key == "enabled":
                if not isinstance(val, bool):
                    return jsonify({"success": False, "error": "enabled 必须为布尔值"}), 400
            elif key in ("max_items", "max_age_days"):
                try:
                    val = int(val)
                    if val < 0:
                        return jsonify({"success": False, "error": f"{key} 不能为负数"}), 400
                except (TypeError, ValueError):
                    return jsonify({"success": False, "error": f"{key} 必须为整数"}), 400
            kwargs[key] = val

    # 如果更新了 URL，需要重新校验
    if "url" in kwargs:
        is_safe, url_error = validate_url(kwargs["url"])
        if not is_safe:
            return jsonify({"success": False, "error": f"URL 校验失败: {url_error}"}), 400

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
@require_auth
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
@require_auth
def fetch_feeds():
    """触发 RSS 抓取信号，scheduler 执行。"""
    from utils.crawl_trigger import CrawlTrigger
    trigger = CrawlTrigger()
    trigger.trigger("rss")
    return jsonify({"success": True, "message": "已触发 RSS 抓取信号"})


# ── 站点发现 ──────────────────────────────────────────────


@rss_bp.route("/api/rss/discover", methods=["POST"])
@require_auth
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
@require_auth
def custom_discover_feed():
    """使用自定义 CSS 选择器生成 RSS 源"""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"success": False, "error": "请求体不能为空"}), 400

    url = data.get("url", "").strip()
    item_selector = data.get("item_selector", "").strip()
    if not url or not item_selector:
        return jsonify({"success": False, "error": "url 和 item_selector 为必填项"}), 400

    title_selector = data.get("title_selector", "").strip() or None

    from flask import current_app

    rsshub_config = current_app.config.get("RSSHUB_CONFIG", {})

    try:
        discoverer = RSSHubDiscover(rsshub_config)
        result = discoverer.generic_discover(url, item_selector=item_selector, title_selector=title_selector)
        if not result.get("success"):
            return jsonify(result), 400
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ── 微信公众号 RSS 发现 ──────────────────────────────────────


@rss_bp.route("/api/rss/discover/wechat", methods=["POST"])
@require_auth
def discover_wechat():
    """将微信公众号 URL 或名称转化为 RSS Feed URL。"""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"success": False, "error": "请求体不能为空"}), 400

    url_or_name = (data.get("url") or data.get("name") or "").strip()
    if not url_or_name:
        return jsonify({"success": False, "error": "请提供公众号链接或名称"}), 400

    from flask import current_app
    from modules.rss.wechat_mp import WechatMPConverter
    from utils.config import load_config

    config = load_config()
    rsshub_config = current_app.config.get("RSSHUB_CONFIG", {})
    rsshub_base = rsshub_config.get("base_url", "http://127.0.0.1:1200")
    wechat_mp_cfg = config.get("wechat_mp", {})

    converter = WechatMPConverter(rsshub_base_url=rsshub_base,
                                  wechat_mp_config=wechat_mp_cfg)
    result = converter.to_rss_url(url_or_name)
    if not result.get("success"):
        return jsonify(result), 400
    return jsonify(result)


@rss_bp.route("/api/rss/detect-type", methods=["POST"])
@require_auth
def detect_feed_type():
    """自动检测 URL 类型，返回建议的处理方式。"""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"success": False, "error": "请求体不能为空"}), 400

    url = data.get("url", "").strip()
    if not url:
        return jsonify({"success": False, "error": "请提供 URL"}), 400

    from modules.rss.wechat_mp import WechatMPConverter
    from urllib.parse import urlparse

    result = {"url": url, "type": "unknown", "suggested_action": "generic_discover"}

    try:
        parsed_url = urlparse(url)
        hostname = parsed_url.hostname or ""
    except Exception:
        hostname = ""

    converter = WechatMPConverter()
    if converter.is_wechat_mp_url(url):
        result["type"] = "wechat_mp"
        result["suggested_action"] = "wechat_discover"
        result["description"] = "微信公众号"
    elif hostname == "weibo.com" or hostname.endswith(".weibo.com"):
        result["type"] = "weibo"
        result["suggested_action"] = "rsshub_discover"
        result["description"] = "微博"
    elif hostname == "zhihu.com" or hostname.endswith(".zhihu.com"):
        result["type"] = "zhihu"
        result["suggested_action"] = "rsshub_discover"
        result["description"] = "知乎"
    elif url.endswith(".xml") or "rss" in url.lower() or "feed" in url.lower() or "atom" in url.lower():
        result["type"] = "rss_url"
        result["suggested_action"] = "direct_subscribe"
        result["description"] = "RSS/Atom 订阅地址"
    else:
        result["type"] = "website"
        result["suggested_action"] = "generic_discover"
        result["description"] = "普通网站"

    return jsonify(result)


# ── AI RSS 搜索 ───────────────────────────────────────────────


@rss_bp.route("/api/rss/search", methods=["POST"])
@require_auth
def search_rss():
    """根据话题关键词搜索相关 RSS 源。"""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"success": False, "error": "请求体不能为空"}), 400

    topic = data.get("topic", "").strip()
    if not topic:
        return jsonify({"success": False, "error": "请提供搜索话题"}), 400

    max_results = min(data.get("max_results", 10), 20)

    try:
        from utils.rss_search import RSSSearcher
        from utils.config import load_config
        config = load_config()
        searcher = RSSSearcher(config.get("rss_search", {}))
        results = searcher.search(topic, max_results=max_results)
        return jsonify({
            "success": True,
            "topic": topic,
            "results": results,
        })
    except Exception:
        logger.exception("search_rss failed for topic: %s", topic)
        return jsonify({"success": False, "error": "搜索服务暂时不可用"}), 500


@rss_bp.route("/api/rss/bulk-subscribe", methods=["POST"])
@require_auth
def bulk_subscribe():
    """批量订阅 RSS 源。"""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"success": False, "error": "请求体不能为空"}), 400

    feeds = data.get("feeds", [])
    if not feeds:
        return jsonify({"success": False, "error": "请提供订阅源列表"}), 400
    if len(feeds) > 20:
        return jsonify({"success": False, "error": "单次最多订阅 20 个源"}), 400

    db = _get_db()
    success = 0
    failed = 0
    errors = []

    for item in feeds:
        name = item.get("name", "").strip()
        url = item.get("url", "").strip()
        if not name or not url:
            errors.append({"url": url, "error": "name 和 url 不能为空"})
            failed += 1
            continue

        is_safe, url_error = validate_url(url)
        if not is_safe:
            errors.append({"url": url, "error": f"URL 校验失败: {url_error}"})
            failed += 1
            continue

        try:
            db.add_feed(name, url)
            success += 1
        except Exception:
            logger.warning("bulk_subscribe: add_feed failed for url=%s", url)
            errors.append({"url": url, "error": "添加失败"})
            failed += 1

    return jsonify({
        "success": success,
        "failed": failed,
        "total": len(feeds),
        "errors": errors,
    })
